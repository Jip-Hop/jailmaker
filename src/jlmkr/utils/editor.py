# SPDX-FileCopyrightText: © 2024 Jip-Hop and the Jailmakers <https://github.com/Jip-Hop/jailmaker>
#
# SPDX-License-Identifier: LGPL-3.0-only

import os
import shutil


def get_text_editor():
    def get_from_environ(key):
        if editor := os.environ.get(key):
            return shutil.which(editor)

    return (
        get_from_environ("VISUAL")
        or get_from_environ("EDITOR")
        or shutil.which("editor")
        or shutil.which("/usr/bin/editor")
        or "nano"
    )
