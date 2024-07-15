# SPDX-FileCopyrightText: © 2024 Jip-Hop and the Jailmakers <https://github.com/Jip-Hop/jailmaker>
#
# SPDX-License-Identifier: LGPL-3.0-only

import subprocess

from utils.paths import SHORTNAME


def log_jail(jail_name, args):
    """
    Show the log file of the jail with given name.
    """
    return subprocess.run(
        ["journalctl", "-u", f"{SHORTNAME}-{jail_name}", *args]
    ).returncode
