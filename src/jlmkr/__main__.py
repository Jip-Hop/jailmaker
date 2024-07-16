#!/usr/bin/env python3
# SPDX-FileCopyrightText: © 2024 Jip-Hop and the Jailmakers <https://github.com/Jip-Hop/jailmaker>
#
# SPDX-License-Identifier: LGPL-3.0-only

"""Create persistent Linux 'jails' on TrueNAS SCALE, \
with full access to all files via bind mounts, \
thanks to systemd-nspawn!"""

__version__ = "3.0.0.dev1"
__author__ = "Jip-Hop"
__copyright__ = "Copyright © 2024, Jip-Hop and the Jailmakers"
__license__ = "LGPL-3.0-only"
__disclaimer__ = """USE THIS SCRIPT AT YOUR OWN RISK!
IT COMES WITHOUT WARRANTY AND IS NOT SUPPORTED BY IXSYSTEMS."""


import sys

from cli import main

if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
