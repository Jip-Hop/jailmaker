# SPDX-FileCopyrightText: © 2024 Jip-Hop and the Jailmakers <https://github.com/Jip-Hop/jailmaker>
#
# SPDX-License-Identifier: LGPL-3.0-only

import os
import stat


def stat_chmod(file_path, mode):
    """
    Change mode if file doesn't already have this mode.
    """
    if mode != stat.S_IMODE(os.stat(file_path).st_mode):
        os.chmod(file_path, mode)


def get_mount_point(path):
    """
    Return the mount point on which the given path resides.
    """
    path = os.path.abspath(path)
    while not os.path.ismount(path):
        path = os.path.dirname(path)
    return path
