# SPDX-FileCopyrightText: © 2024 Jip-Hop and the Jailmakers <https://github.com/Jip-Hop/jailmaker>
#
# SPDX-License-Identifier: LGPL-3.0-only

from actions.start import start_jail
from actions.stop import stop_jail
from utils.console import eprint


def restart_jail(jail_name):
    """
    Restart jail with given name.
    """

    returncode = stop_jail(jail_name)
    if returncode != 0:
        eprint("Abort restart.")
        return returncode

    return start_jail(jail_name)
