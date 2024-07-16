# SPDX-FileCopyrightText: © 2024 Jip-Hop and the Jailmakers <https://github.com/Jip-Hop/jailmaker>
#
# SPDX-License-Identifier: LGPL-3.0-only

import sys

# Only set a color if we have an interactive tty
if sys.stdout.isatty():
    BOLD = "\033[1m"
    RED = "\033[91m"
    YELLOW = "\033[93m"
    UNDERLINE = "\033[4m"
    NORMAL = "\033[0m"
else:
    BOLD = RED = YELLOW = UNDERLINE = NORMAL = ""


def eprint(*args, **kwargs):
    """
    Print to stderr.
    """
    print(*args, file=sys.stderr, **kwargs)


def fail(*args, **kwargs):
    """
    Print to stderr and exit.
    """
    eprint(*args, **kwargs)
    sys.exit(1)
