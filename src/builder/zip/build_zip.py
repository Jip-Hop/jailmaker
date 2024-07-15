# SPDX-FileCopyrightText: © 2024 Jip-Hop and the Jailmakers <https://github.com/Jip-Hop/jailmaker>
#
# SPDX-License-Identifier: LGPL-3.0-only

# hat tip: <https://github.com/dairiki/hatch-zipped-directory/blob/master/hatch_zipped_directory/builder.py>

import os
from hatchling.builders.config import BuilderConfig
from hatchling.builders.plugin.interface import BuilderInterface
from hatchling.builders.plugin.interface import IncludedFile
from hatchling.builders.utils import normalize_relative_path
from pathlib import Path
from typing import Any, Callable, Iterable
from zipfile import ZipFile, ZIP_DEFLATED


class AppZipBuilderConfig(BuilderConfig): pass

class AppZipBuilder(BuilderInterface):
    PLUGIN_NAME = "appzip"

    @classmethod
    def get_config_class(cls):
        return AppZipBuilderConfig

    def get_version_api(self) -> dict[str, Callable[..., str]]:
        return {'standard': self.build_standard}

    def clean(self, directory: str, versions: Iterable[str]) -> None:
        for filename in os.listdir(directory):
            if filename.startswith('jlmkr-') and filename.endswith('.zip'):
                os.remove(Path(directory, filename))

    def build_standard(self, directory: str, **build_data: Any) -> str:
        outpath = Path(directory, f'jlmkr-{self.metadata.version}.zip')
        with ZipFile(outpath, 'w') as zip:
            zip.write(Path(directory, 'jlmkr'), 'jlmkr')
            force_map = build_data['force_include']
            for included_file in self.recurse_forced_files(force_map):
                zip.write(
                    included_file.relative_path,
                    included_file.distribution_path,
                    ZIP_DEFLATED)
        return os.fspath(outpath)

    def get_default_build_data(self) -> dict[str, Any]:
        build_data: dict[str, Any] = super().get_default_build_data()

        extra_files = []
        if self.metadata.core.readme_path:
            extra_files.append(self.metadata.core.readme_path)
        if self.metadata.core.license_files:
            extra_files.extend(self.metadata.core.license_files)

        force_include = build_data.setdefault("force_include", {})
        for fn in map(normalize_relative_path, extra_files):
            force_include[os.path.join(self.root, fn)] = Path(fn).name
        build_data['force_include'] = force_include

        return build_data
