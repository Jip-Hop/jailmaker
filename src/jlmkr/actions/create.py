# SPDX-FileCopyrightText: © 2024 Jip-Hop and the Jailmakers <https://github.com/Jip-Hop/jailmaker>
#
# SPDX-License-Identifier: LGPL-3.0-only

import contextlib
import os
import re

from inspect import cleandoc
from pathlib import Path, PurePath
from textwrap import dedent
from donor.jlmkr import DISCLAIMER
from utils.chroot import Chroot
from utils.config_parser import KeyValueParser, DEFAULT_CONFIG
from utils.console import YELLOW, BOLD, NORMAL, eprint
from utils.download import run_lxc_download_script
from utils.files import stat_chmod, get_mount_point
from utils.jail_dataset import check_jail_name_valid, check_jail_name_available
from utils.jail_dataset import get_jail_config_path, get_jail_rootfs_path
from utils.jail_dataset import get_jail_path, get_zfs_dataset, create_zfs_dataset, cleanup
from utils.paths import COMMAND_NAME, JAILS_DIR_PATH, SCRIPT_NAME, SCRIPT_DIR_PATH


def create_jail(**kwargs):
    print(DISCLAIMER)

    if os.path.basename(SCRIPT_DIR_PATH) != "jailmaker":
        eprint(
            dedent(
                f"""
            {COMMAND_NAME} needs to create files.
            Currently it can not decide if it is safe to create files in:
            {SCRIPT_DIR_PATH}
            Please create a dedicated dataset called "jailmaker", store {SCRIPT_NAME} there and try again."""
            )
        )
        return 1

    if not PurePath(get_mount_point(SCRIPT_DIR_PATH)).is_relative_to("/mnt"):
        print(
            dedent(
                f"""
            {YELLOW}{BOLD}WARNING: BEWARE OF DATA LOSS{NORMAL}

            {SCRIPT_NAME} should be on a dataset mounted under /mnt (it currently is not).
            Storing it on the boot-pool means losing all jails when updating TrueNAS.
            Jails will be stored under:
            {SCRIPT_DIR_PATH}
        """
            )
        )

    jail_name = kwargs.pop("jail_name")
    start_now = False

    if not check_jail_name_valid(jail_name):
        return 1

    if not check_jail_name_available(jail_name):
        return 1

    start_now = kwargs.pop("start", start_now)
    jail_config_path = kwargs.pop("config")

    config = KeyValueParser()

    if jail_config_path:
        # TODO: fallback to default values for e.g. distro and release if they are not in the config file
        if jail_config_path == "-":
            print(f"Creating jail {jail_name} from config template passed via stdin.")
            config.read_string(sys.stdin.read())
        else:
            print(f"Creating jail {jail_name} from config template {jail_config_path}.")
            if jail_config_path not in config.read(jail_config_path):
                eprint(f"Failed to read config template {jail_config_path}.")
                return 1
    else:
        print(f"Creating jail {jail_name} with default config.")
        config.read_string(DEFAULT_CONFIG)

    for option in [
        "distro",
        "gpu_passthrough_intel",
        "gpu_passthrough_nvidia",
        "release",
        "seccomp",
        "startup",
        "systemd_nspawn_user_args",
    ]:
        value = kwargs.pop(option)
        if (
            value is not None
            # String, non-empty list of args or int
            and (isinstance(value, int) or len(value))
            and value is not config.my_get(option, None)
        ):
            # TODO: this will wipe all systemd_nspawn_user_args from the template...
            # Should there be an option to append them instead?
            print(f"Overriding {option} config value with {value}.")
            config.my_set(option, value)

    jail_path = get_jail_path(jail_name)

    distro = config.my_get("distro")
    release = config.my_get("release")

    # Cleanup in except, but only once the jail_path is final
    # Otherwise we may cleanup the wrong directory
    try:
        # Create the dir or dataset where to store the jails
        if not os.path.exists(JAILS_DIR_PATH):
            if get_zfs_dataset(SCRIPT_DIR_PATH):
                # Creating "jails" dataset if "jailmaker" is a ZFS Dataset
                create_zfs_dataset(JAILS_DIR_PATH)
            else:
                os.makedirs(JAILS_DIR_PATH, exist_ok=True)
            stat_chmod(JAILS_DIR_PATH, 0o700)

        # Creating a dataset for the jail if the jails dir is a dataset
        if get_zfs_dataset(JAILS_DIR_PATH):
            create_zfs_dataset(jail_path)

        jail_config_path = get_jail_config_path(jail_name)
        jail_rootfs_path = get_jail_rootfs_path(jail_name)

        # Create directory for rootfs
        os.makedirs(jail_rootfs_path, exist_ok=True)
        # LXC download script needs to write to this file during install
        # but we don't need it so we will remove it later
        open(jail_config_path, "a").close()

        if (
            returncode := run_lxc_download_script(
                jail_name, jail_path, jail_rootfs_path, distro, release
            )
            != 0
        ):
            cleanup(jail_path)
            return returncode

        # Assuming the name of your jail is "myjail"
        # and "machinectl shell myjail" doesn't work
        # Try:
        #
        # Stop the jail with:
        # machinectl stop myjail
        # And start a shell inside the jail without the --boot option:
        # systemd-nspawn -q -D jails/myjail/rootfs /bin/sh
        # Then set a root password with:
        # In case of amazonlinux you may need to run:
        # yum update -y && yum install -y passwd
        # passwd
        # exit
        # Then you may login from the host via:
        # machinectl login myjail
        #
        # You could also enable SSH inside the jail to login
        #
        # Or if that doesn't work (e.g. for alpine) get a shell via:
        # nsenter -t $(machinectl show myjail -p Leader --value) -a /bin/sh -l
        # But alpine jails made with jailmaker have other issues
        # They don't shutdown cleanly via systemctl and machinectl...

        with Chroot(jail_rootfs_path):
            # Use chroot to correctly resolve absolute /sbin/init symlink
            init_system_name = os.path.basename(os.path.realpath("/sbin/init"))

        if (
            init_system_name != "systemd"
            and parse_os_release(jail_rootfs_path).get("ID") != "nixos"
        ):
            print(
                dedent(
                    f"""
                {YELLOW}{BOLD}WARNING: DISTRO NOT SUPPORTED{NORMAL}

                Chosen distro appears not to use systemd...

                You probably will not get a shell with:
                machinectl shell {jail_name}

                You may get a shell with this command:
                nsenter -t $(machinectl show {jail_name} -p Leader --value) -a /bin/sh -l

                Read about the downsides of nsenter:
                https://github.com/systemd/systemd/issues/12785#issuecomment-503019081

                {BOLD}Using this distro with {COMMAND_NAME} is NOT recommended.{NORMAL}
            """
                )
            )

            print("Autostart has been disabled.")
            print("You need to start this jail manually.")
            config.my_set("startup", 0)
            start_now = False

        # Remove config which systemd handles for us
        with contextlib.suppress(FileNotFoundError):
            os.remove(os.path.join(jail_rootfs_path, "etc/machine-id"))
        with contextlib.suppress(FileNotFoundError):
            os.remove(os.path.join(jail_rootfs_path, "etc/resolv.conf"))

        # https://github.com/systemd/systemd/issues/852
        print(
            "\n".join([f"pts/{i}" for i in range(0, 11)]),
            file=open(os.path.join(jail_rootfs_path, "etc/securetty"), "w"),
        )

        network_dir_path = os.path.join(jail_rootfs_path, "etc/systemd/network")

        # Modify default network settings, if network_dir_path exists
        if os.path.isdir(network_dir_path):
            default_host0_network_file = os.path.join(
                jail_rootfs_path, "lib/systemd/network/80-container-host0.network"
            )

            # Check if default host0 network file exists
            if os.path.isfile(default_host0_network_file):
                override_network_file = os.path.join(
                    network_dir_path, "80-container-host0.network"
                )

                # Override the default 80-container-host0.network file (by using the same name)
                # This config applies when using the --network-bridge option of systemd-nspawn
                # Disable LinkLocalAddressing on IPv4, or else the container won't get IP address via DHCP
                # But keep it enabled on IPv6, as SLAAC and DHCPv6 both require a local-link address to function
                print(
                    Path(default_host0_network_file)
                    .read_text()
                    .replace("LinkLocalAddressing=yes", "LinkLocalAddressing=ipv6"),
                    file=open(override_network_file, "w"),
                )

            # Setup DHCP for macvlan network interfaces
            # This config applies when using the --network-macvlan option of systemd-nspawn
            # https://www.debian.org/doc/manuals/debian-reference/ch05.en.html#_the_modern_network_configuration_without_gui
            print(
                cleandoc(
                    """
                [Match]
                Virtualization=container
                Name=mv-*

                [Network]
                DHCP=yes
                LinkLocalAddressing=ipv6

                [DHCPv4]
                UseDNS=true
                UseTimezone=true
            """
                ),
                file=open(os.path.join(network_dir_path, "mv-dhcp.network"), "w"),
            )

            # Setup DHCP for veth-extra network interfaces
            # This config applies when using the --network-veth-extra option of systemd-nspawn
            # https://www.debian.org/doc/manuals/debian-reference/ch05.en.html#_the_modern_network_configuration_without_gui
            print(
                cleandoc(
                    """
                [Match]
                Virtualization=container
                Name=vee-*

                [Network]
                DHCP=yes
                LinkLocalAddressing=ipv6

                [DHCPv4]
                UseDNS=true
                UseTimezone=true
            """
                ),
                file=open(os.path.join(network_dir_path, "vee-dhcp.network"), "w"),
            )

            # Override preset which caused systemd-networkd to be disabled (e.g. fedora 39)
            # https://www.freedesktop.org/software/systemd/man/latest/systemd.preset.html
            # https://github.com/lxc/lxc-ci/blob/f632823ecd9b258ed42df40449ec54ed7ef8e77d/images/fedora.yaml#L312C5-L312C38

            preset_path = os.path.join(jail_rootfs_path, "etc/systemd/system-preset")
            os.makedirs(preset_path, exist_ok=True)
            print(
                "enable systemd-networkd.service",
                file=open(os.path.join(preset_path, "00-jailmaker.preset"), "w"),
            )

        with open(jail_config_path, "w") as fp:
            config.write(fp)

        os.chmod(jail_config_path, 0o600)

    # Cleanup on any exception and rethrow
    except BaseException as error:
        cleanup(jail_path)
        raise error

    if start_now:
        return start_jail(jail_name)

    return 0
