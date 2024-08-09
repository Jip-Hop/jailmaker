# SPDX-FileCopyrightText: © 2024 Jip-Hop and the Jailmakers <https://github.com/Jip-Hop/jailmaker>
#
# SPDX-License-Identifier: LGPL-3.0-only

from utils import editor

from pathlib import Path


def test_editor_executable():
    e = editor.get_text_editor()
    path = Path(e).resolve()
    print(path)
    assert path.is_file()
    assert path.stat().st_mode & 0o7777 == 0o755
