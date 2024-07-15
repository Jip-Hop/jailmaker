# SPDX-FileCopyrightText: © 2024 Jip-Hop and the Jailmakers <https://github.com/Jip-Hop/jailmaker>
#
# SPDX-License-Identifier: LGPL-3.0-only

import os
from io import BytesIO
from pathlib import Path
from typing import Any, Callable, Iterable
from zipapp import create_archive

from hatchling.builders.plugin.interface import BuilderInterface


class ZipAppBuilder(BuilderInterface):
    PLUGIN_NAME = "zipapp"

    def get_version_api(self) -> dict[str, Callable[..., str]]:
        return {"standard": self.build_standard}

    def clean(self, directory: str, versions: Iterable[str]) -> None:
        try:
            os.remove(Path(directory, 'jlmkr'))
        except:
            pass

    def build_standard(self, directory: str, **build_data: Any) -> str:

        # generate zipapp source archive
        pyzbuffer = BytesIO()
        create_archive('src/jlmkr', target=pyzbuffer,
                interpreter='=PLACEHOLDER=',
#                 main='donor.jlmkr:main',
                compressed=True)
        zipdata = pyzbuffer.getvalue() #.removeprefix(b"#!=PLACEHOLDER=\n")

        # output with preamble
        outpath = Path(directory, 'jlmkr')
        with open(outpath, 'wb') as f:
            f.write(preamble(self.metadata.version).encode())
            f.write(zipdata)
        os.chmod(outpath, 0o755)
        return os.fspath(outpath)


# 10 lines will conveniently match the default of head(1)
def preamble(version): return f'''#!/usr/bin/env python3

jlmkr {version}

Persistent Linux 'jails' on TrueNAS SCALE to install software (k3s, docker, portainer, podman, etc.) with full access to all files via bind mounts.

SPDX-FileCopyrightText: © 2024 Jip-Hop and the Jailmakers <https://github.com/Jip-Hop/jailmaker>
SPDX-License-Identifier: LGPL-3.0-only

-=-=-=- this is a zip file -=-=-=- what follows is binary -=-=-=-
'''
