# SPDX-FileCopyrightText: © 2024 Jip-Hop and the Jailmakers <https://github.com/Jip-Hop/jailmaker>
#
# SPDX-License-Identifier: LGPL-3.0-only

import platform

from utils.chroot import Chroot


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
