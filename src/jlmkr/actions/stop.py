# SPDX-FileCopyrightText: © 2024 Jip-Hop and the Jailmakers <https://github.com/Jip-Hop/jailmaker>
#
# SPDX-License-Identifier: LGPL-3.0-only

import subprocess
import time

from utils.console import eprint
from utils.dataset import jail_is_running


def stop_jail(jail_name):
    """
    Stop jail with given name and wait until stopped.
    """

    if not jail_is_running(jail_name):
        return 0

    returncode = subprocess.run(["machinectl", "poweroff", jail_name]).returncode
    if returncode != 0:
        eprint("Error while stopping jail.")
        return returncode

    print(f"Wait for {jail_name} to stop", end="", flush=True)

    while jail_is_running(jail_name):
        time.sleep(1)
        print(".", end="", flush=True)

    return 0
