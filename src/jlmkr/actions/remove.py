# SPDX-FileCopyrightText: © 2024 Jip-Hop and the Jailmakers <https://github.com/Jip-Hop/jailmaker>
#
# SPDX-License-Identifier: LGPL-3.0-only

from actions.stop import stop_jail
from utils.console import eprint
from utils.jail import (
    check_jail_name_valid,
    check_jail_name_available,
    get_jail_path,
    cleanup,
)


def remove_jail(jail_name):
    """
    Remove jail with given name.
    """

    if not check_jail_name_valid(jail_name):
        return 1

    if check_jail_name_available(jail_name, False):
        eprint(f"A jail with name {jail_name} does not exist.")
        return 1

    # TODO: print which dataset is about to be removed before the user confirmation
    # TODO: print that all zfs snapshots will be removed if jail has it's own zfs dataset
    check = input(f'\nCAUTION: Type "{jail_name}" to confirm jail deletion!\n\n')

    if check == jail_name:
        print()
        jail_path = get_jail_path(jail_name)
        returncode = stop_jail(jail_name)
        if returncode != 0:
            return returncode

        print()
        cleanup(jail_path)
        return 0
    else:
        eprint("Wrong name, nothing happened.")
        return 1
