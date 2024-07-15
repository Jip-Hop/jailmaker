# SPDX-FileCopyrightText: © 2024 Jip-Hop and the Jailmakers <https://github.com/Jip-Hop/jailmaker>
#
# SPDX-License-Identifier: LGPL-3.0-only

import os

from utils.paths import JAILS_DIR_PATH


def get_all_jail_names():
    try:
        jail_names = os.listdir(JAILS_DIR_PATH)
    except FileNotFoundError:
        jail_names = []

    return jail_names
