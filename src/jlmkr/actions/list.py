# SPDX-FileCopyrightText: © 2024 Jip-Hop and the Jailmakers <https://github.com/Jip-Hop/jailmaker>
#
# SPDX-License-Identifier: LGPL-3.0-only

import json
import subprocess

from collections import defaultdict
from utils.console import NORMAL, UNDERLINE
from utils.config_parser import parse_config_file
from utils.jail_dataset import get_all_jail_names, get_jail_config_path, get_jail_rootfs_path, parse_os_release


def list_jails():
    """
    List all available and running jails.
    """

    jails = {}
    empty_value_indicator = "-"

    jail_names = get_all_jail_names()

    if not jail_names:
        print("No jails.")
        return 0

    # Get running jails from machinectl
    running_machines = run_command_and_parse_json(["machinectl", "list", "-o", "json"])
    # Index running_machines by machine name
    # We're only interested in systemd-nspawn machines
    running_machines = {
        item["machine"]: item
        for item in running_machines
        if item["service"] == "systemd-nspawn"
    }

    for jail_name in jail_names:
        jail_rootfs_path = get_jail_rootfs_path(jail_name)
        jails[jail_name] = {"name": jail_name, "running": False}
        jail = jails[jail_name]

        config = parse_config_file(get_jail_config_path(jail_name))
        if config:
            jail["startup"] = config.my_getboolean("startup")
            jail["gpu_intel"] = config.my_getboolean("gpu_passthrough_intel")
            jail["gpu_nvidia"] = config.my_getboolean("gpu_passthrough_nvidia")

        if jail_name in running_machines:
            machine = running_machines[jail_name]
            # Augment the jails dict with output from machinectl
            jail["running"] = True
            jail["os"] = machine["os"] or None
            jail["version"] = machine["version"] or None

            addresses = machine.get("addresses")
            if not addresses:
                jail["addresses"] = empty_value_indicator
            else:
                addresses = addresses.split("\n")
                jail["addresses"] = addresses[0]
                if len(addresses) > 1:
                    jail["addresses"] += "…"
        else:
            # Parse os-release info ourselves
            jail_platform = parse_os_release(jail_rootfs_path)
            jail["os"] = jail_platform.get("ID")
            jail["version"] = jail_platform.get("VERSION_ID") or jail_platform.get(
                "VERSION_CODENAME"
            )

    print_table(
        [
            "name",
            "running",
            "startup",
            "gpu_intel",
            "gpu_nvidia",
            "os",
            "version",
            "addresses",
        ],
        sorted(jails.values(), key=lambda x: x["name"]),
        empty_value_indicator,
    )

    return 0


def run_command_and_parse_json(command):
    result = subprocess.run(command, capture_output=True, text=True)
    output = result.stdout.strip()

    try:
        parsed_output = json.loads(output)
        return parsed_output
    except json.JSONDecodeError as e:
        eprint(f"Error parsing JSON: {e}")
        return None


def print_table(header, list_of_objects, empty_value_indicator):
    # Find max width for each column
    widths = defaultdict(int)
    for obj in list_of_objects:
        for hdr in header:
            value = obj.get(hdr)
            if value is None:
                obj[hdr] = value = empty_value_indicator
            widths[hdr] = max(widths[hdr], len(str(value)), len(str(hdr)))

    # Print header
    print(
        UNDERLINE + " ".join(hdr.upper().ljust(widths[hdr]) for hdr in header) + NORMAL
    )

    # Print rows
    for obj in list_of_objects:
        print(" ".join(str(obj.get(hdr)).ljust(widths[hdr]) for hdr in header))
