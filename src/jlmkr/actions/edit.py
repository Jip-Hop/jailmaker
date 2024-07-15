# SPDX-FileCopyrightText: © 2024 Jip-Hop and the Jailmakers <https://github.com/Jip-Hop/jailmaker>
#
# SPDX-License-Identifier: LGPL-3.0-only

import os
import subprocess

from utils.console import eprint
from utils.editor import get_text_editor
from utils.jail_dataset import check_jail_name_valid, check_jail_name_available
from utils.jail_dataset import get_jail_config_path, jail_is_running


def edit_jail(jail_name):
    """
    Edit jail with given name.
    """

    if not check_jail_name_valid(jail_name):
        return 1

    if check_jail_name_available(jail_name, False):
        eprint(f"A jail with name {jail_name} does not exist.")
        return 1

    jail_config_path = get_jail_config_path(jail_name)

    returncode = subprocess.run([get_text_editor(), jail_config_path]).returncode

    if returncode != 0:
        eprint(f"An error occurred while editing {jail_config_path}.")
        return returncode

    if jail_is_running(jail_name):
        print("\nRestart the jail for edits to apply (if you made any).")

    return 0
