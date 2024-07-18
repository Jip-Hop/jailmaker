# SPDX-FileCopyrightText: © 2024 Jip-Hop and the Jailmakers <https://github.com/Jip-Hop/jailmaker>
#
# SPDX-License-Identifier: LGPL-3.0-only

from jlmkr.utils.files import get_mount_point


def test_mount_point():
    assert get_mount_point('/usr/local/share/truenas/eula.html') == '/usr'
