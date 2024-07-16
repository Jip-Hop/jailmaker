# SPDX-FileCopyrightText: © 2024 Jip-Hop and the Jailmakers <https://github.com/Jip-Hop/jailmaker>
#
# SPDX-License-Identifier: LGPL-3.0-only
import os
import re
import shutil
import subprocess
from textwrap import dedent

from paths import JAIL_CONFIG_NAME, JAIL_ROOTFS_NAME, JAILS_DIR_PATH

from utils.console import BOLD, NORMAL, YELLOW, eprint
from utils.dataset import get_zfs_dataset, remove_zfs_dataset


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


def jail_is_running(jail_name):
    return (
        subprocess.run(
            ["machinectl", "show", jail_name],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ).returncode
        == 0
    )


def get_jail_path(jail_name):
    return os.path.join(JAILS_DIR_PATH, jail_name)


def get_jail_config_path(jail_name):
    return os.path.join(get_jail_path(jail_name), JAIL_CONFIG_NAME)


def get_jail_rootfs_path(jail_name):
    return os.path.join(get_jail_path(jail_name), JAIL_ROOTFS_NAME)


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


def get_all_jail_names():
    try:
        jail_names = os.listdir(JAILS_DIR_PATH)
    except FileNotFoundError:
        jail_names = []

    return jail_names
