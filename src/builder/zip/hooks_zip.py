# SPDX-FileCopyrightText: © 2024 Jip-Hop and the Jailmakers <https://github.com/Jip-Hop/jailmaker>
#
# SPDX-License-Identifier: LGPL-3.0-only

from hatchling.plugin import hookimpl

from build_zip import AppZipBuilder

@hookimpl
def hatch_register_builder():
    return AppZipBuilder
