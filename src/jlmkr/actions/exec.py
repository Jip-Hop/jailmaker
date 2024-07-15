# SPDX-FileCopyrightText: © 2024 Jip-Hop and the Jailmakers <https://github.com/Jip-Hop/jailmaker>
#
# SPDX-License-Identifier: LGPL-3.0-only

import subprocess


def exec_jail(jail_name, cmd):
    """
    Execute a command in the jail with given name.
    """
    return subprocess.run(
        [
            "systemd-run",
            "--machine",
            jail_name,
            "--quiet",
            "--pipe",
            "--wait",
            "--collect",
            "--service-type=exec",
            *cmd,
        ]
    ).returncode
