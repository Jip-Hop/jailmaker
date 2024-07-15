# SPDX-FileCopyrightText: © 2024 Jip-Hop and the Jailmakers <https://github.com/Jip-Hop/jailmaker>
#
# SPDX-License-Identifier: LGPL-3.0-only

import os


class Chroot:
    def __init__(self, new_root):
        self.new_root = new_root
        self.old_root = None
        self.initial_cwd = None

    def __enter__(self):
        self.old_root = os.open("/", os.O_PATH)
        self.initial_cwd = os.path.abspath(os.getcwd())
        os.chdir(self.new_root)
        os.chroot(".")

    def __exit__(self, exc_type, exc_value, traceback):
        os.chdir(self.old_root)
        os.chroot(".")
        os.close(self.old_root)
        os.chdir(self.initial_cwd)
