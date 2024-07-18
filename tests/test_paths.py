# SPDX-FileCopyrightText: © 2024 Jip-Hop and the Jailmakers <https://github.com/Jip-Hop/jailmaker>
#
# SPDX-License-Identifier: LGPL-3.0-only

from jlmkr import paths


def test_script_name():
    assert paths.SHORTNAME == 'jlmkr'
