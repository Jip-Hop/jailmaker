# SPDX-FileCopyrightText: © 2024 Jip-Hop and the Jailmakers <https://github.com/Jip-Hop/jailmaker>
#
# SPDX-License-Identifier: LGPL-3.0-only

import os.path
import platform
import subprocess

from utils.chroot import Chroot
from utils.paths import JAILS_DIR_PATH, JAIL_CONFIG_NAME, JAIL_ROOTFS_NAME


def get_jail_path(jail_name):
    return os.path.join(JAILS_DIR_PATH, jail_name)


def get_jail_config_path(jail_name):
    return os.path.join(get_jail_path(jail_name), JAIL_CONFIG_NAME)


def get_jail_rootfs_path(jail_name):
    return os.path.join(get_jail_path(jail_name), JAIL_ROOTFS_NAME)


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
