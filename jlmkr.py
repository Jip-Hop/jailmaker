#!/usr/bin/env python3

"""Create persistent Linux 'jails' on TrueNAS SCALE, \
with full access to all files via bind mounts, \
thanks to systemd-nspawn!"""

__version__ = "2.1.0"
__author__ = "Jip-Hop"
__copyright__ = "Copyright (C) 2023, Jip-Hop"
__license__ = "LGPL-3.0-only"
__disclaimer__ = """USE THIS SCRIPT AT YOUR OWN RISK!
IT COMES WITHOUT WARRANTY AND IS NOT SUPPORTED BY IXSYSTEMS."""

import argparse
import configparser
import contextlib
import hashlib
import io
import json
import os
import platform
import re
import readline
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import urllib.request
from collections import defaultdict
from inspect import cleandoc
from pathlib import Path, PurePath
from textwrap import dedent

DEFAULT_CONFIG = """startup=0
gpu_passthrough_intel=0
gpu_passthrough_nvidia=0
# Turning off seccomp filtering improves performance at the expense of security
seccomp=1

# Below you may add additional systemd-nspawn flags behind systemd_nspawn_user_args=
# To mount host storage in the jail, you may add: --bind='/mnt/pool/dataset:/home'
# To readonly mount host storage, you may add: --bind-ro=/etc/certificates
# To use macvlan networking add: --network-macvlan=eno1 --resolv-conf=bind-host
# To use bridge networking add: --network-bridge=br1 --resolv-conf=bind-host
# Ensure to change eno1/br1 to the interface name you want to use
# To allow syscalls required by docker add: --system-call-filter='add_key keyctl bpf'
systemd_nspawn_user_args=

# Specify command/script to run on the HOST before starting the jail
# For example to load kernel modules and config kernel settings
pre_start_hook=
# pre_start_hook=#!/usr/bin/bash
#     set -euo pipefail
#     echo 'PRE_START_HOOK_EXAMPLE'
#     echo 1 > /proc/sys/net/ipv4/ip_forward
#     modprobe br_netfilter
#     echo 1 > /proc/sys/net/bridge/bridge-nf-call-iptables
#     echo 1 > /proc/sys/net/bridge/bridge-nf-call-ip6tables

# Specify command/script to run on the HOST after starting the jail
# For example to attach to multiple bridge interfaces 
# when using --network-veth-extra=ve-myjail-1:veth1
post_start_hook=
# post_start_hook=#!/usr/bin/bash
#     set -euo pipefail
#     echo 'POST_START_HOOK_EXAMPLE'
#     ip link set dev ve-myjail-1 master br2
#     ip link set dev ve-myjail-1 up

# Specify a command/script to run on the HOST after stopping the jail
post_stop_hook=
# post_stop_hook=echo 'POST_STOP_HOOK_EXAMPLE'

# Only used while creating the jail
distro=debian
release=bookworm

# Specify command/script to run IN THE JAIL on the first start (once networking is ready in the jail)
# Useful to install packages on top of the base rootfs
initial_setup=
# initial_setup=bash -c 'apt-get update && apt-get -y upgrade'

# Usually no need to change systemd_run_default_args
systemd_run_default_args=--collect
    --property=Delegate=yes
    --property=RestartForceExitStatus=133
    --property=SuccessExitStatus=133
    --property=TasksMax=infinity
    --property=Type=notify
    --setenv=SYSTEMD_NSPAWN_LOCK=0
    --property=KillMode=mixed

# Usually no need to change systemd_nspawn_default_args
systemd_nspawn_default_args=--bind-ro=/sys/module
    --boot
    --inaccessible=/sys/module/apparmor
    --quiet
    --keep-unit"""

# Use mostly default settings for systemd-nspawn but with systemd-run instead of a service file:
# https://github.com/systemd/systemd/blob/main/units/systemd-nspawn%40.service.in
# Use TasksMax=infinity since this is what docker does:
# https://github.com/docker/engine/blob/master/contrib/init/systemd/docker.service

# Use SYSTEMD_NSPAWN_LOCK=0: otherwise jail won't start jail after a shutdown (but why?)
# Would give "directory tree currently busy" error and I'd have to run
# `rm /run/systemd/nspawn/locks/*` and remove the .lck file from jail_path
# Disabling locking isn't a big deal as systemd-nspawn will prevent starting a container
# with the same name anyway: as long as we're starting jails using this script,
# it won't be possible to start the same jail twice

# Always add --bind-ro=/sys/module to make lsmod happy
# https://manpages.debian.org/bookworm/manpages/sysfs.5.en.html

DOWNLOAD_SCRIPT_DIGEST = (
    "cfcb5d08b24187d108f2ab0d21a6cc4b73dcd7f5d7dfc80803bfd7f1642d638d"
)
SCRIPT_PATH = os.path.realpath(__file__)
SCRIPT_NAME = os.path.basename(SCRIPT_PATH)
SCRIPT_DIR_PATH = os.path.dirname(SCRIPT_PATH)
COMMAND_NAME = os.path.basename(__file__)
JAILS_DIR_PATH = os.path.join(SCRIPT_DIR_PATH, "jails")
JAIL_CONFIG_NAME = "config"
JAIL_ROOTFS_NAME = "rootfs"
SHORTNAME = "jlmkr"

# Only set a color if we have an interactive tty
if sys.stdout.isatty():
    BOLD = "\033[1m"
    RED = "\033[91m"
    YELLOW = "\033[93m"
    UNDERLINE = "\033[4m"
    NORMAL = "\033[0m"
else:
    BOLD = RED = YELLOW = UNDERLINE = NORMAL = ""

DISCLAIMER = f"""{YELLOW}{BOLD}{__disclaimer__}{NORMAL}"""

# Used in parser getters to indicate the default behavior when a specific
# option is not found. Created to enable `None` as a valid fallback value.
_UNSET = object()


class KeyValueParser(configparser.ConfigParser):
    """Simple comment preserving parser based on ConfigParser.
    Reads a file containing key/value pairs and/or comments.
    Values can span multiple lines, as long as they are indented
    deeper than the first line of the value. Comments or keys
    must NOT be indented.
    """

    def __init__(self, *args, **kwargs):
        # Set defaults if not specified by user
        if "interpolation" not in kwargs:
            kwargs["interpolation"] = None
        if "allow_no_value" not in kwargs:
            kwargs["allow_no_value"] = True
        if "comment_prefixes" not in kwargs:
            kwargs["comment_prefixes"] = "#"

        super().__init__(*args, **kwargs)

        # Backup _comment_prefixes
        self._comment_prefixes_backup = self._comment_prefixes
        # Unset _comment_prefixes so comments won't be skipped
        self._comment_prefixes = ()
        # Starting point for the comment IDs
        self._comment_id = 0
        # Default delimiter to use
        delimiter = self._delimiters[0]
        # Template to store comments as key value pair
        self._comment_template = "#{0} " + delimiter + " {1}"
        # Regex to match the comment prefix
        self._comment_regex = re.compile(
            r"^#\d+\s*" + re.escape(delimiter) + r"[^\S\n]*"
        )
        # Regex to match cosmetic newlines (skips newlines in multiline values):
        # consecutive whitespace from start of line followed by a line not starting with whitespace
        self._cosmetic_newlines_regex = re.compile(r"^(\s+)(?=^\S)", re.MULTILINE)
        # Dummy section name
        self._section_name = "a"

    def _find_cosmetic_newlines(self, text):
        # Indices of the lines containing cosmetic newlines
        cosmetic_newline_indices = set()
        for match in re.finditer(self._cosmetic_newlines_regex, text):
            start_index = text.count("\n", 0, match.start())
            end_index = start_index + text.count("\n", match.start(), match.end())
            cosmetic_newline_indices.update(range(start_index, end_index))

        return cosmetic_newline_indices

    # TODO: can I create a solution which not depends on the internal _read method?
    def _read(self, fp, fpname):
        lines = fp.readlines()
        cosmetic_newline_indices = self._find_cosmetic_newlines("".join(lines))
        # Preprocess config file to preserve comments
        for i, line in enumerate(lines):
            if i in cosmetic_newline_indices or line.startswith(
                self._comment_prefixes_backup
            ):
                # Store cosmetic newline or comment with unique key
                lines[i] = self._comment_template.format(self._comment_id, line)
                self._comment_id += 1

        # Convert to in-memory file and prepend a dummy section header
        lines = io.StringIO(f"[{self._section_name}]\n" + "".join(lines))
        # Feed preprocessed file to original _read method
        return super()._read(lines, fpname)

    def read_default_string(self, string, source="<string>"):
        # Ignore all comments when parsing default key/values
        string = "\n".join(
            [
                line
                for line in string.splitlines()
                if not line.startswith(self._comment_prefixes_backup)
            ]
        )
        # Feed preprocessed file to original _read method
        return super()._read(io.StringIO("[DEFAULT]\n" + string), source)

    def write(self, fp, space_around_delimiters=False):
        # Write the config to an in-memory file
        with io.StringIO() as sfile:
            super().write(sfile, space_around_delimiters)
            # Start from the beginning of sfile
            sfile.seek(0)

            line = sfile.readline()
            # Throw away lines until we reach the dummy section header
            while line.strip() != f"[{self._section_name}]":
                line = sfile.readline()

            lines = sfile.readlines()

        for i, line in enumerate(lines):
            # Remove the comment id prefix
            lines[i] = self._comment_regex.sub("", line, 1)

        fp.write("".join(lines).rstrip())

    # Set value for specified option key
    def my_set(self, option, value):
        if isinstance(value, bool):
            value = str(int(value))
        elif isinstance(value, list):
            value = str("\n    ".join(value))
        elif not isinstance(value, str):
            value = str(value)

        super().set(self._section_name, option, value)

    # Return value for specified option key
    def my_get(self, option, fallback=_UNSET):
        return super().get(self._section_name, option, fallback=fallback)

    # Return value converted to boolean for specified option key
    def my_getboolean(self, option, fallback=_UNSET):
        return super().getboolean(self._section_name, option, fallback=fallback)


class ExceptionWithParser(Exception):
    def __init__(self, parser, message):
        self.parser = parser
        self.message = message
        super().__init__(message)


# Workaround for exit_on_error=False not applying to:
# "error: the following arguments are required"
# https://github.com/python/cpython/issues/103498
class CustomSubParser(argparse.ArgumentParser):
    def error(self, message):
        if self.exit_on_error:
            super().error(message)
        else:
            raise ExceptionWithParser(self, message)


class Chroot:
    def __init__(self, new_root):
        self.new_root = new_root
        self.old_root = None
        self.initial_cwd = None

    def __enter__(self):
        self.old_root = os.open("/", os.O_PATH)
        self.initial_cwd = os.path.abspath(os.getcwd())
        os.chdir(self.new_root)
        os.chroot(".")

    def __exit__(self, exc_type, exc_value, traceback):
        os.chdir(self.old_root)
        os.chroot(".")
        os.close(self.old_root)
        os.chdir(self.initial_cwd)


def eprint(*args, **kwargs):
    """
    Print to stderr.
    """
    print(*args, file=sys.stderr, **kwargs)


def fail(*args, **kwargs):
    """
    Print to stderr and exit.
    """
    eprint(*args, **kwargs)
    sys.exit(1)


def get_jail_path(jail_name):
    return os.path.join(JAILS_DIR_PATH, jail_name)


def get_jail_config_path(jail_name):
    return os.path.join(get_jail_path(jail_name), JAIL_CONFIG_NAME)


def get_jail_rootfs_path(jail_name):
    return os.path.join(get_jail_path(jail_name), JAIL_ROOTFS_NAME)


# Test intel GPU by decoding mp4 file (output is discarded)
# Run the commands below in the jail:
# curl -o bunny.mp4 https://www.w3schools.com/html/mov_bbb.mp4
# ffmpeg -hwaccel vaapi -hwaccel_device /dev/dri/renderD128 -hwaccel_output_format vaapi -i bunny.mp4 -f null - && echo 'SUCCESS!'


def passthrough_intel(gpu_passthrough_intel, systemd_nspawn_additional_args):
    if not gpu_passthrough_intel:
        return

    if not os.path.exists("/dev/dri"):
        eprint(
            dedent(
                """
        No intel GPU seems to be present...
        Skip passthrough of intel GPU."""
            )
        )
        return

    systemd_nspawn_additional_args.append("--bind=/dev/dri")


def passthrough_nvidia(
    gpu_passthrough_nvidia, systemd_nspawn_additional_args, jail_name
):
    jail_rootfs_path = get_jail_rootfs_path(jail_name)
    ld_so_conf_path = Path(
        os.path.join(jail_rootfs_path), f"etc/ld.so.conf.d/{SHORTNAME}-nvidia.conf"
    )

    if not gpu_passthrough_nvidia:
        # Cleanup the config file we made when passthrough was enabled
        ld_so_conf_path.unlink(missing_ok=True)
        return

    # Load the nvidia kernel module
    if subprocess.run(["modprobe", "nvidia-current-uvm"]).returncode != 0:
        eprint(
            dedent(
                """
            Failed to load nvidia-current-uvm kernel module."""
            )
        )

    # Run nvidia-smi to initialize the nvidia driver
    # If we can't run nvidia-smi successfully,
    # then nvidia-container-cli list will fail too:
    # we shouldn't continue with gpu passthrough
    if subprocess.run(["nvidia-smi", "-f", "/dev/null"]).returncode != 0:
        eprint("Skip passthrough of nvidia GPU.")
        return

    try:
        # Get list of libraries
        nvidia_libraries = set(
            [
                x
                for x in subprocess.check_output(
                    ["nvidia-container-cli", "list", "--libraries"]
                )
                .decode()
                .split("\n")
                if x
            ]
        )
        # Get full list of files, but excluding library ones from above
        nvidia_files = set(
            (
                [
                    x
                    for x in subprocess.check_output(["nvidia-container-cli", "list"])
                    .decode()
                    .split("\n")
                    if x and x not in nvidia_libraries
                ]
            )
        )
    except Exception:
        eprint(
            dedent(
                """
        Unable to detect which nvidia driver files to mount.
        Skip passthrough of nvidia GPU."""
            )
        )
        return

    # Also make nvidia-smi available inside the path,
    # while mounting the symlink will be resolved and nvidia-smi will appear as a regular file
    nvidia_files.add("/usr/bin/nvidia-smi")

    nvidia_mounts = []

    for file_path in nvidia_files:
        if not os.path.exists(file_path):
            # Don't try to mount files not present on the host
            print(f"Skipped mounting {file_path}, it doesn't exist on the host...")
            continue

        if file_path.startswith("/dev/"):
            nvidia_mounts.append(f"--bind={file_path}")
        else:
            nvidia_mounts.append(f"--bind-ro={file_path}")

    # Check if the parent dir exists where we want to write our conf file
    if ld_so_conf_path.parent.exists():
        library_folders = set(str(Path(x).parent) for x in nvidia_libraries)
        # Add the library folders as mounts
        for lf in library_folders:
            nvidia_mounts.append(f"--bind-ro={lf}")

        # Only write if the conf file doesn't yet exist or has different contents
        existing_conf_libraries = set()
        if ld_so_conf_path.exists():
            existing_conf_libraries.update(
                x for x in ld_so_conf_path.read_text().splitlines() if x
            )

        if library_folders != existing_conf_libraries:
            print("\n".join(x for x in library_folders), file=ld_so_conf_path.open("w"))

            # Run ldconfig inside systemd-nspawn jail with nvidia mounts...
            subprocess.run(
                [
                    "systemd-nspawn",
                    "--quiet",
                    f"--machine={jail_name}",
                    f"--directory={jail_rootfs_path}",
                    *nvidia_mounts,
                    "ldconfig",
                ]
            )
    else:
        eprint(
            dedent(
                """
            Unable to write the ld.so.conf.d directory inside the jail (it doesn't exist).
            Skipping call to ldconfig.
            The nvidia drivers will probably not be detected..."""
            )
        )

    systemd_nspawn_additional_args += nvidia_mounts


def exec_jail(jail_name, cmd):
    """
    Execute a command in the jail with given name.
    """
    return subprocess.run(
        [
            "systemd-run",
            "--machine",
            jail_name,
            "--quiet",
            "--pipe",
            "--wait",
            "--collect",
            "--service-type=exec",
            *cmd,
        ]
    ).returncode


def status_jail(jail_name, args):
    """
    Show the status of the systemd service wrapping the jail with given name.
    """
    # Alternatively `machinectl status jail_name` could be used
    return subprocess.run(
        ["systemctl", "status", f"{SHORTNAME}-{jail_name}", *args]
    ).returncode


def log_jail(jail_name, args):
    """
    Show the log file of the jail with given name.
    """
    return subprocess.run(
        ["journalctl", "-u", f"{SHORTNAME}-{jail_name}", *args]
    ).returncode


def shell_jail(args):
    """
    Open a shell in the jail with given name.
    """
    return subprocess.run(["machinectl", "shell"] + args).returncode


def parse_config_file(jail_config_path):
    config = KeyValueParser()
    # Read default config to fallback to default values
    # for keys not found in the jail_config_path file
    config.read_default_string(DEFAULT_CONFIG)
    try:
        with open(jail_config_path, "r") as fp:
            config.read_file(fp)
        return config
    except FileNotFoundError:
        eprint(f"Unable to find config file: {jail_config_path}.")
        return


def systemd_escape_path(path):
    """
    Escape path containing spaces, while properly handling backslashes in filenames.
    https://manpages.debian.org/bookworm/systemd/systemd.syntax.7.en.html#QUOTING
    https://manpages.debian.org/bookworm/systemd/systemd.service.5.en.html#COMMAND_LINES
    """
    return "".join(
        map(
            lambda char: r"\s" if char == " " else "\\\\" if char == "\\" else char,
            path,
        )
    )


def add_hook(jail_path, systemd_run_additional_args, hook_command, hook_type):
    if not hook_command:
        return

    # Run the command directly if it doesn't start with a shebang
    if not hook_command.startswith("#!"):
        systemd_run_additional_args += [f"--property={hook_type}={hook_command}"]
        return

    # Otherwise write a script file and call that
    hook_file = os.path.abspath(os.path.join(jail_path, f".{hook_type}"))

    # Only write if contents are different
    if not os.path.exists(hook_file) or Path(hook_file).read_text() != hook_command:
        print(hook_command, file=open(hook_file, "w"))

    stat_chmod(hook_file, 0o700)
    systemd_run_additional_args += [
        f"--property={hook_type}={systemd_escape_path(hook_file)}"
    ]


def start_jail(jail_name):
    """
    Start jail with given name.
    """
    skip_start_message = (
        f"Skipped starting jail {jail_name}. It appears to be running already..."
    )

    if jail_is_running(jail_name):
        eprint(skip_start_message)
        return 0

    jail_path = get_jail_path(jail_name)
    jail_config_path = get_jail_config_path(jail_name)
    jail_rootfs_path = get_jail_rootfs_path(jail_name)

    config = parse_config_file(jail_config_path)

    if not config:
        eprint("Aborting...")
        return 1

    seccomp = config.my_getboolean("seccomp")

    systemd_run_additional_args = [
        f"--unit={SHORTNAME}-{jail_name}",
        f"--working-directory={jail_path}",
        f"--description=My nspawn jail {jail_name} [created with jailmaker]",
    ]

    systemd_nspawn_additional_args = [
        f"--machine={jail_name}",
        f"--directory={JAIL_ROOTFS_NAME}",
    ]

    # The systemd-nspawn manual explicitly mentions:
    # Device nodes may not be created
    # https://www.freedesktop.org/software/systemd/man/systemd-nspawn.html
    # This means docker images containing device nodes can't be pulled
    # https://github.com/moby/moby/issues/35245
    #
    # The solution is to use DevicePolicy=auto
    # https://github.com/kinvolk/kube-spawn/pull/328
    #
    # DevicePolicy=auto is the default for systemd-run and allows access to all devices
    # as long as we don't add any --property=DeviceAllow= flags
    # https://manpages.debian.org/bookworm/systemd/systemd.resource-control.5.en.html
    #
    # We can now successfully run:
    # mknod /dev/port c 1 4
    # Or pull docker images containing device nodes:
    # docker pull oraclelinux@sha256:d49469769e4701925d5145c2676d5a10c38c213802cf13270ec3a12c9c84d643

    # Add hooks to execute commands on the host before/after starting and after stopping a jail
    add_hook(
        jail_path,
        systemd_run_additional_args,
        config.my_get("pre_start_hook"),
        "ExecStartPre",
    )

    add_hook(
        jail_path,
        systemd_run_additional_args,
        config.my_get("post_start_hook"),
        "ExecStartPost",
    )

    add_hook(
        jail_path,
        systemd_run_additional_args,
        config.my_get("post_stop_hook"),
        "ExecStopPost",
    )

    gpu_passthrough_intel = config.my_getboolean("gpu_passthrough_intel")
    gpu_passthrough_nvidia = config.my_getboolean("gpu_passthrough_nvidia")

    passthrough_intel(gpu_passthrough_intel, systemd_nspawn_additional_args)
    passthrough_nvidia(
        gpu_passthrough_nvidia, systemd_nspawn_additional_args, jail_name
    )

    if seccomp is False:
        # Disabling seccomp filtering by passing --setenv=SYSTEMD_SECCOMP=0 to systemd-run will improve performance
        # at the expense of security: it allows syscalls which otherwise would be blocked or would have to be explicitly allowed by passing
        # --system-call-filter to systemd-nspawn
        # https://github.com/systemd/systemd/issues/18370
        #
        # However, and additional layer of seccomp filtering may be undesirable
        # For example when using docker to run containers inside the jail created with systemd-nspawn
        # Even though seccomp filtering is disabled for the systemd-nspawn jail itself, docker can still use seccomp filtering
        # to restrict the actions available within its containers
        #
        # Proof that seccomp can be used inside a jail started with --setenv=SYSTEMD_SECCOMP=0:
        # Run a command in a docker container which is blocked by the default docker seccomp profile:
        # 	docker run --rm -it debian:jessie unshare --map-root-user --user sh -c whoami
        # 	unshare: unshare failed: Operation not permitted
        # Now run unconfined to show command runs successfully:
        # 	docker run --rm -it --security-opt seccomp=unconfined debian:jessie unshare --map-root-user --user sh -c whoami
        # 	root

        systemd_run_additional_args += [
            "--setenv=SYSTEMD_SECCOMP=0",
        ]

    initial_setup = False

    # If there's no machine-id, then this the first time the jail is started
    if not os.path.exists(os.path.join(jail_rootfs_path, "etc/machine-id")) and (
        initial_setup := config.my_get("initial_setup")
    ):
        # initial_setup has been assigned due to := expression above
        # Ensure the jail init system is ready before we start the initial_setup
        systemd_nspawn_additional_args += [
            "--notify-ready=yes",
        ]

    cmd = [
        "systemd-run",
        *shlex.split(config.my_get("systemd_run_default_args")),
        *systemd_run_additional_args,
        "--",
        "systemd-nspawn",
        *shlex.split(config.my_get("systemd_nspawn_default_args")),
        *systemd_nspawn_additional_args,
        *shlex.split(config.my_get("systemd_nspawn_user_args")),
    ]

    print(
        dedent(
            f"""
        Starting jail {jail_name} with the following command:

        {shlex.join(cmd)}
    """
        )
    )

    returncode = subprocess.run(cmd).returncode
    if returncode != 0:
        eprint(
            dedent(
                f"""
            Failed to start jail {jail_name}...
            In case of a config error, you may fix it with:
            {COMMAND_NAME} edit {jail_name}
        """
            )
        )

        return returncode

    # Handle initial setup after jail is up and running (for the first time)
    if initial_setup:
        if not initial_setup.startswith("#!"):
            initial_setup = "#!/bin/sh\n" + initial_setup

        with tempfile.NamedTemporaryFile(
            mode="w+t",
            prefix="jlmkr-initial-setup.",
            dir=jail_rootfs_path,
            delete=False,
        ) as initial_setup_file:
            # Write a script file to call during initial setup
            initial_setup_file.write(initial_setup)

        initial_setup_file_name = os.path.basename(initial_setup_file.name)
        initial_setup_file_host_path = os.path.abspath(initial_setup_file.name)
        stat_chmod(initial_setup_file_host_path, 0o700)

        print(f"About to run the initial setup script: {initial_setup_file_name}.")
        print("Waiting for networking in the jail to be ready.")
        print(
            "Please wait (this may take 90s in case of bridge networking with STP is enabled)..."
        )
        returncode = exec_jail(
            jail_name,
            [
                "--",
                "systemd-run",
                f"--unit={initial_setup_file_name}",
                "--quiet",
                "--pipe",
                "--wait",
                "--service-type=exec",
                "--property=After=network-online.target",
                "--property=Wants=network-online.target",
                "/" + initial_setup_file_name,
            ],
        )

        if returncode != 0:
            eprint("Tried to run the following commands inside the jail:")
            eprint(initial_setup)
            eprint()
            eprint(f"{RED}{BOLD}Failed to run initial setup...")
            eprint(
                f"You may want to manually run /{initial_setup_file_name} inside the jail for debugging purposes."
            )
            eprint(f"Or stop and remove the jail and try again.{NORMAL}")
            return returncode
        else:
            # Cleanup the initial_setup_file_host_path
            Path(initial_setup_file_host_path).unlink(missing_ok=True)
            print(f"Done with initial setup of jail {jail_name}!")

    return returncode


def restart_jail(jail_name):
    """
    Restart jail with given name.
    """

    returncode = stop_jail(jail_name)
    if returncode != 0:
        eprint("Abort restart.")
        return returncode

    return start_jail(jail_name)


def cleanup(jail_path):
    """
    Cleanup jail.
    """

    if get_zfs_dataset(jail_path):
        eprint(f"Cleaning up: {jail_path}.")
        remove_zfs_dataset(jail_path)

    elif os.path.isdir(jail_path):
        # Workaround for https://github.com/python/cpython/issues/73885
        # Should be fixed in Python 3.13 https://stackoverflow.com/a/70549000
        def _onerror(func, path, exc_info):
            exc_type, exc_value, exc_traceback = exc_info
            if issubclass(exc_type, PermissionError):
                # Update the file permissions with the immutable and append-only bit cleared
                subprocess.run(["chattr", "-i", "-a", path])
                # Reattempt the removal
                func(path)
            elif not issubclass(exc_type, FileNotFoundError):
                raise exc_value

        eprint(f"Cleaning up: {jail_path}.")
        shutil.rmtree(jail_path, onerror=_onerror)


def input_with_default(prompt, default):
    """
    Ask user for input with a default value already provided.
    """
    readline.set_startup_hook(lambda: readline.insert_text(default))
    try:
        return input(prompt)
    finally:
        readline.set_startup_hook()


def validate_sha256(file_path, digest):
    """
    Validates if a file matches a sha256 digest.
    """
    try:
        with open(file_path, "rb") as f:
            file_hash = hashlib.sha256(f.read()).hexdigest()
            return file_hash == digest
    except FileNotFoundError:
        return False


def run_lxc_download_script(
    jail_name=None, jail_path=None, jail_rootfs_path=None, distro=None, release=None
):
    arch = "amd64"
    lxc_dir = ".lxc"
    lxc_cache = os.path.join(lxc_dir, "cache")
    lxc_download_script = os.path.join(lxc_dir, "lxc-download.sh")

    # Create the lxc dirs if nonexistent
    os.makedirs(lxc_dir, exist_ok=True)
    stat_chmod(lxc_dir, 0o700)
    os.makedirs(lxc_cache, exist_ok=True)
    stat_chmod(lxc_cache, 0o700)

    try:
        if os.stat(lxc_download_script).st_uid != 0:
            os.remove(lxc_download_script)
    except FileNotFoundError:
        pass

    # Fetch the lxc download script if not present locally (or hash doesn't match)
    if not validate_sha256(lxc_download_script, DOWNLOAD_SCRIPT_DIGEST):
        urllib.request.urlretrieve(
            "https://raw.githubusercontent.com/Jip-Hop/lxc/97f93be72ebf380f3966259410b70b1c966b0ff0/templates/lxc-download.in",
            lxc_download_script,
        )

        if not validate_sha256(lxc_download_script, DOWNLOAD_SCRIPT_DIGEST):
            eprint("Abort! Downloaded script has unexpected contents.")
            return 1

    stat_chmod(lxc_download_script, 0o700)

    if None not in [jail_name, jail_path, jail_rootfs_path, distro, release]:
        cmd = [
            lxc_download_script,
            f"--name={jail_name}",
            f"--path={jail_path}",
            f"--rootfs={jail_rootfs_path}",
            f"--arch={arch}",
            f"--dist={distro}",
            f"--release={release}",
        ]

        if rc := subprocess.run(cmd, env={"LXC_CACHE_PATH": lxc_cache}).returncode != 0:
            eprint("Aborting...")
            return rc

    else:
        # List images
        cmd = [lxc_download_script, "--list", f"--arch={arch}"]

        p1 = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, env={"LXC_CACHE_PATH": lxc_cache}
        )

        for line in iter(p1.stdout.readline, b""):
            line = line.decode().strip()
            # Filter out the known incompatible distros
            if not re.match(
                r"^(alpine|amazonlinux|busybox|devuan|funtoo|openwrt|plamo|voidlinux)\s",
                line,
            ):
                print(line)

        rc = p1.wait()
        # Currently --list will always return a non-zero exit code, even when listing the images was successful
        # https://github.com/lxc/lxc/pull/4462
        # Therefore we must currently return 0, to prevent aborting the interactive create process

        # return rc

    return 0


def stat_chmod(file_path, mode):
    """
    Change mode if file doesn't already have this mode.
    """
    if mode != stat.S_IMODE(os.stat(file_path).st_mode):
        os.chmod(file_path, mode)


def agree(question, default=None):
    """
    Ask user a yes/no question.
    """
    hint = "[Y/n]" if default == "y" else ("[y/N]" if default == "n" else "[y/n]")

    while True:
        user_input = input(f"{question} {hint} ") or default

        if user_input.lower() in ["y", "n"]:
            return user_input.lower() == "y"

        eprint("Invalid input. Please type 'y' for yes or 'n' for no and press enter.")


def get_mount_point(path):
    """
    Return the mount point on which the given path resides.
    """
    path = os.path.abspath(path)
    while not os.path.ismount(path):
        path = os.path.dirname(path)
    return path


def get_relative_path_in_jailmaker_dir(absolute_path):
    return PurePath(absolute_path).relative_to(SCRIPT_DIR_PATH)


def get_zfs_dataset(path):
    """
    Get ZFS dataset path.
    """

    def clean_field(field):
        # Put back spaces which were encoded
        # https://github.com/openzfs/zfs/issues/11182
        return field.replace("\\040", " ")

    path = os.path.realpath(path)
    with open("/proc/mounts", "r") as f:
        for line in f:
            fields = line.split()
            if "zfs" == fields[2] and path == clean_field(fields[1]):
                return clean_field(fields[0])


def get_zfs_base_path():
    """
    Get ZFS dataset path for jailmaker directory.
    """
    zfs_base_path = get_zfs_dataset(SCRIPT_DIR_PATH)
    if not zfs_base_path:
        fail("Failed to get dataset path for jailmaker directory.")

    return zfs_base_path


def create_zfs_dataset(absolute_path):
    """
    Create a ZFS Dataset inside the jailmaker directory at the provided absolute path.
    E.g. "/mnt/mypool/jailmaker/jails" or "/mnt/mypool/jailmaker/jails/newjail").
    """
    relative_path = get_relative_path_in_jailmaker_dir(absolute_path)
    dataset_to_create = os.path.join(get_zfs_base_path(), relative_path)
    eprint(f"Creating ZFS Dataset {dataset_to_create}")
    subprocess.run(["zfs", "create", dataset_to_create], check=True)


def remove_zfs_dataset(absolute_path):
    """
    Remove a ZFS Dataset inside the jailmaker directory at the provided absolute path.
    E.g. "/mnt/mypool/jailmaker/jails/oldjail".
    """
    relative_path = get_relative_path_in_jailmaker_dir(absolute_path)
    dataset_to_remove = os.path.join((get_zfs_base_path()), relative_path)
    eprint(f"Removing ZFS Dataset {dataset_to_remove}")
    subprocess.run(["zfs", "destroy", "-r", dataset_to_remove], check=True)


def check_jail_name_valid(jail_name, warn=True):
    """
    Return True if jail name matches the required format.
    """
    if (
        re.match(r"^[.a-zA-Z0-9-]{1,64}$", jail_name)
        and not jail_name.startswith(".")
        and ".." not in jail_name
    ):
        return True

    if warn:
        eprint(
            dedent(
                f"""
            {YELLOW}{BOLD}WARNING: INVALID NAME{NORMAL}

            A valid name consists of:
            - allowed characters (alphanumeric, dash, dot)
            - no leading or trailing dots
            - no sequences of multiple dots
            - max 64 characters"""
            )
        )
    return False


def check_jail_name_available(jail_name, warn=True):
    """
    Return True if jail name is not yet taken.
    """
    if not os.path.exists(get_jail_path(jail_name)):
        return True

    if warn:
        print()
        eprint("A jail with this name already exists.")
    return False


def ask_jail_name(jail_name=""):
    while True:
        print()
        jail_name = input_with_default("Enter jail name: ", jail_name).strip()
        if check_jail_name_valid(jail_name):
            if check_jail_name_available(jail_name):
                return jail_name


def agree_with_default(config, key, question):
    default_answer = "y" if config.my_getboolean(key) else "n"
    config.my_set(key, agree(question, default_answer))


def get_text_editor():
    def get_from_environ(key):
        if editor := os.environ.get(key):
            return shutil.which(editor)

    return (
        get_from_environ("VISUAL")
        or get_from_environ("EDITOR")
        or shutil.which("editor")
        or shutil.which("/usr/bin/editor")
        or "nano"
    )


def interactive_config():
    config = KeyValueParser()
    config.read_string(DEFAULT_CONFIG)

    recommended_distro = config.my_get("distro")
    recommended_release = config.my_get("release")

    #################
    # Config handling
    #################
    jail_name = ""

    print()
    if agree("Do you wish to create a jail from a config template?", "n"):
        print(
            dedent(
                """
            A text editor will open so you can provide the config template.

              1. Please copy your config
              2. Paste it into the text editor
              3. Save and close the text editor
        """
            )
        )
        input("Press Enter to open the text editor.")

        with tempfile.NamedTemporaryFile(mode="w+t") as f:
            subprocess.call([get_text_editor(), f.name])
            f.seek(0)
            # Start over with a new KeyValueParser to parse user config
            config = KeyValueParser()
            config.read_file(f)

        # Ask for jail name
        jail_name = ask_jail_name(jail_name)
    else:
        print()
        if not agree(
            f"Install the recommended image ({recommended_distro} {recommended_release})?",
            "y",
        ):
            print(
                dedent(
                    f"""
                {YELLOW}{BOLD}WARNING: ADVANCED USAGE{NORMAL}

                You may now choose from a list which distro to install.
                But not all of them may work with {COMMAND_NAME} since these images are made for LXC.
                Distros based on systemd probably work (e.g. Ubuntu, Arch Linux and Rocky Linux).
            """
                )
            )
            input("Press Enter to continue...")
            print()

            if run_lxc_download_script() != 0:
                fail("Failed to list images. Aborting...")

            print(
                dedent(
                    """
                Choose from the DIST column.
            """
                )
            )

            config.my_set("distro", input("Distro: "))

            print(
                dedent(
                    """
                Choose from the RELEASE column (or ARCH if RELEASE is empty).
            """
                )
            )

            config.my_set("release", input("Release: "))

        jail_name = ask_jail_name(jail_name)

        print()
        agree_with_default(
            config, "gpu_passthrough_intel", "Passthrough the intel GPU (if present)?"
        )
        print()
        agree_with_default(
            config, "gpu_passthrough_nvidia", "Passthrough the nvidia GPU (if present)?"
        )

        print(
            dedent(
                f"""
            {YELLOW}{BOLD}WARNING: CHECK SYNTAX{NORMAL}

            You may pass additional flags to systemd-nspawn.
            With incorrect flags the jail may not start.
            It is possible to correct/add/remove flags post-install.
        """
            )
        )

        if agree("Show the man page for systemd-nspawn?", "n"):
            subprocess.run(["man", "systemd-nspawn"])
        else:
            try:
                base_os_version = platform.freedesktop_os_release().get(
                    "VERSION_CODENAME", recommended_release
                )
            except AttributeError:
                base_os_version = recommended_release
            print(
                dedent(
                    f"""
                You may read the systemd-nspawn manual online:
                https://manpages.debian.org/{base_os_version}/systemd-container/systemd-nspawn.1.en.html"""
                )
            )

        # Backslashes and colons need to be escaped in bind mount options:
        # e.g. to bind mount a file called:
        # weird chars :?\"
        # the corresponding command would be:
        # --bind-ro='/mnt/data/weird chars \:?\\"'

        print(
            dedent(
                """
            Would you like to add additional systemd-nspawn flags?
            For example to mount directories inside the jail you may:
            Mount the TrueNAS location /mnt/pool/dataset to the /home directory of the jail with:
            --bind='/mnt/pool/dataset:/home'
            Or the same, but readonly, with:
            --bind-ro='/mnt/pool/dataset:/home'
            Or create macvlan interface with:
            --network-macvlan=eno1 --resolv-conf=bind-host
        """
            )
        )

        config.my_set(
            "systemd_nspawn_user_args",
            "\n    ".join(shlex.split(input("Additional flags: ") or "")),
        )

        print(
            dedent(
                f"""
            The `{COMMAND_NAME} startup` command can automatically start a selection of jails.
            This comes in handy when you want to automatically start multiple jails after booting TrueNAS SCALE (e.g. from a Post Init Script).
        """
            )
        )

        config.my_set(
            "startup",
            agree(
                f"Do you want to start this jail when running: {COMMAND_NAME} startup?",
                "n",
            ),
        )

    print()
    start_now = agree("Do you want to start this jail now (when create is done)?", "y")

    print()

    return jail_name, config, start_now


def create_jail(**kwargs):
    print(DISCLAIMER)

    if os.path.basename(SCRIPT_DIR_PATH) != "jailmaker":
        eprint(
            dedent(
                f"""
            {COMMAND_NAME} needs to create files.
            Currently it can not decide if it is safe to create files in:
            {SCRIPT_DIR_PATH}
            Please create a dedicated dataset called "jailmaker", store {SCRIPT_NAME} there and try again."""
            )
        )
        return 1

    if not PurePath(get_mount_point(SCRIPT_DIR_PATH)).is_relative_to("/mnt"):
        print(
            dedent(
                f"""
            {YELLOW}{BOLD}WARNING: BEWARE OF DATA LOSS{NORMAL}

            {SCRIPT_NAME} should be on a dataset mounted under /mnt (it currently is not).
            Storing it on the boot-pool means losing all jails when updating TrueNAS.
            Jails will be stored under:
            {SCRIPT_DIR_PATH}
        """
            )
        )

    jail_name = kwargs.pop("jail_name", None)
    start_now = False

    # Non-interactive create
    if jail_name:
        if not check_jail_name_valid(jail_name):
            return 1

        if not check_jail_name_available(jail_name):
            return 1

        start_now = kwargs.pop("start", start_now)
        jail_config_path = kwargs.pop("config")

        config = KeyValueParser()

        if jail_config_path:
            # TODO: fallback to default values for e.g. distro and release if they are not in the config file
            if jail_config_path == "-":
                print(
                    f"Creating jail {jail_name} from config template passed via stdin."
                )
                config.read_string(sys.stdin.read())
            else:
                print(
                    f"Creating jail {jail_name} from config template {jail_config_path}."
                )
                if jail_config_path not in config.read(jail_config_path):
                    eprint(f"Failed to read config template {jail_config_path}.")
                    return 1
        else:
            print(f"Creating jail {jail_name} with default config.")
            config.read_string(DEFAULT_CONFIG)

        user_overridden = False

        for option in [
            "distro",
            "gpu_passthrough_intel",
            "gpu_passthrough_nvidia",
            "release",
            "seccomp",
            "startup",
            "systemd_nspawn_user_args",
        ]:
            value = kwargs.pop(option)
            if (
                value is not None
                # String, non-empty list of args or int
                and (isinstance(value, int) or len(value))
                and value is not config.my_get(option, None)
            ):
                # TODO: this will wipe all systemd_nspawn_user_args from the template...
                # Should there be an option to append them instead?
                print(f"Overriding {option} config value with {value}.")
                config.my_set(option, value)
                user_overridden = True

        if not user_overridden:
            print(
                dedent(
                    f"""
                    Hint: run `{COMMAND_NAME} create` without any arguments for interactive config.
                    Or use CLI args to override the default options.
                    For more info, run: `{COMMAND_NAME} create --help`
                  """
                )
            )
    else:
        jail_name, config, start_now = interactive_config()

    jail_path = get_jail_path(jail_name)

    distro = config.my_get("distro")
    release = config.my_get("release")

    # Cleanup in except, but only once the jail_path is final
    # Otherwise we may cleanup the wrong directory
    try:
        # Create the dir or dataset where to store the jails
        if not os.path.exists(JAILS_DIR_PATH):
            if get_zfs_dataset(SCRIPT_DIR_PATH):
                # Creating "jails" dataset if "jailmaker" is a ZFS Dataset
                create_zfs_dataset(JAILS_DIR_PATH)
            else:
                os.makedirs(JAILS_DIR_PATH, exist_ok=True)
            stat_chmod(JAILS_DIR_PATH, 0o700)

        # Creating a dataset for the jail if the jails dir is a dataset
        if get_zfs_dataset(JAILS_DIR_PATH):
            create_zfs_dataset(jail_path)

        jail_config_path = get_jail_config_path(jail_name)
        jail_rootfs_path = get_jail_rootfs_path(jail_name)

        # Create directory for rootfs
        os.makedirs(jail_rootfs_path, exist_ok=True)
        # LXC download script needs to write to this file during install
        # but we don't need it so we will remove it later
        open(jail_config_path, "a").close()

        if (
            returncode := run_lxc_download_script(
                jail_name, jail_path, jail_rootfs_path, distro, release
            )
            != 0
        ):
            cleanup(jail_path)
            return returncode

        # Assuming the name of your jail is "myjail"
        # and "machinectl shell myjail" doesn't work
        # Try:
        #
        # Stop the jail with:
        # machinectl stop myjail
        # And start a shell inside the jail without the --boot option:
        # systemd-nspawn -q -D jails/myjail/rootfs /bin/sh
        # Then set a root password with:
        # In case of amazonlinux you may need to run:
        # yum update -y && yum install -y passwd
        # passwd
        # exit
        # Then you may login from the host via:
        # machinectl login myjail
        #
        # You could also enable SSH inside the jail to login
        #
        # Or if that doesn't work (e.g. for alpine) get a shell via:
        # nsenter -t $(machinectl show myjail -p Leader --value) -a /bin/sh -l
        # But alpine jails made with jailmaker have other issues
        # They don't shutdown cleanly via systemctl and machinectl...

        with Chroot(jail_rootfs_path):
            # Use chroot to correctly resolve absolute /sbin/init symlink
            init_system_name = os.path.basename(os.path.realpath("/sbin/init"))

        if (
            init_system_name != "systemd"
            and parse_os_release(jail_rootfs_path).get("ID") != "nixos"
        ):
            print(
                dedent(
                    f"""
                {YELLOW}{BOLD}WARNING: DISTRO NOT SUPPORTED{NORMAL}

                Chosen distro appears not to use systemd...

                You probably will not get a shell with:
                machinectl shell {jail_name}

                You may get a shell with this command:
                nsenter -t $(machinectl show {jail_name} -p Leader --value) -a /bin/sh -l

                Read about the downsides of nsenter:
                https://github.com/systemd/systemd/issues/12785#issuecomment-503019081

                {BOLD}Using this distro with {COMMAND_NAME} is NOT recommended.{NORMAL}
            """
                )
            )

            print("Autostart has been disabled.")
            print("You need to start this jail manually.")
            config.my_set("startup", 0)
            start_now = False

        # Remove config which systemd handles for us
        with contextlib.suppress(FileNotFoundError):
            os.remove(os.path.join(jail_rootfs_path, "etc/machine-id"))
        with contextlib.suppress(FileNotFoundError):
            os.remove(os.path.join(jail_rootfs_path, "etc/resolv.conf"))

        # https://github.com/systemd/systemd/issues/852
        print(
            "\n".join([f"pts/{i}" for i in range(0, 11)]),
            file=open(os.path.join(jail_rootfs_path, "etc/securetty"), "w"),
        )

        network_dir_path = os.path.join(jail_rootfs_path, "etc/systemd/network")

        # Modify default network settings, if network_dir_path exists
        if os.path.isdir(network_dir_path):
            default_host0_network_file = os.path.join(
                jail_rootfs_path, "lib/systemd/network/80-container-host0.network"
            )

            # Check if default host0 network file exists
            if os.path.isfile(default_host0_network_file):
                override_network_file = os.path.join(
                    network_dir_path, "80-container-host0.network"
                )

                # Override the default 80-container-host0.network file (by using the same name)
                # This config applies when using the --network-bridge option of systemd-nspawn
                # Disable LinkLocalAddressing on IPv4, or else the container won't get IP address via DHCP
                # But keep it enabled on IPv6, as SLAAC and DHCPv6 both require a local-link address to function
                print(
                    Path(default_host0_network_file)
                    .read_text()
                    .replace("LinkLocalAddressing=yes", "LinkLocalAddressing=ipv6"),
                    file=open(override_network_file, "w"),
                )

            # Setup DHCP for macvlan network interfaces
            # This config applies when using the --network-macvlan option of systemd-nspawn
            # https://www.debian.org/doc/manuals/debian-reference/ch05.en.html#_the_modern_network_configuration_without_gui
            print(
                cleandoc(
                    """
                [Match]
                Virtualization=container
                Name=mv-*

                [Network]
                DHCP=yes
                LinkLocalAddressing=ipv6

                [DHCPv4]
                UseDNS=true
                UseTimezone=true
            """
                ),
                file=open(os.path.join(network_dir_path, "mv-dhcp.network"), "w"),
            )

            # Setup DHCP for veth-extra network interfaces
            # This config applies when using the --network-veth-extra option of systemd-nspawn
            # https://www.debian.org/doc/manuals/debian-reference/ch05.en.html#_the_modern_network_configuration_without_gui
            print(
                cleandoc(
                    """
                [Match]
                Virtualization=container
                Name=vee-*

                [Network]
                DHCP=yes
                LinkLocalAddressing=ipv6

                [DHCPv4]
                UseDNS=true
                UseTimezone=true
            """
                ),
                file=open(os.path.join(network_dir_path, "vee-dhcp.network"), "w"),
            )

            # Override preset which caused systemd-networkd to be disabled (e.g. fedora 39)
            # https://www.freedesktop.org/software/systemd/man/latest/systemd.preset.html
            # https://github.com/lxc/lxc-ci/blob/f632823ecd9b258ed42df40449ec54ed7ef8e77d/images/fedora.yaml#L312C5-L312C38

            preset_path = os.path.join(jail_rootfs_path, "etc/systemd/system-preset")
            os.makedirs(preset_path, exist_ok=True)
            print(
                "enable systemd-networkd.service",
                file=open(os.path.join(preset_path, "00-jailmaker.preset"), "w"),
            )

        with open(jail_config_path, "w") as fp:
            config.write(fp)

        os.chmod(jail_config_path, 0o600)

    # Cleanup on any exception and rethrow
    except BaseException as error:
        cleanup(jail_path)
        raise error

    if start_now:
        return start_jail(jail_name)

    return 0


def jail_is_running(jail_name):
    return (
        subprocess.run(
            ["machinectl", "show", jail_name],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ).returncode
        == 0
    )


def edit_jail(jail_name):
    """
    Edit jail with given name.
    """

    if not check_jail_name_valid(jail_name):
        return 1

    if check_jail_name_available(jail_name, False):
        eprint(f"A jail with name {jail_name} does not exist.")
        return 1

    jail_config_path = get_jail_config_path(jail_name)

    returncode = subprocess.run([get_text_editor(), jail_config_path]).returncode

    if returncode != 0:
        eprint(f"An error occurred while editing {jail_config_path}.")
        return returncode

    if jail_is_running(jail_name):
        print("\nRestart the jail for edits to apply (if you made any).")

    return 0


def stop_jail(jail_name):
    """
    Stop jail with given name and wait until stopped.
    """

    if not jail_is_running(jail_name):
        return 0

    returncode = subprocess.run(["machinectl", "poweroff", jail_name]).returncode
    if returncode != 0:
        eprint("Error while stopping jail.")
        return returncode

    print(f"Wait for {jail_name} to stop", end="", flush=True)

    while jail_is_running(jail_name):
        time.sleep(1)
        print(".", end="", flush=True)

    return 0


def remove_jail(jail_name):
    """
    Remove jail with given name.
    """

    if not check_jail_name_valid(jail_name):
        return 1

    if check_jail_name_available(jail_name, False):
        eprint(f"A jail with name {jail_name} does not exist.")
        return 1

    # TODO: print which dataset is about to be removed before the user confirmation
    # TODO: print that all zfs snapshots will be removed if jail has it's own zfs dataset
    check = input(f'\nCAUTION: Type "{jail_name}" to confirm jail deletion!\n\n')

    if check == jail_name:
        print()
        jail_path = get_jail_path(jail_name)
        returncode = stop_jail(jail_name)
        if returncode != 0:
            return returncode

        print()
        cleanup(jail_path)
        return 0
    else:
        eprint("Wrong name, nothing happened.")
        return 1


def print_table(header, list_of_objects, empty_value_indicator):
    # Find max width for each column
    widths = defaultdict(int)
    for obj in list_of_objects:
        for hdr in header:
            value = obj.get(hdr)
            if value is None:
                obj[hdr] = value = empty_value_indicator
            widths[hdr] = max(widths[hdr], len(str(value)), len(str(hdr)))

    # Print header
    print(
        UNDERLINE + " ".join(hdr.upper().ljust(widths[hdr]) for hdr in header) + NORMAL
    )

    # Print rows
    for obj in list_of_objects:
        print(" ".join(str(obj.get(hdr)).ljust(widths[hdr]) for hdr in header))


def run_command_and_parse_json(command):
    result = subprocess.run(command, capture_output=True, text=True)
    output = result.stdout.strip()

    try:
        parsed_output = json.loads(output)
        return parsed_output
    except json.JSONDecodeError as e:
        eprint(f"Error parsing JSON: {e}")
        return None


def get_all_jail_names():
    try:
        jail_names = os.listdir(JAILS_DIR_PATH)
    except FileNotFoundError:
        jail_names = []

    return jail_names


def parse_os_release(new_root):
    result = {}
    with Chroot(new_root):
        # Use chroot to correctly resolve os-release symlink (for nixos)
        for candidate in ["/etc/os-release", "/usr/lib/os-release"]:
            try:
                with open(candidate, encoding="utf-8") as f:
                    # TODO: can I create a solution which not depends on the internal _parse_os_release method?
                    result = platform._parse_os_release(f)
                    break
            except OSError:
                # Silently ignore failing to read os release info
                pass

    return result


def list_jails():
    """
    List all available and running jails.
    """

    jails = {}
    empty_value_indicator = "-"

    jail_names = get_all_jail_names()

    if not jail_names:
        print("No jails.")
        return 0

    # Get running jails from machinectl
    running_machines = run_command_and_parse_json(["machinectl", "list", "-o", "json"])
    # Index running_machines by machine name
    # We're only interested in systemd-nspawn machines
    running_machines = {
        item["machine"]: item
        for item in running_machines
        if item["service"] == "systemd-nspawn"
    }

    for jail_name in jail_names:
        jail_rootfs_path = get_jail_rootfs_path(jail_name)
        jails[jail_name] = {"name": jail_name, "running": False}
        jail = jails[jail_name]

        config = parse_config_file(get_jail_config_path(jail_name))
        if config:
            jail["startup"] = config.my_getboolean("startup")
            jail["gpu_intel"] = config.my_getboolean("gpu_passthrough_intel")
            jail["gpu_nvidia"] = config.my_getboolean("gpu_passthrough_nvidia")

        if jail_name in running_machines:
            machine = running_machines[jail_name]
            # Augment the jails dict with output from machinectl
            jail["running"] = True
            jail["os"] = machine["os"] or None
            jail["version"] = machine["version"] or None

            addresses = machine.get("addresses")
            if not addresses:
                jail["addresses"] = empty_value_indicator
            else:
                addresses = addresses.split("\n")
                jail["addresses"] = addresses[0]
                if len(addresses) > 1:
                    jail["addresses"] += "…"
        else:
            # Parse os-release info ourselves
            jail_platform = parse_os_release(jail_rootfs_path)
            jail["os"] = jail_platform.get("ID")
            jail["version"] = jail_platform.get("VERSION_ID") or jail_platform.get(
                "VERSION_CODENAME"
            )

    print_table(
        [
            "name",
            "running",
            "startup",
            "gpu_intel",
            "gpu_nvidia",
            "os",
            "version",
            "addresses",
        ],
        sorted(jails.values(), key=lambda x: x["name"]),
        empty_value_indicator,
    )

    return 0


def startup_jails():
    start_failure = False
    for jail_name in get_all_jail_names():
        config = parse_config_file(get_jail_config_path(jail_name))
        if config and config.my_getboolean("startup"):
            if start_jail(jail_name) != 0:
                start_failure = True

    if start_failure:
        return 1

    return 0


def split_at_string(lst, string):
    try:
        index = lst.index(string)
        return lst[:index], lst[index + 1 :]
    except ValueError:
        return lst, []


def add_parser(subparser, **kwargs):
    if kwargs.get("add_help") is False:
        # Don't add help if explicitly disabled
        add_help = False
    else:
        # Never add help with the built in add_help
        kwargs["add_help"] = False
        add_help = True

    kwargs["epilog"] = DISCLAIMER
    kwargs["exit_on_error"] = False
    func = kwargs.pop("func")
    parser = subparser.add_parser(**kwargs)
    parser.set_defaults(func=func)

    if add_help:
        parser.add_argument(
            "-h", "--help", help="show this help message and exit", action="store_true"
        )

    # Setting the add_help after the parser has been created with add_parser has no effect,
    # but it allows us to look up if this parser has a help message available
    parser.add_help = add_help

    return parser


def main():
    if os.stat(SCRIPT_PATH).st_uid != 0:
        fail(
            f"This script should be owned by the root user... Fix it manually with: `chown root {SCRIPT_PATH}`."
        )

    parser = argparse.ArgumentParser(
        description=__doc__, epilog=DISCLAIMER, allow_abbrev=False
    )

    parser.add_argument("--version", action="version", version=__version__)

    subparsers = parser.add_subparsers(
        title="commands", dest="command", metavar="", parser_class=CustomSubParser
    )

    split_commands = ["create", "exec", "log", "status"]
    commands = {}

    for d in [
        dict(
            name="create",  #
            help="create a new jail",
            func=create_jail,
        ),
        dict(
            name="edit",
            help=f"edit jail config with {get_text_editor()} text editor",
            func=edit_jail,
        ),
        dict(
            name="exec",  #
            help="execute a command in the jail",
            func=exec_jail,
        ),
        dict(
            name="images",
            help="list available images to create jails from",
            func=run_lxc_download_script,
        ),
        dict(
            name="list",  #
            help="list jails",
            func=list_jails,
        ),
        dict(
            name="log",  #
            help="show jail log",
            func=log_jail,
        ),
        dict(
            name="remove",  #
            help="remove previously created jail",
            func=remove_jail,
        ),
        dict(
            name="restart",  #
            help="restart a running jail",
            func=restart_jail,
        ),
        dict(
            name="shell",
            help="open shell in running jail (alias for machinectl shell)",
            func=shell_jail,
            add_help=False,
        ),
        dict(
            name="start",  #
            help="start previously created jail",
            func=start_jail,
        ),
        dict(
            name="startup",
            help="startup selected jails",
            func=startup_jails,
        ),
        dict(
            name="status",  #
            help="show jail status",
            func=status_jail,
        ),
        dict(
            name="stop",  #
            help="stop a running jail",
            func=stop_jail,
        ),
    ]:
        commands[d["name"]] = add_parser(subparsers, **d)

    for cmd in ["edit", "exec", "log", "remove", "restart", "start", "status", "stop"]:
        commands[cmd].add_argument("jail_name", help="name of the jail")

    commands["exec"].add_argument(
        "cmd",
        nargs="*",
        help="command to execute",
    )

    commands["shell"].add_argument(
        "args",
        nargs="*",
        help="args to pass to machinectl shell",
    )

    commands["log"].add_argument(
        "args",
        nargs="*",
        help="args to pass to journalctl",
    )

    commands["status"].add_argument(
        "args",
        nargs="*",
        help="args to pass to systemctl",
    )

    commands["create"].add_argument(
        "jail_name",  #
        nargs="?",
        help="name of the jail",
    )
    commands["create"].add_argument("--distro")
    commands["create"].add_argument("--release")
    commands["create"].add_argument(
        "--start",  #
        help="start jail after create",
        action="store_true",
    )
    commands["create"].add_argument(
        "--startup",
        type=int,
        choices=[0, 1],
        help=f"start this jail when running: {SCRIPT_NAME} startup",
    )
    commands["create"].add_argument(
        "--seccomp",  #
        type=int,
        choices=[0, 1],
        help="turning off seccomp filtering improves performance at the expense of security",
    )
    commands["create"].add_argument(
        "-c",  #
        "--config",
        help="path to config file template or - for stdin",
    )
    commands["create"].add_argument(
        "-gi",  #
        "--gpu_passthrough_intel",
        type=int,
        choices=[0, 1],
    )
    commands["create"].add_argument(
        "-gn",  #
        "--gpu_passthrough_nvidia",
        type=int,
        choices=[0, 1],
    )
    commands["create"].add_argument(
        "systemd_nspawn_user_args",
        nargs="*",
        help="add additional systemd-nspawn flags",
    )

    if os.getuid() != 0:
        parser.print_help()
        fail("Run this script as root...")

    # Set appropriate permissions (if not already set) for this file, since it's executed as root
    stat_chmod(SCRIPT_PATH, 0o700)

    # Ignore all args after the first "--"
    args_to_parse = split_at_string(sys.argv[1:], "--")[0]
    # Check for help
    if any(item in args_to_parse for item in ["-h", "--help"]):
        # Likely we need to show help output...
        try:
            args = vars(parser.parse_known_args(args_to_parse)[0])
            # We've exited by now if not invoking a subparser: jlmkr.py --help
            if args.get("help"):
                need_help = True
                command = args.get("command")

                # Edge case for some commands
                if command in split_commands and args["jail_name"]:
                    # Ignore all args after the jail name
                    args_to_parse = split_at_string(args_to_parse, args["jail_name"])[0]
                    # Add back the jail_name as it may be a required positional and we
                    # don't want to end up in the except clause below
                    args_to_parse += [args["jail_name"]]
                    # Parse one more time...
                    args = vars(parser.parse_known_args(args_to_parse)[0])
                    # ...and check if help is still in the remaining args
                    need_help = args.get("help")

                if need_help:
                    commands[command].print_help()
                    sys.exit()
        except ExceptionWithParser as e:
            # Print help output on error, e.g. due to:
            # "error: the following arguments are required"
            if e.parser.add_help:
                e.parser.print_help()
                sys.exit()

    # Exit on parse errors (e.g. missing positional args)
    for command in commands:
        commands[command].exit_on_error = True

    # Parse to find command and function and ignore unknown args which may be present
    # such as args intended to pass through to systemd-run
    args = vars(parser.parse_known_args()[0])
    command = args.pop("command", None)

    # Start over with original args
    args_to_parse = sys.argv[1:]

    if not command:
        # Parse args and show error for unknown args
        parser.parse_args(args_to_parse)

        if agree("Create a new jail?", "y"):
            print()
            sys.exit(create_jail())
        else:
            parser.print_help()
            sys.exit()

    elif command == "shell":
        # Pass anything after the "shell" command to machinectl
        _, shell_args = split_at_string(args_to_parse, command)
        sys.exit(args["func"](shell_args))
    elif command in split_commands and args["jail_name"]:
        jlmkr_args, remaining_args = split_at_string(args_to_parse, args["jail_name"])
        if remaining_args and remaining_args[0] != "--":
            # Add "--" after the jail name to ensure further args, e.g.
            # --help or --version, are captured as systemd_nspawn_user_args
            args_to_parse = jlmkr_args + [args["jail_name"], "--"] + remaining_args

    # Parse args again, but show error for unknown args
    args = vars(parser.parse_args(args_to_parse))
    # Clean the args
    args.pop("help")
    args.pop("command", None)
    func = args.pop("func")
    sys.exit(func(**args))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
