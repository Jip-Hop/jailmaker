# SPDX-FileCopyrightText: © 2024 Jip-Hop and the Jailmakers <https://github.com/Jip-Hop/jailmaker>
#
# SPDX-License-Identifier: LGPL-3.0-only

import subprocess


def shell_jail(args):
    """
    Open a shell in the jail with given name.
    """
    return subprocess.run(["machinectl", "shell"] + args).returncode
