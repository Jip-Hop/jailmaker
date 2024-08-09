# SPDX-FileCopyrightText: © 2024 Jip-Hop and the Jailmakers <https://github.com/Jip-Hop/jailmaker>
#
# SPDX-License-Identifier: LGPL-3.0-only

import os.path
import subprocess
from pathlib import PurePath

from paths import JAILMAKER_DIR_PATH

from utils.console import eprint, fail


def _get_relative_path_in_jailmaker_dir(absolute_path):
    return PurePath(absolute_path).relative_to(JAILMAKER_DIR_PATH)


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
    zfs_base_path = get_zfs_dataset(JAILMAKER_DIR_PATH)
    if not zfs_base_path:
        fail("Failed to get dataset path for jailmaker directory.")

    return zfs_base_path


def create_zfs_dataset(absolute_path):
    """
    Create a ZFS Dataset inside the jailmaker directory at the provided absolute path.
    E.g. "/mnt/mypool/jailmaker/jails" or "/mnt/mypool/jailmaker/jails/newjail").
    """
    relative_path = _get_relative_path_in_jailmaker_dir(absolute_path)
    dataset_to_create = os.path.join(get_zfs_base_path(), relative_path)
    eprint(f"Creating ZFS Dataset {dataset_to_create}")
    subprocess.run(["zfs", "create", dataset_to_create], check=True)


def remove_zfs_dataset(absolute_path):
    """
    Remove a ZFS Dataset inside the jailmaker directory at the provided absolute path.
    E.g. "/mnt/mypool/jailmaker/jails/oldjail".
    """
    relative_path = _get_relative_path_in_jailmaker_dir(absolute_path)
    dataset_to_remove = os.path.join((get_zfs_base_path()), relative_path)
    eprint(f"Removing ZFS Dataset {dataset_to_remove}")
    subprocess.run(["zfs", "destroy", "-r", dataset_to_remove], check=True)
