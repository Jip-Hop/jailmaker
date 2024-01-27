#!/usr/bin/env python3

import argparse
import configparser
import contextlib
import ctypes
import glob
import hashlib
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
import time
import urllib.request
from collections import defaultdict
from inspect import cleandoc
from pathlib import Path, PurePath
from textwrap import dedent

# Only set a color if we have an interactive tty
if sys.stdout.isatty():
    BOLD = "\033[1m"
    RED = "\033[91m"
    YELLOW = "\033[93m"
    UNDERLINE = "\033[4m"
    NORMAL = "\033[0m"
else:
    BOLD = RED = YELLOW = UNDERLINE = NORMAL = ""

DISCLAIMER = f"""{YELLOW}{BOLD}USE THIS SCRIPT AT YOUR OWN RISK!
IT COMES WITHOUT WARRANTY AND IS NOT SUPPORTED BY IXSYSTEMS.{NORMAL}"""

DESCRIPTION = (
    "Create persistent Linux 'jails' on TrueNAS SCALE, with full access to all files \
    via bind mounts, thanks to systemd-nspawn!"
)

VERSION = "1.0.1"

JAILS_DIR_PATH = "jails"
JAIL_CONFIG_NAME = "config"
JAIL_ROOTFS_NAME = "rootfs"
DOWNLOAD_SCRIPT_DIGEST = (
    "6cca2eda73c7358c232fecb4e750b3bf0afa9636efb5de6a9517b7df78be12a4"
)
SCRIPT_PATH = os.path.realpath(__file__)
SCRIPT_NAME = os.path.basename(SCRIPT_PATH)
SCRIPT_DIR_PATH = os.path.dirname(SCRIPT_PATH)
COMMAND_NAME = os.path.basename(__file__)
SYMLINK_NAME = "jlmkr"
TEXT_EDITOR = "nano"


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


def passthrough_intel(gpu_passthrough_intel, systemd_nspawn_additional_args):
    if gpu_passthrough_intel != "1":
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
        os.path.join(jail_rootfs_path), f"etc/ld.so.conf.d/{SYMLINK_NAME}-nvidia.conf"
    )

    if gpu_passthrough_nvidia != "1":
        # Cleanup the config file we made when passthrough was enabled
        ld_so_conf_path.unlink(missing_ok=True)
        return

    # Load the nvidia kernel module
    if subprocess.run(["modprobe", "nvidia-current-uvm"]).returncode != 0:
        eprint(
            dedent(
                """
            Failed to load nvidia-current-uvm kernel module.
            Skip passthrough of nvidia GPU."""
            )
        )
        return

    # Run nvidia-smi to initialize the nvidia driver
    # If we can't run nvidia-smi successfully,
    # then nvidia-container-cli list will fail too:
    # we shouldn't continue with gpu passthrough
    if subprocess.run(["nvidia-smi", "-f", "/dev/null"]).returncode != 0:
        eprint("Skip passthrough of nvidia GPU.")
        return

    try:
        nvidia_files = set(
            (
                [
                    x
                    for x in subprocess.check_output(["nvidia-container-cli", "list"])
                    .decode()
                    .split("\n")
                    if x
                ]
            )
        )
    except:
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
        nvidia_libraries = set(
            Path(x)
            for x in subprocess.check_output(
                ["nvidia-container-cli", "list", "--libraries"]
            )
            .decode()
            .split("\n")
            if x
        )
        library_folders = set(str(x.parent) for x in nvidia_libraries)

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


def exec_jail(jail_name, cmd, args):
    """
    Execute a command in the jail with given name.
    """
    subprocess.run(
        [
            "systemd-run",
            "--machine",
            jail_name,
            "--quiet",
            "--pipe",
            "--wait",
            "--collect",
            "--service-type=exec",
            cmd,
        ]
        + args,
        check=True,
    )


def status_jail(jail_name):
    """
    Show the status of the systemd service wrapping the jail with given name.
    """
    # Alternatively `machinectl status jail_name` could be used
    subprocess.run(["systemctl", "status", f"{SYMLINK_NAME}-{jail_name}"])


def log_jail(jail_name):
    """
    Show the log file of the jail with given name.
    """
    subprocess.run(["journalctl", "-u", f"{SYMLINK_NAME}-{jail_name}"])


def shell_jail(jail_name):
    """
    Open a shell in the jail with given name.
    """
    subprocess.run(["machinectl", "shell", jail_name])


def stop_jail(jail_name):
    """
    Stop jail with given name.
    """
    subprocess.run(["machinectl", "poweroff", jail_name])


def parse_config(jail_config_path):
    config = configparser.ConfigParser()
    try:
        # Workaround to read config file without section headers
        config.read_string("[DEFAULT]\n" + Path(jail_config_path).read_text())
    except FileNotFoundError:
        eprint(f"Unable to find config file: {jail_config_path}.")
        return

    config = dict(config["DEFAULT"])

    return config


def start_jail(jail_name, check_startup_enabled=False):
    """
    Start jail with given name.
    """
    skip_start_message = (
        f"Skipped starting jail {jail_name}. It appears to be running already..."
    )

    if not check_startup_enabled and jail_is_running(jail_name):
        fail(skip_start_message)

    jail_path = get_jail_path(jail_name)
    jail_config_path = get_jail_config_path(jail_name)

    config = parse_config(jail_config_path)

    if not config:
        fail("Aborting...")

    # Only start if the startup setting is enabled in the config
    if check_startup_enabled:
        if config.get("startup") == "1":
            # We should start this jail based on the startup config...
            if jail_is_running(jail_name):
                # ...but we can skip if it's already running
                eprint(skip_start_message)
                return
        else:
            # Skip starting this jail since the startup config setting isnot enabled
            return

    systemd_run_additional_args = [
        f"--unit={SYMLINK_NAME}-{jail_name}",
        f"--working-directory=./{jail_path}",
        f"--description=My nspawn jail {jail_name} [created with jailmaker]",
    ]

    # Always add --bind-ro=/sys/module to make lsmod happy
    # https://manpages.debian.org/bookworm/manpages/sysfs.5.en.html
    systemd_nspawn_additional_args = [
        f"--machine={jail_name}",
        f"--directory={JAIL_ROOTFS_NAME}",
    ]

    # TODO: split the docker_compatible option into separate options
    #   - privileged (to disable seccomp, set DevicePolicy=auto and add all capabilities)
    #   "The bottom line is that using the --privileged flag does not tell the container
    #   engines to add additional security constraints. The --privileged flag does not add
    #   any privilege over what the processes launching the containers have."
    #   "Container engines user namespace is not affected by the --privileged flag"
    #   Meaning in the context of systemd-nspawn I could have a privileged option,
    #   which would also apply to jails with --private-users (user namespacing)
    #   https://www.redhat.com/sysadmin/privileged-flag-container-engines
    #   - how to call the option to enable ip_forward and bridge-nf-call?
    #   - add CSV value for preloading kernel modules like linux.kernel_modules in LXC

    if config.get("docker_compatible") == "1":
        # Enable ip forwarding on the host (docker needs it)
        print(1, file=open("/proc/sys/net/ipv4/ip_forward", "w"))

        # Load br_netfilter kernel module and enable bridge-nf-call to fix warning when running docker info:
        # WARNING: bridge-nf-call-iptables is disabled
        # WARNING: bridge-nf-call-ip6tables is disabled
        #
        # If we are using Apps then this should already be enabled
        # May cause "guest container traffic to be blocked by iptables rules that are intended for the host"
        # https://unix.stackexchange.com/q/720105/477308
        # https://github.com/moby/moby/issues/24809
        # https://docs.oracle.com/en/operating-systems/oracle-linux/docker/docker-KnownIssues.html#docker-issues
        # https://wiki.libvirt.org/page/Net.bridge.bridge-nf-call_and_sysctl.conf
        # https://serverfault.com/questions/963759/docker-breaks-libvirt-bridge-network

        if subprocess.run(["modprobe", "br_netfilter"]).returncode == 0:
            print(1, file=open("/proc/sys/net/bridge/bridge-nf-call-iptables", "w"))
            print(1, file=open("/proc/sys/net/bridge/bridge-nf-call-ip6tables", "w"))
        else:
            eprint(
                dedent(
                    """
                Failed to load br_netfilter kernel module."""
                )
            )

        # To properly run docker inside the jail, we need to lift restrictions
        # Without DevicePolicy=auto images with device nodes may not be pulled
        # For example docker pull ljishen/sysbench would fail
        # Fortunately I didn't encounter many images with device nodes...
        #
        # Issue: https://github.com/moby/moby/issues/35245
        #
        # The systemd-nspawn manual explicitly mentions:
        # Device nodes may not be created
        # https://www.freedesktop.org/software/systemd/man/systemd-nspawn.html
        #
        # Workaround: https://github.com/kinvolk/kube-spawn/pull/328
        #
        # As of 26-3-2024 on TrueNAS-SCALE-23.10.1.1 it seems to no longer be
        # required to use DevicePolicy=auto
        # Docker can successfully pull the ljishen/sysbench test image
        # Running mknod /dev/port c 1 4 manually works too...
        # Unknown why this suddenly started working...
        # https://github.com/systemd/systemd/issues/21987
        #
        # Use SYSTEMD_SECCOMP=0: https://github.com/systemd/systemd/issues/18370

        systemd_run_additional_args += [
            "--setenv=SYSTEMD_SECCOMP=0",
            "--property=DevicePolicy=auto",
        ]

        # Add additional flags required for docker
        systemd_nspawn_additional_args += [
            "--capability=all",
        ]

    # Legacy gpu_passthrough config setting
    if config.get("gpu_passthrough") == "1":
        gpu_passthrough_intel = "1"
        gpu_passthrough_nvidia = "1"
    else:
        gpu_passthrough_intel = config.get("gpu_passthrough_intel")
        gpu_passthrough_nvidia = config.get("gpu_passthrough_nvidia")

    if gpu_passthrough_intel == "1" or gpu_passthrough_nvidia == "1":
        systemd_nspawn_additional_args.append("--property=DeviceAllow=char-drm rw")

    passthrough_intel(gpu_passthrough_intel, systemd_nspawn_additional_args)
    passthrough_nvidia(
        gpu_passthrough_nvidia, systemd_nspawn_additional_args, jail_name
    )

    cmd = [
        "systemd-run",
        *shlex.split(config.get("systemd_run_default_args", "")),
        *systemd_run_additional_args,
        "--",
        "systemd-nspawn",
        *shlex.split(config.get("systemd_nspawn_default_args", "")),
        *systemd_nspawn_additional_args,
        *shlex.split(config.get("systemd_nspawn_user_args", "")),
    ]

    print(
        dedent(
            f"""
        Starting jail {jail_name} with the following command:

        {shlex.join(cmd)}
    """
        )
    )

    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError:
        fail(
            dedent(
                f"""
            Failed to start jail {jail_name}...
            In case of a config error, you may fix it with:
            {SYMLINK_NAME} edit {jail_name}
        """
            )
        )


def cleanup(jail_path):
    """
    Cleanup after aborted jail creation.
    """
    if os.path.isdir(jail_path):
        eprint(f"Cleaning up: {jail_path}")
        shutil.rmtree(jail_path)


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
            "https://raw.githubusercontent.com/Jip-Hop/lxc/58520263041b6864cadad96278848f9b8ce78ee9/templates/lxc-download.in",
            lxc_download_script,
        )
        if not validate_sha256(lxc_download_script, DOWNLOAD_SCRIPT_DIGEST):
            fail("Abort! Downloaded script has unexpected contents.")

    stat_chmod(lxc_download_script, 0o700)

    check_exit_code = False

    if None not in [jail_name, jail_path, jail_rootfs_path, distro, release]:
        check_exit_code = True
        cmd = [
            lxc_download_script,
            f"--name={jail_name}",
            f"--path={jail_path}",
            f"--rootfs={jail_rootfs_path}",
            f"--arch={arch}",
            f"--dist={distro}",
            f"--release={release}",
        ]
    else:
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

    p1.wait()

    if check_exit_code and p1.returncode != 0:
        fail("Aborting...")


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


def create_jail(jail_name, distro="debian", release="bookworm"):
    """
    Create jail with given name.
    """

    print(DISCLAIMER)

    if os.path.basename(os.getcwd()) != "jailmaker":
        fail(
            dedent(
                f"""
            {COMMAND_NAME} needs to create files.
            Currently it can not decide if it is safe to create files in:
            {SCRIPT_DIR_PATH}
            Please create a dedicated directory called 'jailmaker', store {SCRIPT_NAME} there and try again."""
            )
        )

    if not PurePath(get_mount_point(os.getcwd())).is_relative_to("/mnt"):
        print(
            dedent(
                f"""
            {YELLOW}{BOLD}WARNING: BEWARE OF DATA LOSS{NORMAL}

            {SCRIPT_NAME} should be on a dataset mounted under /mnt (it currently is not).
            Storing it on the boot-pool means losing all jails when updating TrueNAS.
            If you continue, jails will be stored under:
            {SCRIPT_DIR_PATH}
        """
            )
        )
        if not agree("Do you wish to ignore this warning and continue?", "n"):
            fail("Aborting...")

    # Create the dir where to store the jails
    os.makedirs(JAILS_DIR_PATH, exist_ok=True)
    stat_chmod(JAILS_DIR_PATH, 0o700)

    print()
    if not agree(f"Install the recommended image ({distro} {release})?", "y"):
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

        run_lxc_download_script()

        print(
            dedent(
                """
            Choose from the DIST column.
        """
            )
        )

        distro = input("Distro: ")

        print(
            dedent(
                """
            Choose from the RELEASE column (or ARCH if RELEASE is empty).
        """
            )
        )

        release = input("Release: ")

    while True:
        print()
        jail_name = input_with_default("Enter jail name: ", jail_name).strip()
        if check_jail_name_valid(jail_name):
            if check_jail_name_available(jail_name):
                break

    jail_path = get_jail_path(jail_name)

    # Cleanup in except, but only once the jail_path is final
    # Otherwise we may cleanup the wrong directory
    try:
        print(
            dedent(
                f"""
            Docker won't be installed by {COMMAND_NAME}.
            But it can setup the jail with the capabilities required to run docker.
            You can turn DOCKER_COMPATIBLE mode on/off post-install.
        """
            )
        )

        docker_compatible = 0

        if agree("Make jail docker compatible right now?", "n"):
            docker_compatible = 1

        print()

        gpu_passthrough_intel = 0

        if agree("Passthrough the intel GPU (if present)?", "n"):
            gpu_passthrough_intel = 1

        print()

        gpu_passthrough_nvidia = 0

        if agree("Passthrough the nvidia GPU (if present)?", "n"):
            gpu_passthrough_nvidia = 1

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
                    "VERSION_CODENAME", release
                )
            except AttributeError:
                base_os_version = release
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
            Or create MACVLAN interface for static IP, with:
            --network-macvlan=eno1 --resolv-conf=bind-host
        """
            )
        )

        # Enable tab auto completion of file paths after the = symbol
        readline.set_completer_delims("=")
        readline.parse_and_bind("tab: complete")

        readline_lib = ctypes.CDLL(readline.__file__)
        rl_completer_quote_characters = ctypes.c_char_p.in_dll(
            readline_lib, "rl_completer_quote_characters"
        )

        # Let the readline library know about quote characters for completion
        rl_completer_quote_characters.value = "\"'".encode("utf-8")

        # TODO: more robust tab completion of file paths with space or = character
        # Currently completing these only works when the path is quoted
        # https://thoughtbot.com/blog/tab-completion-in-gnu-readline
        # https://stackoverflow.com/a/67118744
        # https://github.com/python-cmd2/cmd2/blob/ee7599f9ac0dbb6ce3793f6b665ba1200d3ef9a3/cmd2/cmd2.py
        # https://stackoverflow.com/a/40152927

        systemd_nspawn_user_args = input("Additional flags: ") or ""
        # Disable tab auto completion
        readline.parse_and_bind("tab: self-insert")

        print(
            dedent(
                f"""
            The `{COMMAND_NAME} startup` command can automatically ensure {COMMAND_NAME} is installed properly and start a selection of jails.
            This comes in handy when you want to automatically start multiple jails after booting TrueNAS SCALE (e.g. from a Post Init Script).
        """
            )
        )

        startup = int(
            agree(
                f"Do you want to start this jail when running: {COMMAND_NAME} startup?",
                "n",
            )
        )

        print()

        jail_config_path = get_jail_config_path(jail_name)
        jail_rootfs_path = get_jail_rootfs_path(jail_name)

        # Create directory for rootfs
        os.makedirs(jail_rootfs_path, exist_ok=True)
        # LXC download script needs to write to this file during install
        # but we don't need it so we will remove it later
        open(jail_config_path, "a").close()

        run_lxc_download_script(jail_name, jail_path, jail_rootfs_path, distro, release)

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

        if (
            os.path.basename(
                os.path.realpath(os.path.join(jail_rootfs_path, "sbin/init"))
            )
            != "systemd"
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

            if agree("Abort creating jail?", "y"):
                exit(1)

        with contextlib.suppress(FileNotFoundError):
            # Remove config which systemd handles for us
            os.remove(os.path.join(jail_rootfs_path, "etc/machine-id"))
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

            # Override preset which caused systemd-networkd to be disabled (e.g. fedora 39)
            # https://www.freedesktop.org/software/systemd/man/latest/systemd.preset.html
            # https://github.com/lxc/lxc-ci/blob/f632823ecd9b258ed42df40449ec54ed7ef8e77d/images/fedora.yaml#L312C5-L312C38

            preset_path = os.path.join(jail_rootfs_path, "etc/systemd/system-preset")
            os.makedirs(preset_path, exist_ok=True)
            print(
                "enable systemd-networkd.service",
                file=open(os.path.join(preset_path, "00-jailmaker.preset"), "w"),
            )

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

        systemd_run_default_args = [
            "--property=KillMode=mixed",
            "--property=Type=notify",
            "--property=RestartForceExitStatus=133",
            "--property=SuccessExitStatus=133",
            "--property=Delegate=yes",
            "--property=TasksMax=infinity",
            "--collect",
            "--setenv=SYSTEMD_NSPAWN_LOCK=0",
        ]

        systemd_nspawn_default_args = [
            "--keep-unit",
            "--quiet",
            "--boot",
            "--bind-ro=/sys/module",
        ]

        config = cleandoc(
            f"""
            startup={startup}
            docker_compatible={docker_compatible}
            gpu_passthrough_intel={gpu_passthrough_intel}
            gpu_passthrough_nvidia={gpu_passthrough_nvidia}
            systemd_nspawn_user_args={systemd_nspawn_user_args}
            # You generally will not need to change the options below
            systemd_run_default_args={' '.join(systemd_run_default_args)}
            systemd_nspawn_default_args={' '.join(systemd_nspawn_default_args)}
        """
        )

        print(config, file=open(jail_config_path, "w"))

        os.chmod(jail_config_path, 0o600)

    # Cleanup on any exception and rethrow
    except BaseException as error:
        cleanup(jail_path)
        raise error

    print()
    if agree(f"Do you want to start jail {jail_name} right now?", "y"):
        start_jail(jail_name)


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
    if check_jail_name_valid(jail_name):
        if check_jail_name_available(jail_name, False):
            eprint(f"A jail with name {jail_name} does not exist.")
        else:
            jail_config_path = get_jail_config_path(jail_name)
            if not shutil.which(TEXT_EDITOR):
                eprint(f"Unable to edit config file: {jail_config_path}.")
                eprint(f"The {TEXT_EDITOR} text editor is not available.")
            else:
                subprocess.run([TEXT_EDITOR, get_jail_config_path(jail_name)])
                if jail_is_running(jail_name):
                    print("\nRestart the jail for edits to apply (if you made any).")


def remove_jail(jail_name):
    """
    Remove jail with given name.
    """

    if check_jail_name_valid(jail_name):
        if check_jail_name_available(jail_name, False):
            eprint(f"A jail with name {jail_name} does not exist.")
        else:
            check = (
                input(f'\nCAUTION: Type "{jail_name}" to confirm jail deletion!\n\n')
                or ""
            )
            if check == jail_name:
                jail_path = get_jail_path(jail_name)
                if jail_is_running(jail_name):
                    print(f"\nWait for {jail_name} to stop...", end="")
                    stop_jail(jail_name)
                    # Need to sleep since deleting immediately after stop causes problems...
                    while jail_is_running(jail_name):
                        time.sleep(1)
                        print(".", end="", flush=True)

                print(f"\nCleaning up: {jail_path}")
                shutil.rmtree(jail_path)
            else:
                eprint("Wrong name, nothing happened.")


def print_table(header, list_of_objects, empty_value_indicator):
    # Find max width for each column
    widths = defaultdict(int)
    for obj in list_of_objects:
        for hdr in header:
            widths[hdr] = max(widths[hdr], len(str(obj.get(hdr))), len(str(hdr)))

    # Print header
    print(
        UNDERLINE + " ".join(hdr.upper().ljust(widths[hdr]) for hdr in header) + NORMAL
    )

    # Print rows
    for obj in list_of_objects:
        print(
            " ".join(
                str(obj.get(hdr, empty_value_indicator)).ljust(widths[hdr])
                for hdr in header
            )
        )


def run_command_and_parse_json(command):
    result = subprocess.run(command, capture_output=True, text=True)
    output = result.stdout.strip()

    try:
        parsed_output = json.loads(output)
        return parsed_output
    except json.JSONDecodeError as e:
        print(f"Error parsing JSON: {e}")
        return None


def get_all_jail_names():
    try:
        jail_names = os.listdir(JAILS_DIR_PATH)
    except FileNotFoundError:
        jail_names = []

    return jail_names


def list_jails():
    """
    List all available and running jails.
    """

    jails = {}
    empty_value_indicator = "-"

    jail_names = get_all_jail_names()

    if not jail_names:
        print("No jails.")
        return

    for jail in jail_names:
        jails[jail] = {"name": jail, "running": False}

    # Get running jails from machinectl
    running_machines = run_command_and_parse_json(["machinectl", "list", "-o", "json"])

    # Augment the jails dict with output from machinectl
    for machine in running_machines:
        machine_name = machine["machine"]
        # We're only interested in the list of jails made with jailmaker
        if machine["service"] == "systemd-nspawn" and machine_name in jails:
            addresses = (machine.get("addresses") or empty_value_indicator).split("\n")
            if len(addresses) > 1:
                addresses = addresses[0] + "…"
            else:
                addresses = addresses[0]

            jails[machine_name] = {
                "name": machine_name,
                "running": True,
                "os": machine["os"],
                "version": machine["version"],
                "addresses": addresses,
            }

    # TODO: add additional properties from the jails config file

    for jail_name in jails:
        config = parse_config(get_jail_config_path(jail_name))

        startup = False
        if config:
            startup = bool(int(config.get("startup", "0")))
        # TODO: in case config is missing or parsing fails,
        # should an error message be thrown here?

        jails[jail_name]["startup"] = startup

    print_table(
        ["name", "running", "startup", "os", "version", "addresses"],
        sorted(jails.values(), key=lambda x: x["name"]),
        empty_value_indicator,
    )


def install_jailmaker():
    # Check if command exists in path
    if shutil.which("systemd-nspawn"):
        print("systemd-nspawn is already installed.")
    else:
        print("Installing jailmaker dependencies...")

        original_permissions = {}

        print(
            "Temporarily enable apt and dpkg (if not already enabled) to install systemd-nspawn."
        )

        # Make /bin/apt* and /bin/dpkg* files executable
        for file in glob.glob("/bin/apt*") + (glob.glob("/bin/dpkg*")):
            original_permissions[file] = os.stat(file).st_mode
            stat_chmod(file, 0o755)

        subprocess.run(["apt-get", "update"], check=True)
        subprocess.run(["apt-get", "install", "-y", "systemd-container"], check=True)

        # Restore original permissions
        print("Restore permissions of apt and dpkg.")

        for file, original_permission in original_permissions.items():
            stat_chmod(file, original_permission)

    target = f"/usr/local/sbin/{SYMLINK_NAME}"

    # Check if command exists in path
    if shutil.which(SYMLINK_NAME):
        print(f"The {SYMLINK_NAME} command is available.")
    elif not os.path.lexists(target):
        print(f"Creating symlink {target} to {SCRIPT_PATH}.")
        os.symlink(SCRIPT_PATH, target)
    else:
        print(
            f"File {target} already exists... Maybe it's a broken symlink from a previous install attempt?"
        )
        print(f"Skipped creating new symlink {target} to {SCRIPT_PATH}.")

    print("Done installing jailmaker.")


def startup_jails():
    install_jailmaker()
    for jail_name in get_all_jail_names():
        start_jail(jail_name, True)


def main():
    if os.stat(SCRIPT_PATH).st_uid != 0:
        fail(
            f"This script should be owned by the root user... Fix it manually with: `chown root {SCRIPT_PATH}`."
        )

    parser = argparse.ArgumentParser(description=DESCRIPTION, epilog=DISCLAIMER)

    parser.add_argument("--version", action="version", version=VERSION)

    subparsers = parser.add_subparsers(title="commands", dest="subcommand", metavar="")

    subparsers.add_parser(
        name="install",
        epilog=DISCLAIMER,
        help="install jailmaker dependencies and create symlink",
    )

    subparsers.add_parser(
        name="create", epilog=DISCLAIMER, help="create a new jail"
    ).add_argument("name", nargs="?", help="name of the jail")

    subparsers.add_parser(
        name="start", epilog=DISCLAIMER, help="start a previously created jail"
    ).add_argument("name", help="name of the jail")

    subparsers.add_parser(
        name="shell", epilog=DISCLAIMER, help="open shell in running jail"
    ).add_argument("name", help="name of the jail")

    exec_parser = subparsers.add_parser(
        name="exec", epilog=DISCLAIMER, help="execute a command in the jail"
    )
    exec_parser.add_argument("name", help="name of the jail")
    exec_parser.add_argument("cmd", help="command to execute")

    subparsers.add_parser(
        name="status", epilog=DISCLAIMER, help="show jail status"
    ).add_argument("name", help="name of the jail")

    subparsers.add_parser(
        name="log", epilog=DISCLAIMER, help="show jail log"
    ).add_argument("name", help="name of the jail")

    subparsers.add_parser(
        name="stop", epilog=DISCLAIMER, help="stop a running jail"
    ).add_argument("name", help="name of the jail")

    subparsers.add_parser(
        name="edit",
        epilog=DISCLAIMER,
        help=f"edit jail config with {TEXT_EDITOR} text editor",
    ).add_argument("name", help="name of the jail to edit")

    subparsers.add_parser(
        name="remove", epilog=DISCLAIMER, help="remove a previously created jail"
    ).add_argument("name", help="name of the jail to remove")

    subparsers.add_parser(name="list", epilog=DISCLAIMER, help="list jails")

    subparsers.add_parser(
        name="images",
        epilog=DISCLAIMER,
        help="list available images to create jails from",
    )

    subparsers.add_parser(
        name="startup",
        epilog=DISCLAIMER,
        help=f"install {SYMLINK_NAME} and startup selected jails",
    )

    if os.getuid() != 0:
        parser.print_usage()
        fail("Run this script as root...")

    # Set appropriate permissions (if not already set) for this file, since it's executed as root
    stat_chmod(SCRIPT_PATH, 0o700)

    # Work relative to this script
    os.chdir(SCRIPT_DIR_PATH)

    args, additional_args = parser.parse_known_args()

    if args.subcommand == "install":
        install_jailmaker()

    elif args.subcommand == "create":
        create_jail(args.name)

    elif args.subcommand == "start":
        start_jail(args.name)

    elif args.subcommand == "shell":
        shell_jail(args.name)

    elif args.subcommand == "exec":
        exec_jail(args.name, args.cmd, additional_args)

    elif args.subcommand == "status":
        status_jail(args.name)

    elif args.subcommand == "log":
        log_jail(args.name)

    elif args.subcommand == "stop":
        stop_jail(args.name)

    elif args.subcommand == "edit":
        edit_jail(args.name)

    elif args.subcommand == "remove":
        remove_jail(args.name)

    elif args.subcommand == "list":
        list_jails()

    elif args.subcommand == "images":
        run_lxc_download_script()

    elif args.subcommand == "startup":
        startup_jails()

    else:
        if agree("Create a new jail?", "y"):
            print()
            create_jail("")
        else:
            parser.print_usage()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
