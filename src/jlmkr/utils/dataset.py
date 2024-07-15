# SPDX-FileCopyrightText: © 2024 Jip-Hop and the Jailmakers <https://github.com/Jip-Hop/jailmaker>
#
# SPDX-License-Identifier: LGPL-3.0-only

import os.path
import platform
import re
import shutil
import subprocess

from pathlib import PurePath
from textwrap import dedent

from paths import JAILS_DIR_PATH, JAIL_CONFIG_NAME, JAIL_ROOTFS_NAME, SCRIPT_DIR_PATH
from utils.chroot import Chroot
from utils.console import eprint, fail, YELLOW, BOLD, NORMAL


def get_jail_path(jail_name):
    return os.path.join(JAILS_DIR_PATH, jail_name)


def get_jail_config_path(jail_name):
    return os.path.join(get_jail_path(jail_name), JAIL_CONFIG_NAME)


def get_jail_rootfs_path(jail_name):
    return os.path.join(get_jail_path(jail_name), JAIL_ROOTFS_NAME)


def get_relative_path_in_jailmaker_dir(absolute_path):
    return PurePath(absolute_path).relative_to(SCRIPT_DIR_PATH)


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


def jail_is_running(jail_name):
    return (
        subprocess.run(
            ["machinectl", "show", jail_name],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ).returncode
        == 0
    )


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


def get_all_jail_names():
    try:
        jail_names = os.listdir(JAILS_DIR_PATH)
    except FileNotFoundError:
        jail_names = []

    return jail_names


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
