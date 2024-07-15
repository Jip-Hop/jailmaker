# SPDX-FileCopyrightText: © 2024 Jip-Hop and the Jailmakers <https://github.com/Jip-Hop/jailmaker>
#
# SPDX-License-Identifier: LGPL-3.0-only

import os.path
import shlex
import subprocess
import tempfile

from pathlib import Path
from textwrap import dedent
from utils.config_parser import parse_config_file
from utils.console import eprint
from utils.files import stat_chmod
from utils.gpu import passthrough_intel, passthrough_nvidia
from utils.jail_dataset import get_jail_path, jail_is_running
from utils.jail_dataset import get_jail_config_path, get_jail_rootfs_path
from utils.paths import SHORTNAME, JAIL_ROOTFS_NAME


def start_jail(jail_name):
    """
    Start jail with given name.
    """
    skip_start_message = (
        f"Skipped starting jail {jail_name}. It appears to be running already..."
    )

    if jail_is_running(jail_name):
        eprint(skip_start_message)
        return 0

    jail_path = get_jail_path(jail_name)
    jail_config_path = get_jail_config_path(jail_name)
    jail_rootfs_path = get_jail_rootfs_path(jail_name)

    config = parse_config_file(jail_config_path)

    if not config:
        eprint("Aborting...")
        return 1

    seccomp = config.my_getboolean("seccomp")

    systemd_run_additional_args = [
        f"--unit={SHORTNAME}-{jail_name}",
        f"--working-directory={jail_path}",
        f"--description=My nspawn jail {jail_name} [created with jailmaker]",
    ]

    systemd_nspawn_additional_args = [
        f"--machine={jail_name}",
        f"--directory={JAIL_ROOTFS_NAME}",
    ]

    # The systemd-nspawn manual explicitly mentions:
    # Device nodes may not be created
    # https://www.freedesktop.org/software/systemd/man/systemd-nspawn.html
    # This means docker images containing device nodes can't be pulled
    # https://github.com/moby/moby/issues/35245
    #
    # The solution is to use DevicePolicy=auto
    # https://github.com/kinvolk/kube-spawn/pull/328
    #
    # DevicePolicy=auto is the default for systemd-run and allows access to all devices
    # as long as we don't add any --property=DeviceAllow= flags
    # https://manpages.debian.org/bookworm/systemd/systemd.resource-control.5.en.html
    #
    # We can now successfully run:
    # mknod /dev/port c 1 4
    # Or pull docker images containing device nodes:
    # docker pull oraclelinux@sha256:d49469769e4701925d5145c2676d5a10c38c213802cf13270ec3a12c9c84d643

    # Add hooks to execute commands on the host before/after starting and after stopping a jail
    add_hook(
        jail_path,
        systemd_run_additional_args,
        config.my_get("pre_start_hook"),
        "ExecStartPre",
    )

    add_hook(
        jail_path,
        systemd_run_additional_args,
        config.my_get("post_start_hook"),
        "ExecStartPost",
    )

    add_hook(
        jail_path,
        systemd_run_additional_args,
        config.my_get("post_stop_hook"),
        "ExecStopPost",
    )

    gpu_passthrough_intel = config.my_getboolean("gpu_passthrough_intel")
    gpu_passthrough_nvidia = config.my_getboolean("gpu_passthrough_nvidia")

    passthrough_intel(gpu_passthrough_intel, systemd_nspawn_additional_args)
    passthrough_nvidia(
        gpu_passthrough_nvidia, systemd_nspawn_additional_args, jail_name
    )

    if seccomp is False:
        # Disabling seccomp filtering by passing --setenv=SYSTEMD_SECCOMP=0 to systemd-run will improve performance
        # at the expense of security: it allows syscalls which otherwise would be blocked or would have to be explicitly allowed by passing
        # --system-call-filter to systemd-nspawn
        # https://github.com/systemd/systemd/issues/18370
        #
        # However, and additional layer of seccomp filtering may be undesirable
        # For example when using docker to run containers inside the jail created with systemd-nspawn
        # Even though seccomp filtering is disabled for the systemd-nspawn jail itself, docker can still use seccomp filtering
        # to restrict the actions available within its containers
        #
        # Proof that seccomp can be used inside a jail started with --setenv=SYSTEMD_SECCOMP=0:
        # Run a command in a docker container which is blocked by the default docker seccomp profile:
        # 	docker run --rm -it debian:jessie unshare --map-root-user --user sh -c whoami
        # 	unshare: unshare failed: Operation not permitted
        # Now run unconfined to show command runs successfully:
        # 	docker run --rm -it --security-opt seccomp=unconfined debian:jessie unshare --map-root-user --user sh -c whoami
        # 	root

        systemd_run_additional_args += [
            "--setenv=SYSTEMD_SECCOMP=0",
        ]

    initial_setup = False

    # If there's no machine-id, then this the first time the jail is started
    if not os.path.exists(os.path.join(jail_rootfs_path, "etc/machine-id")) and (
        initial_setup := config.my_get("initial_setup")
    ):
        # initial_setup has been assigned due to := expression above
        # Ensure the jail init system is ready before we start the initial_setup
        systemd_nspawn_additional_args += [
            "--notify-ready=yes",
        ]

    cmd = [
        "systemd-run",
        *shlex.split(config.my_get("systemd_run_default_args")),
        *systemd_run_additional_args,
        "--",
        "systemd-nspawn",
        *shlex.split(config.my_get("systemd_nspawn_default_args")),
        *systemd_nspawn_additional_args,
        *shlex.split(config.my_get("systemd_nspawn_user_args")),
    ]

    print(
        dedent(
            f"""
        Starting jail {jail_name} with the following command:

        {shlex.join(cmd)}
    """
        )
    )

    returncode = subprocess.run(cmd).returncode
    if returncode != 0:
        eprint(
            dedent(
                f"""
            Failed to start jail {jail_name}...
            In case of a config error, you may fix it with:
            {COMMAND_NAME} edit {jail_name}
        """
            )
        )

        return returncode

    # Handle initial setup after jail is up and running (for the first time)
    if initial_setup:
        if not initial_setup.startswith("#!"):
            initial_setup = "#!/bin/sh\n" + initial_setup

        with tempfile.NamedTemporaryFile(
            mode="w+t",
            prefix="jlmkr-initial-setup.",
            dir=jail_rootfs_path,
            delete=False,
        ) as initial_setup_file:
            # Write a script file to call during initial setup
            initial_setup_file.write(initial_setup)

        initial_setup_file_name = os.path.basename(initial_setup_file.name)
        initial_setup_file_host_path = os.path.abspath(initial_setup_file.name)
        stat_chmod(initial_setup_file_host_path, 0o700)

        print(f"About to run the initial setup script: {initial_setup_file_name}.")
        print("Waiting for networking in the jail to be ready.")
        print(
            "Please wait (this may take 90s in case of bridge networking with STP is enabled)..."
        )
        returncode = exec_jail(
            jail_name,
            [
                "--",
                "systemd-run",
                f"--unit={initial_setup_file_name}",
                "--quiet",
                "--pipe",
                "--wait",
                "--service-type=exec",
                "--property=After=network-online.target",
                "--property=Wants=network-online.target",
                "/" + initial_setup_file_name,
            ],
        )

        if returncode != 0:
            eprint("Tried to run the following commands inside the jail:")
            eprint(initial_setup)
            eprint()
            eprint(f"{RED}{BOLD}Failed to run initial setup...")
            eprint(
                f"You may want to manually run /{initial_setup_file_name} inside the jail for debugging purposes."
            )
            eprint(f"Or stop and remove the jail and try again.{NORMAL}")
            return returncode
        else:
            # Cleanup the initial_setup_file_host_path
            Path(initial_setup_file_host_path).unlink(missing_ok=True)
            print(f"Done with initial setup of jail {jail_name}!")

    return returncode


def add_hook(jail_path, systemd_run_additional_args, hook_command, hook_type):
    if not hook_command:
        return

    # Run the command directly if it doesn't start with a shebang
    if not hook_command.startswith("#!"):
        systemd_run_additional_args += [f"--property={hook_type}={hook_command}"]
        return

    # Otherwise write a script file and call that
    hook_file = os.path.abspath(os.path.join(jail_path, f".{hook_type}"))

    # Only write if contents are different
    if not os.path.exists(hook_file) or Path(hook_file).read_text() != hook_command:
        print(hook_command, file=open(hook_file, "w"))

    stat_chmod(hook_file, 0o700)
    systemd_run_additional_args += [
        f"--property={hook_type}={systemd_escape_path(hook_file)}"
    ]


def systemd_escape_path(path):
    """
    Escape path containing spaces, while properly handling backslashes in filenames.
    https://manpages.debian.org/bookworm/systemd/systemd.syntax.7.en.html#QUOTING
    https://manpages.debian.org/bookworm/systemd/systemd.service.5.en.html#COMMAND_LINES
    """
    return "".join(
        map(
            lambda char: r"\s" if char == " " else "\\\\" if char == "\\" else char,
            path,
        )
    )
