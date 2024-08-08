# SPDX-FileCopyrightText: © 2024 Jip-Hop and the Jailmakers <https://github.com/Jip-Hop/jailmaker>
#
# SPDX-License-Identifier: LGPL-3.0-only

import os
import sys

from configparser import ConfigParser
from pathlib import Path
from utils.console import fail


def _get_selected_jailmaker_directory() -> Path:
    '''
    Determine the user's affirmative choice of parent jailmaker directory
    '''
    # first choice: global --dir/-D argument
    #TODO
    
    # next: JAILMAKER_DIR environment variable
    envname = 'JAILMAKER_DIR'
    if envname in os.environ:
        return Path(os.environ[envname])
    
    # next: ~/.local/share/jailmaker.conf
    secname = 'DEFAULT'
    cfgname = 'jailmaker_dir'
    username = ''
    if os.getuid() == 0 and 'SUDO_USER' in os.environ:
        username = os.environ['SUDO_USER']
    cfgpath = Path(f'~{username}/.local/share/jailmaker.conf').expanduser()
    cfg = ConfigParser()
    cfg.read(cfgpath)
    if 'ignore_owner' in cfg[secname]:
        os.environ['JLMKR_DEBUG'] = cfg[secname]['ignore_owner']
    if cfgname in cfg[secname]:
        return Path(cfg[secname][cfgname])
    
    # next: current directory iff it's named jailmaker
    script = Path(sys.argv[0]).resolve(True)
    if script.parent.name == 'jailmaker':
        return script.parent
    
    fail("Please specify a jailmaker directory path (JAILMAKER_DIR)")


def get_tool_path_on_disk() -> Path:
    '''
    Determine the script's location on disk
    '''
    # When running as a zipapp, the script file is an ancestor
    path = Path(__file__).resolve(strict=False)
    while path and not path.is_file():
        path = path.parent
    return path


SCRIPT_PATH = get_tool_path_on_disk()
SCRIPT_NAME = SCRIPT_PATH.name
COMMAND_NAME = SCRIPT_NAME
SHORTNAME = "jlmkr"

JAILMAKER_DIR_PATH = _get_selected_jailmaker_directory()

JAILS_DIR_PATH = JAILMAKER_DIR_PATH.joinpath("jails")
JAIL_CONFIG_NAME = "config"
JAIL_ROOTFS_NAME = "rootfs"
