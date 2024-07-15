#!/usr/bin/env python3

"""Create persistent Linux 'jails' on TrueNAS SCALE, \
with full access to all files via bind mounts, \
thanks to systemd-nspawn!"""

__version__ = "3.0.0"
__author__ = "Jip-Hop"
__copyright__ = "Copyright (C) 2023, Jip-Hop"
__license__ = "LGPL-3.0-only"
__disclaimer__ = """USE THIS SCRIPT AT YOUR OWN RISK!
IT COMES WITHOUT WARRANTY AND IS NOT SUPPORTED BY IXSYSTEMS."""

import argparse
import contextlib
import hashlib
import json
import os
import platform
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import urllib.request
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

from utils.paths import SCRIPT_PATH, SCRIPT_NAME, SCRIPT_DIR_PATH
from utils.paths import JAILS_DIR_PATH, JAIL_CONFIG_NAME, JAIL_ROOTFS_NAME
from utils.paths import COMMAND_NAME, SHORTNAME
from utils.console import BOLD, RED, YELLOW, UNDERLINE, NORMAL

DISCLAIMER = f"""{YELLOW}{BOLD}{__disclaimer__}{NORMAL}"""

from utils.config_parser import ExceptionWithParser, KeyValueParser
from utils.config_parser import parse_config_file


# Workaround for exit_on_error=False not applying to:
# "error: the following arguments are required"
# https://github.com/python/cpython/issues/103498
class CustomSubParser(argparse.ArgumentParser):
    def error(self, message):
        if self.exit_on_error:
            super().error(message)
        else:
            raise ExceptionWithParser(self, message)


from utils.chroot import Chroot
from utils.console import eprint, fail
from utils.jail_dataset import get_jail_path, get_jail_config_path, get_jail_rootfs_path

from actions.exec import exec_jail
from actions.status import status_jail
from actions.log import log_jail
from actions.shell import shell_jail
from actions.start import start_jail
from actions.restart import restart_jail
from actions.images import run_lxc_download_script


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


from utils.files import stat_chmod


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

    jail_name = kwargs.pop("jail_name")
    start_now = False

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
            print(f"Creating jail {jail_name} from config template passed via stdin.")
            config.read_string(sys.stdin.read())
        else:
            print(f"Creating jail {jail_name} from config template {jail_config_path}.")
            if jail_config_path not in config.read(jail_config_path):
                eprint(f"Failed to read config template {jail_config_path}.")
                return 1
    else:
        print(f"Creating jail {jail_name} with default config.")
        config.read_string(DEFAULT_CONFIG)

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


from utils.jail_dataset import jail_is_running


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


from actions.stop import stop_jail


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


from utils.parent_dataset import get_all_jail_names
from utils.jail_dataset import parse_os_release
from actions.list import list_jails


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
    kwargs["formatter_class"] = argparse.RawDescriptionHelpFormatter
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
      if os.environ.get('JLMKR_DEBUG') is not None:
        fail(
            f"This script should be owned by the root user... Fix it manually with: `chown root {SCRIPT_PATH}`."
        )

    parser = argparse.ArgumentParser(
        description=__doc__,
        allow_abbrev=False,
        epilog=f"For more info on some command, run: {COMMAND_NAME} some_command --help.\n{DISCLAIMER}",
        formatter_class=argparse.RawDescriptionHelpFormatter,
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

    for cmd in [
        "create",
        "edit",
        "exec",
        "log",
        "remove",
        "restart",
        "start",
        "status",
        "stop",
    ]:
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
        "--distro", metavar="X", help="desired DIST from the images list"
    )
    commands["create"].add_argument(
        "--release", metavar="X", help="desired RELEASE from the images list"
    )
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
        metavar="X",
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
        metavar="nspawn_args",
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
