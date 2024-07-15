# SPDX-FileCopyrightText: © 2024 Jip-Hop and the Jailmakers <https://github.com/Jip-Hop/jailmaker>
#
# SPDX-License-Identifier: LGPL-3.0-only

import os.path


# When running as a zipapp, the script file is a parent
ZIPAPP_PATH = os.path.realpath(__file__)
while not os.path.exists(ZIPAPP_PATH):
    ZIPAPP_PATH = os.path.dirname(ZIPAPP_PATH)

SCRIPT_PATH = os.path.realpath(ZIPAPP_PATH)
SCRIPT_NAME = os.path.basename(SCRIPT_PATH)
SCRIPT_DIR_PATH = os.path.dirname(SCRIPT_PATH)
COMMAND_NAME = os.path.basename(ZIPAPP_PATH)

JAILS_DIR_PATH = os.path.join(SCRIPT_DIR_PATH, "jails")
JAIL_CONFIG_NAME = "config"
JAIL_ROOTFS_NAME = "rootfs"

SHORTNAME = "jlmkr"
