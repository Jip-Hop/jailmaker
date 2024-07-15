# SPDX-FileCopyrightText: © 2024 Jip-Hop and the Jailmakers <https://github.com/Jip-Hop/jailmaker>
#
# SPDX-License-Identifier: LGPL-3.0-only

import os.path
import subprocess

from pathlib import Path
from textwrap import dedent
from utils.console import eprint
from utils.jail_dataset import get_jail_rootfs_path
from utils.paths import SHORTNAME


# Test intel GPU by decoding mp4 file (output is discarded)
# Run the commands below in the jail:
# curl -o bunny.mp4 https://www.w3schools.com/html/mov_bbb.mp4
# ffmpeg -hwaccel vaapi -hwaccel_device /dev/dri/renderD128 -hwaccel_output_format vaapi -i bunny.mp4 -f null - && echo 'SUCCESS!'


def passthrough_intel(gpu_passthrough_intel, systemd_nspawn_additional_args):
    if not gpu_passthrough_intel:
        return

    if not os.path.exists("/dev/dri"):
        eprint(
            dedent(
                """
        No intel GPU seems to be present...
        Skip passthrough of intel GPU."""
            )
        )
        return

    systemd_nspawn_additional_args.append("--bind=/dev/dri")


def passthrough_nvidia(
    gpu_passthrough_nvidia, systemd_nspawn_additional_args, jail_name
):
    jail_rootfs_path = get_jail_rootfs_path(jail_name)
    ld_so_conf_path = Path(
        os.path.join(jail_rootfs_path), f"etc/ld.so.conf.d/{SHORTNAME}-nvidia.conf"
    )

    if not gpu_passthrough_nvidia:
        # Cleanup the config file we made when passthrough was enabled
        ld_so_conf_path.unlink(missing_ok=True)
        return

    # Load the nvidia kernel module
    if subprocess.run(["modprobe", "nvidia-current-uvm"]).returncode != 0:
        eprint(
            dedent(
                """
            Failed to load nvidia-current-uvm kernel module."""
            )
        )

    # Run nvidia-smi to initialize the nvidia driver
    # If we can't run nvidia-smi successfully,
    # then nvidia-container-cli list will fail too:
    # we shouldn't continue with gpu passthrough
    if subprocess.run(["nvidia-smi", "-f", "/dev/null"]).returncode != 0:
        eprint("Skip passthrough of nvidia GPU.")
        return

    try:
        # Get list of libraries
        nvidia_libraries = set(
            [
                x
                for x in subprocess.check_output(
                    ["nvidia-container-cli", "list", "--libraries"]
                )
                .decode()
                .split("\n")
                if x
            ]
        )
        # Get full list of files, but excluding library ones from above
        nvidia_files = set(
            (
                [
                    x
                    for x in subprocess.check_output(["nvidia-container-cli", "list"])
                    .decode()
                    .split("\n")
                    if x and x not in nvidia_libraries
                ]
            )
        )
    except Exception:
        eprint(
            dedent(
                """
        Unable to detect which nvidia driver files to mount.
        Skip passthrough of nvidia GPU."""
            )
        )
        return

    # Also make nvidia-smi available inside the path,
    # while mounting the symlink will be resolved and nvidia-smi will appear as a regular file
    nvidia_files.add("/usr/bin/nvidia-smi")

    nvidia_mounts = []

    for file_path in nvidia_files:
        if not os.path.exists(file_path):
            # Don't try to mount files not present on the host
            print(f"Skipped mounting {file_path}, it doesn't exist on the host...")
            continue

        if file_path.startswith("/dev/"):
            nvidia_mounts.append(f"--bind={file_path}")
        else:
            nvidia_mounts.append(f"--bind-ro={file_path}")

    # Check if the parent dir exists where we want to write our conf file
    if ld_so_conf_path.parent.exists():
        library_folders = set(str(Path(x).parent) for x in nvidia_libraries)
        # Add the library folders as mounts
        for lf in library_folders:
            nvidia_mounts.append(f"--bind-ro={lf}")

        # Only write if the conf file doesn't yet exist or has different contents
        existing_conf_libraries = set()
        if ld_so_conf_path.exists():
            existing_conf_libraries.update(
                x for x in ld_so_conf_path.read_text().splitlines() if x
            )

        if library_folders != existing_conf_libraries:
            print("\n".join(x for x in library_folders), file=ld_so_conf_path.open("w"))

            # Run ldconfig inside systemd-nspawn jail with nvidia mounts...
            subprocess.run(
                [
                    "systemd-nspawn",
                    "--quiet",
                    f"--machine={jail_name}",
                    f"--directory={jail_rootfs_path}",
                    *nvidia_mounts,
                    "ldconfig",
                ]
            )
    else:
        eprint(
            dedent(
                """
            Unable to write the ld.so.conf.d directory inside the jail (it doesn't exist).
            Skipping call to ldconfig.
            The nvidia drivers will probably not be detected..."""
            )
        )

    systemd_nspawn_additional_args += nvidia_mounts
