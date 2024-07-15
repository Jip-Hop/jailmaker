#!/usr/bin/env python3

"""Create persistent Linux 'jails' on TrueNAS SCALE, \
with full access to all files via bind mounts, \
thanks to systemd-nspawn!"""

__version__ = "3.0.0"
__author__ = "Jip-Hop"
__copyright__ = "Copyright (C) 2023, Jip-Hop"
__license__ = "LGPL-3.0-only"
__disclaimer__ = """USE THIS SCRIPT AT YOUR OWN RISK!
IT COMES WITHOUT WARRANTY AND IS NOT SUPPORTED BY IXSYSTEMS."""

import argparse
import contextlib
import hashlib
import json
import os
import platform
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path, PurePath
from textwrap import dedent


# Use mostly default settings for systemd-nspawn but with systemd-run instead of a service file:
# https://github.com/systemd/systemd/blob/main/units/systemd-nspawn%40.service.in
# Use TasksMax=infinity since this is what docker does:
# https://github.com/docker/engine/blob/master/contrib/init/systemd/docker.service

# Use SYSTEMD_NSPAWN_LOCK=0: otherwise jail won't start jail after a shutdown (but why?)
# Would give "directory tree currently busy" error and I'd have to run
# `rm /run/systemd/nspawn/locks/*` and remove the .lck file from jail_path
# Disabling locking isn't a big deal as systemd-nspawn will prevent starting a container
# with the same name anyway: as long as we're starting jails using this script,
# it won't be possible to start the same jail twice

# Always add --bind-ro=/sys/module to make lsmod happy
# https://manpages.debian.org/bookworm/manpages/sysfs.5.en.html

from utils.paths import SCRIPT_PATH, SCRIPT_NAME, SCRIPT_DIR_PATH
from utils.paths import JAILS_DIR_PATH, JAIL_CONFIG_NAME, JAIL_ROOTFS_NAME
from utils.paths import COMMAND_NAME, SHORTNAME
from utils.console import BOLD, RED, YELLOW, UNDERLINE, NORMAL

DISCLAIMER = f"""{YELLOW}{BOLD}{__disclaimer__}{NORMAL}"""

from utils.config_parser import ExceptionWithParser, KeyValueParser
from utils.config_parser import parse_config_file


# Workaround for exit_on_error=False not applying to:
# "error: the following arguments are required"
# https://github.com/python/cpython/issues/103498
class CustomSubParser(argparse.ArgumentParser):
    def error(self, message):
        if self.exit_on_error:
            super().error(message)
        else:
            raise ExceptionWithParser(self, message)


from utils.chroot import Chroot
from utils.console import eprint, fail
from utils.dataset import check_jail_name_valid, check_jail_name_available
from utils.dataset import get_jail_path, get_jail_config_path, get_jail_rootfs_path

from actions.exec import exec_jail
from actions.status import status_jail
from actions.log import log_jail
from actions.shell import shell_jail
from actions.start import start_jail
from actions.restart import restart_jail
from actions.images import run_lxc_download_script

from utils.dataset import cleanup, check_jail_name_valid, check_jail_name_available
from utils.download import run_lxc_download_script
from utils.files import stat_chmod
from utils.dataset import get_zfs_dataset, create_zfs_dataset, remove_zfs_dataset

from actions.create import create_jail
from utils.editor import get_text_editor
from utils.dataset import jail_is_running

from actions.edit import edit_jail
from actions.stop import stop_jail
from actions.remove import remove_jail

from utils.dataset import get_all_jail_names, parse_os_release
from actions.list import list_jails
from actions.startup import startup_jails


def split_at_string(lst, string):
    try:
        index = lst.index(string)
        return lst[:index], lst[index + 1 :]
    except ValueError:
        return lst, []


def add_parser(subparser, **kwargs):
    if kwargs.get("add_help") is False:
        # Don't add help if explicitly disabled
        add_help = False
    else:
        # Never add help with the built in add_help
        kwargs["add_help"] = False
        add_help = True

    kwargs["epilog"] = DISCLAIMER
    kwargs["formatter_class"] = argparse.RawDescriptionHelpFormatter
    kwargs["exit_on_error"] = False
    func = kwargs.pop("func")
    parser = subparser.add_parser(**kwargs)
    parser.set_defaults(func=func)

    if add_help:
        parser.add_argument(
            "-h", "--help", help="show this help message and exit", action="store_true"
        )

    # Setting the add_help after the parser has been created with add_parser has no effect,
    # but it allows us to look up if this parser has a help message available
    parser.add_help = add_help

    return parser


def main():
    if os.stat(SCRIPT_PATH).st_uid != 0:
      if os.environ.get('JLMKR_DEBUG') is not None:
        fail(
            f"This script should be owned by the root user... Fix it manually with: `chown root {SCRIPT_PATH}`."
        )

    parser = argparse.ArgumentParser(
        description=__doc__,
        allow_abbrev=False,
        epilog=f"For more info on some command, run: {COMMAND_NAME} some_command --help.\n{DISCLAIMER}",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument("--version", action="version", version=__version__)

    subparsers = parser.add_subparsers(
        title="commands", dest="command", metavar="", parser_class=CustomSubParser
    )

    split_commands = ["create", "exec", "log", "status"]
    commands = {}

    for d in [
        dict(
            name="create",  #
            help="create a new jail",
            func=create_jail,
        ),
        dict(
            name="edit",
            help=f"edit jail config with {get_text_editor()} text editor",
            func=edit_jail,
        ),
        dict(
            name="exec",  #
            help="execute a command in the jail",
            func=exec_jail,
        ),
        dict(
            name="images",
            help="list available images to create jails from",
            func=run_lxc_download_script,
        ),
        dict(
            name="list",  #
            help="list jails",
            func=list_jails,
        ),
        dict(
            name="log",  #
            help="show jail log",
            func=log_jail,
        ),
        dict(
            name="remove",  #
            help="remove previously created jail",
            func=remove_jail,
        ),
        dict(
            name="restart",  #
            help="restart a running jail",
            func=restart_jail,
        ),
        dict(
            name="shell",
            help="open shell in running jail (alias for machinectl shell)",
            func=shell_jail,
            add_help=False,
        ),
        dict(
            name="start",  #
            help="start previously created jail",
            func=start_jail,
        ),
        dict(
            name="startup",
            help="startup selected jails",
            func=startup_jails,
        ),
        dict(
            name="status",  #
            help="show jail status",
            func=status_jail,
        ),
        dict(
            name="stop",  #
            help="stop a running jail",
            func=stop_jail,
        ),
    ]:
        commands[d["name"]] = add_parser(subparsers, **d)

    for cmd in [
        "create",
        "edit",
        "exec",
        "log",
        "remove",
        "restart",
        "start",
        "status",
        "stop",
    ]:
        commands[cmd].add_argument("jail_name", help="name of the jail")

    commands["exec"].add_argument(
        "cmd",
        nargs="*",
        help="command to execute",
    )

    commands["shell"].add_argument(
        "args",
        nargs="*",
        help="args to pass to machinectl shell",
    )

    commands["log"].add_argument(
        "args",
        nargs="*",
        help="args to pass to journalctl",
    )

    commands["status"].add_argument(
        "args",
        nargs="*",
        help="args to pass to systemctl",
    )

    commands["create"].add_argument(
        "--distro", metavar="X", help="desired DIST from the images list"
    )
    commands["create"].add_argument(
        "--release", metavar="X", help="desired RELEASE from the images list"
    )
    commands["create"].add_argument(
        "--start",  #
        help="start jail after create",
        action="store_true",
    )
    commands["create"].add_argument(
        "--startup",
        type=int,
        choices=[0, 1],
        help=f"start this jail when running: {SCRIPT_NAME} startup",
    )
    commands["create"].add_argument(
        "--seccomp",  #
        type=int,
        choices=[0, 1],
        help="turning off seccomp filtering improves performance at the expense of security",
    )
    commands["create"].add_argument(
        "-c",  #
        "--config",
        metavar="X",
        help="path to config file template or - for stdin",
    )
    commands["create"].add_argument(
        "-gi",  #
        "--gpu_passthrough_intel",
        type=int,
        choices=[0, 1],
    )
    commands["create"].add_argument(
        "-gn",  #
        "--gpu_passthrough_nvidia",
        type=int,
        choices=[0, 1],
    )
    commands["create"].add_argument(
        "systemd_nspawn_user_args",
        metavar="nspawn_args",
        nargs="*",
        help="add additional systemd-nspawn flags",
    )

    if os.getuid() != 0:
        parser.print_help()
        fail("Run this script as root...")

    # Set appropriate permissions (if not already set) for this file, since it's executed as root
    stat_chmod(SCRIPT_PATH, 0o700)

    # Ignore all args after the first "--"
    args_to_parse = split_at_string(sys.argv[1:], "--")[0]
    # Check for help
    if any(item in args_to_parse for item in ["-h", "--help"]):
        # Likely we need to show help output...
        try:
            args = vars(parser.parse_known_args(args_to_parse)[0])
            # We've exited by now if not invoking a subparser: jlmkr.py --help
            if args.get("help"):
                need_help = True
                command = args.get("command")

                # Edge case for some commands
                if command in split_commands and args["jail_name"]:
                    # Ignore all args after the jail name
                    args_to_parse = split_at_string(args_to_parse, args["jail_name"])[0]
                    # Add back the jail_name as it may be a required positional and we
                    # don't want to end up in the except clause below
                    args_to_parse += [args["jail_name"]]
                    # Parse one more time...
                    args = vars(parser.parse_known_args(args_to_parse)[0])
                    # ...and check if help is still in the remaining args
                    need_help = args.get("help")

                if need_help:
                    commands[command].print_help()
                    sys.exit()
        except ExceptionWithParser as e:
            # Print help output on error, e.g. due to:
            # "error: the following arguments are required"
            if e.parser.add_help:
                e.parser.print_help()
                sys.exit()

    # Exit on parse errors (e.g. missing positional args)
    for command in commands:
        commands[command].exit_on_error = True

    # Parse to find command and function and ignore unknown args which may be present
    # such as args intended to pass through to systemd-run
    args = vars(parser.parse_known_args()[0])
    command = args.pop("command", None)

    # Start over with original args
    args_to_parse = sys.argv[1:]

    if not command:
        # Parse args and show error for unknown args
        parser.parse_args(args_to_parse)
        parser.print_help()
        sys.exit()

    elif command == "shell":
        # Pass anything after the "shell" command to machinectl
        _, shell_args = split_at_string(args_to_parse, command)
        sys.exit(args["func"](shell_args))
    elif command in split_commands and args["jail_name"]:
        jlmkr_args, remaining_args = split_at_string(args_to_parse, args["jail_name"])
        if remaining_args and remaining_args[0] != "--":
            # Add "--" after the jail name to ensure further args, e.g.
            # --help or --version, are captured as systemd_nspawn_user_args
            args_to_parse = jlmkr_args + [args["jail_name"], "--"] + remaining_args

    # Parse args again, but show error for unknown args
    args = vars(parser.parse_args(args_to_parse))
    # Clean the args
    args.pop("help")
    args.pop("command", None)
    func = args.pop("func")
    sys.exit(func(**args))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
