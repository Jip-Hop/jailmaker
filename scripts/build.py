# SPDX-FileCopyrightText: © 2024 Jip-Hop and the Jailmakers <https://github.com/Jip-Hop/jailmaker>
#
# SPDX-License-Identifier: LGPL-3.0-only

# hat tip: <https://github.com/dairiki/hatch-zipped-directory/blob/master/hatch_zipped_directory/builder.py>

import os
import sys
from io import BytesIO
from pathlib import Path
from typing import Any, Callable, Iterable
from zipapp import create_archive
from zipfile import ZipFile, ZIP_DEFLATED

from src.jlmkr.__main__ import __version__ as VERSION

PROJECT_PATH = Path.cwd()
SRC_PATH = Path('./src/jlmkr')
DIST_PATH = Path('./dist')

# 10 lines will conveniently match the default of head(1)
PREAMBLE = f'''#!/usr/bin/env python3

jlmkr {VERSION}

Persistent Linux 'jails' on TrueNAS SCALE to install software (k3s, docker, portainer, podman, etc.) with full access to all files via bind mounts.

SPDX-FileCopyrightText: © 2024 Jip-Hop and the Jailmakers <https://github.com/Jip-Hop/jailmaker>
SPDX-License-Identifier: LGPL-3.0-only

-=-=-=- this is a zip file -=-=-=- what follows is binary -=-=-=-
'''


def build_tool() -> Path:

    # generate zipapp source archive
    pyzbuffer = BytesIO()
    create_archive(SRC_PATH, target=pyzbuffer,
            interpreter='=PLACEHOLDER=',
            compressed=True)
    zipdata = pyzbuffer.getvalue().removeprefix(b"#!=PLACEHOLDER=\n")

    # output with preamble
    tool_path = DIST_PATH.joinpath('jlmkr')
    with open(tool_path, 'wb') as f:
        f.write(PREAMBLE.encode())
        f.write(zipdata)
    os.chmod(tool_path, 0o755)
    return tool_path


def build_zip() -> Path:
    zip_path = DIST_PATH.joinpath(f'jlmkr-{VERSION}.zip')
    tool_path = DIST_PATH.joinpath('jlmkr')
    attachments = ['README.md', 'LICENSE']

    # include the tool as-is (with the uncompressed preamble),
    # then compress and attach other hangers-on
    with ZipFile(zip_path, 'w') as zip:
        zip.write(tool_path)
        for attachment in attachments:
            path = PROJECT_PATH.joinpath(attachment)
            zip.write(path, compress_type=ZIP_DEFLATED)
    return zip_path


if __name__ == '__main__':
    DIST_PATH.mkdir(exist_ok=True)
    print(build_tool())
    print(build_zip())
