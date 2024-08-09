#!/usr/bin/env python3
# SPDX-FileCopyrightText: © 2024 Jip-Hop and the Jailmakers <https://github.com/Jip-Hop/jailmaker>
#
# SPDX-License-Identifier: LGPL-3.0-only

import os
import sys

from contextlib import AbstractContextManager, chdir
from pathlib import Path
from subprocess import run, PIPE, STDOUT, CalledProcessError
from tempfile import NamedTemporaryFile, TemporaryDirectory

SUDO = '/usr/bin/sudo'
ZPOOL = '/sbin/zpool'
ZFS = '/sbin/zfs'


class TemporaryPool(AbstractContextManager):
    vdev: NamedTemporaryFile
    mountpoint: Path
    name: str

    def __init__(self, bytesize: int):
        self.vdisk = NamedTemporaryFile()
        self.vdisk.truncate(bytesize)
        self._tmpdir = TemporaryDirectory()
        self.mountpoint = Path(self._tmpdir.name)
        self.name = self.mountpoint.name

    def __enter__(self):
        run([SUDO, ZPOOL, 'create',
                '-m', self.mountpoint,
                self.name, self.vdisk.name], check=False)
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        run([SUDO, ZPOOL, 'destroy', self.name], check=False)


class JailmakerDataset(AbstractContextManager):
    name: str
    path: Path

    def __init__(self, pool: TemporaryPool):
        self.name = f'{pool.name}/jailmaker'
        self.path = pool.mountpoint.joinpath('jailmaker')

    def __enter__(self):
        run([SUDO, ZFS, 'create', self.name], check=False)
        run([SUDO, '/usr/bin/cp', 'dist/jlmkr', self.path], check=False)
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        run([SUDO, ZFS, 'destroy', '-r', self.name], check=False)


def run_test(path):
    with (
        TemporaryPool(512*1024*1024) as pool,
        JailmakerDataset(pool) as dataset,
    ):
        print(f'▶️  {path.name} ...')
        environment = {
            **os.environ,
            'JAILMAKER_DIR': dataset.path,
            'TEMPLATES': Path('templates').resolve(True),
        }
        result = run([path], env=environment,
            capture_output=False, #stdout=PIPE, stderr=STDOUT,
            cwd=dataset.path, check=False)
        if result.returncode == 0:
            print(f'✅  {path.name} completed OK')
        else:
            if result.stdout:
                print(result.stdout.decode())
            print(f'❌  {path.name} returned {result.returncode}')
        result.check_returncode()


if __name__ == '__main__':
    jlmkr = Path('dist/jlmkr')
    if not jlmkr.is_file():
        raise(Exception('build jlmkr first'))
    testdir = Path(__file__).parent

    succeeded = 0
    failed = 0
    for testscript in testdir.iterdir():
        if testscript.name.startswith('test_'):
            try:
                run_test(testscript)
                succeeded += 1
            except CalledProcessError:
                failed += 1
    print()
    if failed:
        print(f'❌  {failed} of {failed+succeeded} tests FAILED')
        sys.exit(-1)
    else:
        print(f'✅  All {succeeded} tests OK')
        sys.exit(0)
