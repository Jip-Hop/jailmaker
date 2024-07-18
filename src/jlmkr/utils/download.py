# SPDX-FileCopyrightText: © 2024 Jip-Hop and the Jailmakers <https://github.com/Jip-Hop/jailmaker>
#
# SPDX-License-Identifier: LGPL-3.0-only

import hashlib
import os
import re
import subprocess
import urllib.request

from utils.console import eprint
from utils.files import stat_chmod

DOWNLOAD_SCRIPT_DIGEST = (
    "645ba65a8846a2f402fc8bd870029b95fbcd3128e3046cd55642d577652cb0a0"
)


def run_lxc_download_script(
    jail_name=None, jail_path=None, jail_rootfs_path=None, distro=None, release=None
):
    arch = "amd64"
    lxc_dir = ".lxc"
    lxc_cache = os.path.join(lxc_dir, "cache")
    lxc_download_script = os.path.join(lxc_dir, "lxc-download.sh")

    # Create the lxc dirs if nonexistent
    os.makedirs(lxc_dir, exist_ok=True)
    stat_chmod(lxc_dir, 0o700)
    os.makedirs(lxc_cache, exist_ok=True)
    stat_chmod(lxc_cache, 0o700)

    try:
        if os.stat(lxc_download_script).st_uid != 0:
            os.remove(lxc_download_script)
    except FileNotFoundError:
        pass

    # Fetch the lxc download script if not present locally (or hash doesn't match)
    if not validate_sha256(lxc_download_script, DOWNLOAD_SCRIPT_DIGEST):
        urllib.request.urlretrieve(
            "https://raw.githubusercontent.com/Jip-Hop/lxc/b24d2d45b3875b013131b480e61c93b6fb8ea70c/templates/lxc-download.in",
            lxc_download_script,
        )

        if not validate_sha256(lxc_download_script, DOWNLOAD_SCRIPT_DIGEST):
            eprint("Abort! Downloaded script has unexpected contents.")
            return 1

    stat_chmod(lxc_download_script, 0o700)

    if None not in [jail_name, jail_path, jail_rootfs_path, distro, release]:
        cmd = [
            lxc_download_script,
            f"--name={jail_name}",
            f"--path={jail_path}",
            f"--rootfs={jail_rootfs_path}",
            f"--arch={arch}",
            f"--dist={distro}",
            f"--release={release}",
        ]

        if rc := subprocess.run(cmd, env={"LXC_CACHE_PATH": lxc_cache}).returncode != 0:
            eprint("Aborting...")
            return rc

    else:
        # List images
        cmd = [lxc_download_script, "--list", f"--arch={arch}"]

        p1 = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, env={"LXC_CACHE_PATH": lxc_cache}
        )

        for line in iter(p1.stdout.readline, b""):
            line = line.decode().strip()
            # Filter out the known incompatible distros
            if not re.match(
                r"^(alpine|amazonlinux|busybox|devuan|funtoo|openwrt|plamo|voidlinux)\s",
                line,
            ):
                # TODO: check if output matches expected output, if it does then return 0
                # Else treat this as an error and return 1
                print(line)

        return p1.wait()

    return 0


def validate_sha256(file_path, digest):
    """
    Validates if a file matches a sha256 digest.
    """
    try:
        with open(file_path, "rb") as f:
            file_hash = hashlib.sha256(f.read()).hexdigest()
            return file_hash == digest
    except FileNotFoundError:
        return False
