# SPDX-FileCopyrightText: © 2024 Jip-Hop and the Jailmakers <https://github.com/Jip-Hop/jailmaker>
#
# SPDX-License-Identifier: LGPL-3.0-only

import argparse
import os
import sys

from actions.create import create_jail
from actions.edit import edit_jail
from actions.exec import exec_jail
from actions.images import run_lxc_download_script
from actions.list import list_jails
from actions.log import log_jail
from actions.remove import remove_jail
from actions.restart import restart_jail
from actions.shell import shell_jail
from actions.start import start_jail
from actions.startup import startup_jails
from actions.status import status_jail
from actions.stop import stop_jail
from data import DISCLAIMER
from paths import COMMAND_NAME, SCRIPT_NAME, SCRIPT_PATH
from utils.config_parser import ExceptionWithParser
from utils.console import fail
from utils.editor import get_text_editor
from utils.files import stat_chmod

from __main__ import __version__


def main():
    if os.stat(SCRIPT_PATH).st_uid != 0:
        if os.environ.get("JLMKR_DEBUG") is None:
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


# Workaround for exit_on_error=False not applying to:
# "error: the following arguments are required"
# https://github.com/python/cpython/issues/103498
class CustomSubParser(argparse.ArgumentParser):
    def error(self, message):
        if self.exit_on_error:
            super().error(message)
        else:
            raise ExceptionWithParser(self, message)


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


def split_at_string(lst, string):
    try:
        index = lst.index(string)
        return lst[:index], lst[index + 1 :]
    except ValueError:
        return lst, []
