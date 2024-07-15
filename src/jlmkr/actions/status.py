# SPDX-FileCopyrightText: © 2024 Jip-Hop and the Jailmakers <https://github.com/Jip-Hop/jailmaker>
#
# SPDX-License-Identifier: LGPL-3.0-only

import subprocess

from utils.paths import SHORTNAME


def status_jail(jail_name, args):
    """
    Show the status of the systemd service wrapping the jail with given name.
    """
    # Alternatively `machinectl status jail_name` could be used
    return subprocess.run(
        ["systemctl", "status", f"{SHORTNAME}-{jail_name}", *args]
    ).returncode
