# SPDX-FileCopyrightText: © 2024 Jip-Hop and the Jailmakers <https://github.com/Jip-Hop/jailmaker>
#
# SPDX-License-Identifier: LGPL-3.0-only

from actions.start import start_jail
from utils.config_parser import parse_config_file
from utils.jail import get_all_jail_names, get_jail_config_path


def startup_jails():
    start_failure = False
    for jail_name in get_all_jail_names():
        config = parse_config_file(get_jail_config_path(jail_name))
        if config and config.my_getboolean("startup"):
            if start_jail(jail_name) != 0:
                start_failure = True

    if start_failure:
        return 1

    return 0
