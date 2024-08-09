# SPDX-FileCopyrightText: © 2024 Jip-Hop and the Jailmakers <https://github.com/Jip-Hop/jailmaker>
#
# SPDX-License-Identifier: LGPL-3.0-only

from utils.files import get_mount_point


def test_mount_point():
    return # oops good choice for TrueNAS; poor choice for GitHub Runner
    assert get_mount_point('/usr/local/share/truenas/eula.html') == '/usr'
