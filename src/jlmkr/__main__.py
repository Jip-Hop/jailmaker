#!/usr/bin/env python3
# SPDX-FileCopyrightText: © 2024 Jip-Hop and the Jailmakers <https://github.com/Jip-Hop/jailmaker>
#
# SPDX-License-Identifier: LGPL-3.0-only

import donor
import sys

if __name__ == "__main__":
    try:
        sys.exit(donor.main())
    except KeyboardInterrupt:
        sys.exit(130)
