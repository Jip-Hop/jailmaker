#!/usr/bin/env python3

import argparse
import configparser
import contextlib
import ctypes
import hashlib
import os
import re
import readline
import shlex
import shutil
import stat
import subprocess
import sys
import urllib.request

from inspect import cleandoc
from pathlib import Path, PurePath
from textwrap import dedent

# Only set a color if we have an interactive tty
if sys.stdout.isatty():
    BOLD = '\033[1m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    NORMAL = '\033[0m'
else:
    BOLD = RED = YELLOW = NORMAL = ''

DISCLAIMER = f"""{YELLOW}{BOLD}USE THIS SCRIPT AT YOUR OWN RISK!
IT COMES WITHOUT WARRANTY AND IS NOT SUPPORTED BY IXSYSTEMS.{NORMAL}"""

DESCRIPTION = "Create persistent Linux 'jails' on TrueNAS SCALE, with full access to all files \
    via bind mounts, without modifying the host OS thanks to systemd-nspawn!"

VERSION = '0.0.0'

JAILS_DIR_PATH = 'jails'
JAIL_CONFIG_NAME = 'config'
JAIL_ROOTFS_NAME = 'rootfs'
DOWNLOAD_SCRIPT_DIGEST = '6cca2eda73c7358c232fecb4e750b3bf0afa9636efb5de6a9517b7df78be12a4'
SCRIPT_NAME = os.path.basename(__file__)
SCRIPT_DIR_PATH = os.path.dirname(os.path.realpath(__file__))


def eprint(*args, **kwargs):
    """
    Print to stderr.
    """
    print(*args, file=sys.stderr, **kwargs)


def fail(*args, **kwargs):
    """
    Print to stderr and exit.
    """
    eprint(*args, **kwargs)
    sys.exit(1)


def start_jail(jail_name):
    """
    Start jail with given name.
    """

    jail_path = os.path.join(JAILS_DIR_PATH, jail_name)
    jail_config_path = os.path.join(jail_path, JAIL_CONFIG_NAME)

    config = configparser.ConfigParser()
    try:
        # Workaround to read config file without section headers
        config.read_string('[DEFAULT]\n'+Path(jail_config_path).read_text())
    except FileNotFoundError:
        fail(f'Unable to find: {jail_config_path}.')

    config = dict(config['DEFAULT'])

    print("Config loaded!")

    systemd_run_additional_args = [
        f"--unit=jlmkr-{jail_name}",
        f"--working-directory=./{jail_path}",
        f"--description=My nspawn jail {jail_name} [created with jailmaker]",
    ]

    systemd_nspawn_additional_args = [
        f"--machine={jail_name}",
        f"--directory={JAIL_ROOTFS_NAME}",
    ]

    if config.get('docker_compatible') == '1':
        # Enable ip forwarding on the host (docker needs it)
        print(1, file=open('/proc/sys/net/ipv4/ip_forward', 'w'))

        # Load br_netfilter kernel module and enable bridge-nf-call to fix warning when running docker info:
        # WARNING: bridge-nf-call-iptables is disabled
        # WARNING: bridge-nf-call-ip6tables is disabled
        #
        # If we are using Apps then this should already be enabled
        # May cause "guest container traffic to be blocked by iptables rules that are intended for the host"
        # https://unix.stackexchange.com/q/720105/477308
        # https://github.com/moby/moby/issues/24809
        # https://docs.oracle.com/en/operating-systems/oracle-linux/docker/docker-KnownIssues.html#docker-issues
        # https://wiki.libvirt.org/page/Net.bridge.bridge-nf-call_and_sysctl.conf
        # https://serverfault.com/questions/963759/docker-breaks-libvirt-bridge-network

        if subprocess.run(['modprobe', 'br_netfilter']).returncode == 0:
            print(1, file=open('/proc/sys/net/bridge/bridge-nf-call-iptables', 'w'))
            print(1, file=open('/proc/sys/net/bridge/bridge-nf-call-ip6tables', 'w'))
        else:
            eprint(dedent("""
                Failed to load br_netfilter kernel module."""))

        # To properly run docker inside the jail, we need to lift restrictions
        # Without DevicePolicy=auto images with device nodes may not be pulled
        # For example docker pull ljishen/sysbench would fail
        # Fortunately I didn't encounter many images with device nodes...
        #
        # Issue: https://github.com/moby/moby/issues/35245
        #
        # The systemd-nspawn manual explicitly mentions:
        # Device nodes may not be created
        # https://www.freedesktop.org/software/systemd/man/systemd-nspawn.html
        #
        # Workaround: https://github.com/kinvolk/kube-spawn/pull/328
        #
        # However, it seems like the DeviceAllow= workaround may break in
        # a future Debian release with systemd version 250 or higher
        # https://github.com/systemd/systemd/issues/21987
        #
        # As of 29-1-2023 it still works with debian bookworm (nightly) and sid
        # using the latest systemd version 252.4-2 so I think we're good!
        #
        # Use SYSTEMD_SECCOMP=0: https://github.com/systemd/systemd/issues/18370

        systemd_run_additional_args += [
            '--setenv=SYSTEMD_SECCOMP=0',
            '--property=DevicePolicy=auto',
        ]

        # Add additional flags required for docker
        systemd_nspawn_additional_args += [
            '--capability=all',
            '--system-call-filter=add_key keyctl bpf',
        ]

    if config.get('gpu_passthrough') == '1':
        systemd_nspawn_additional_args.append(
            '--property=DeviceAllow=char-drm rw')

        # Detect intel GPU device and if present add bind flag
        if os.path.exists('/dev/dri'):
            systemd_nspawn_additional_args.append('--bind=/dev/dri')

        # Detect nvidia GPU
        if os.path.exists('/dev/nvidia0'):
            nvidia_driver_files = []

            try:
                nvidia_driver_files = subprocess.check_output(
                    ['nvidia-container-cli', 'list']).decode().split('\n')
            except subprocess.CalledProcessError:
                eprint(dedent("""
                    Failed to run nvidia-container-cli.
                    Unable to mount the nvidia driver files."""))

            for file_path in nvidia_driver_files:
                if file_path.startswith('/dev/'):
                    systemd_nspawn_additional_args.append(
                        f"--bind={file_path}")
                else:
                    systemd_nspawn_additional_args.append(
                        f"--bind-ro=={file_path}")

    cmd = ['systemd-run',
           *shlex.split(config.get('systemd_run_default_args', '')),
           *systemd_run_additional_args,
           '--',
           'systemd-nspawn',
           *shlex.split(config.get('systemd_nspawn_default_args', '')),
           *systemd_nspawn_additional_args,
           *shlex.split(config.get('systemd_nspawn_user_args', ''))
           ]

    print(dedent(f"""
        Starting jail with the following command:
        
        {shlex.join(cmd)}

        Starting jail with name: {jail_name}
    """))

    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError:
        fail(dedent(f"""
            Failed to start the jail...
            In case of a config error, you may fix it with:
            nano {shlex.quote(jail_config_path)}
        """))

    print(dedent(f"""
        Check logging:
        journalctl -u jlmkr-{jail_name}

        Check status:
        systemctl status jlmkr-{jail_name}

        Stop the jail:
        machinectl stop {jail_name}

        Get a shell:
        machinectl shell {jail_name}
    """))


def cleanup(jail_path):
    """
    Cleanup after aborted jail creation.
    """
    if os.path.isdir(jail_path):
        eprint(f"Cleaning up: {jail_path}")
        shutil.rmtree(jail_path)


def input_with_default(prompt, default):
    """
    Ask user for input with a default value already provided.
    """
    readline.set_startup_hook(lambda: readline.insert_text(default))
    try:
        return input(prompt)
    finally:
        readline.set_startup_hook()


def validate_sha256(file_path, digest):
    """
    Validates if a file matches a sha256 digest.
    """
    try:
        with open(file_path, 'rb') as f:
            file_hash = hashlib.sha256(f.read()).hexdigest()
            return file_hash == digest
    except FileNotFoundError:
        return False


def stat_chmod(file_path, mode):
    """
    Change mode if file doesn't already have this mode.
    """
    if mode != stat.S_IMODE(os.stat(file_path).st_mode):
        os.chmod(file_path, mode)


def agree(question, default=None):
    """
    Ask user a yes/no question.
    """
    hint = '[Y/n]' if default == 'y' else (
        '[y/N]' if default == 'n' else '[y/n]')

    while True:
        user_input = input(f"{question} {hint} ") or default

        if user_input.lower() in ['y', 'n']:
            return user_input.lower() == 'y'

        eprint("Invalid input. Please type 'y' for yes or 'n' for no and press enter.")


def get_mount_point(path):
    """
    Return the mount point on which the given path resides.
    """
    path = os.path.abspath(path)
    while not os.path.ismount(path):
        path = os.path.dirname(path)
    return path


def create_jail(jail_name):
    """
    Create jail with given name.
    """

    print(DISCLAIMER)

    arch = 'amd64'
    lxc_dir = '.lxc'
    lxc_cache = os.path.join(lxc_dir, 'cache')
    lxc_download_script = os.path.join(lxc_dir, 'lxc-download.sh')

    if os.path.basename(os.getcwd()) != 'jailmaker':
        fail(dedent(f"""
            {SCRIPT_NAME} needs to create files.
            Currently it can not decide if it is safe to create files in:
            {SCRIPT_DIR_PATH}
            Please create a dedicated directory called 'jailmaker', store {SCRIPT_NAME} there and try again."""))

    if not PurePath(get_mount_point(os.getcwd())).is_relative_to('/mnt'):
        print(dedent(f"""
            {YELLOW}{BOLD}WARNING: BEWARE OF DATA LOSS{NORMAL}

            {SCRIPT_NAME} should be on a dataset mounted under /mnt (it currently is not).
            Storing it on the boot-pool means losing all jails when updating TrueNAS.
            If you continue, jails will be stored under:
            {SCRIPT_DIR_PATH}
        """))
        if not agree("Do you wish to ignore this warning and continue?", 'n'):
            fail("Aborting...")

    # Create the lxc dirs if nonexistent
    os.makedirs(lxc_dir, exist_ok=True)
    stat_chmod(lxc_dir, 0o700)
    os.makedirs(lxc_cache, exist_ok=True)
    stat_chmod(lxc_cache, 0o700)

    # Create the dir where to store the jails
    os.makedirs(JAILS_DIR_PATH, exist_ok=True)
    stat_chmod(JAILS_DIR_PATH, 0o700)

    # Fetch the lxc download script if not present locally (or hash doesn't match)
    if not validate_sha256(lxc_download_script, DOWNLOAD_SCRIPT_DIGEST):
        urllib.request.urlretrieve(
            "https://raw.githubusercontent.com/Jip-Hop/lxc/58520263041b6864cadad96278848f9b8ce78ee9/templates/lxc-download.in", lxc_download_script)
        if not validate_sha256(lxc_download_script, DOWNLOAD_SCRIPT_DIGEST):
            fail("Abort! Downloaded script has unexpected contents.")

    stat_chmod(lxc_download_script, 0o700)

    distro = 'debian'
    release = 'bullseye'

    print()
    if not agree("Install the recommended distro (Debian 11)?", 'y'):
        print(dedent(f"""
            {YELLOW}{BOLD}WARNING: ADVANCED USAGE{NORMAL}

            You may now choose from a list which distro to install.
            But not all of them will work with {SCRIPT_NAME} since these images are made for LXC.
            Distros based on systemd probably work (e.g. Ubuntu, Arch Linux and Rocky Linux).
            Others (Alpine, Devuan, Void Linux) probably will not.
        """))
        input("Press Enter to continue...")
        print()

        subprocess.call([lxc_download_script, '--list',
                        '--arch=' + arch], env={'LXC_CACHE_PATH': lxc_cache})

        print(dedent("""
            Choose from the DIST column.
        """))

        distro = input("Distro: ")

        print(dedent("""
            Choose from the RELEASE column (or ARCH if RELEASE is empty).
        """))

        release = input("Release: ")

    jail_path = None

    while jail_path == None:
        print()
        jail_name = input_with_default("Enter jail name: ", jail_name).strip()
        if not re.match(r"^[.a-zA-Z0-9-]{1,64}$", jail_name) or jail_name.startswith(".") or ".." in jail_name:
            eprint(dedent(f"""

                {YELLOW}{BOLD}WARNING: INVALID NAME{NORMAL}

                A valid name consists of:
                - allowed characters (alphanumeric, dash, dot)
                - no leading or trailing dots
                - no sequences of multiple dots
                - max 64 characters

            """))
        else:
            jail_path = os.path.join(JAILS_DIR_PATH, jail_name)
            if os.path.exists(jail_path):
                print()
                eprint("A jail with this name already exists.")
                jail_path = None

    # Cleanup in except, but only once the jail_path is final
    # Otherwise we may cleanup the wrong directory
    try:
        print(dedent(f"""
            Docker won't be installed by {SCRIPT_NAME}.
            But it can setup the jail with the capabilities required to run docker.
            You can turn DOCKER_COMPATIBLE mode on/off post-install.
        """))

        docker_compatible = 0

        if agree('Make jail docker compatible right now?', 'n'):
            docker_compatible = 1

        print()

        gpu_passthrough = 0

        if agree('Give access to the GPU inside the jail?', 'n'):
            gpu_passthrough = 1

        print(dedent(f"""
            {YELLOW}{BOLD}WARNING: CHECK SYNTAX{NORMAL}
        
            You may pass additional flags to systemd-nspawn.
            With incorrect flags the jail may not start.
            It is possible to correct/add/remove flags post-install.
        """))

        if agree('Show the man page for systemd-nspawn?', 'n'):
            os.system("man systemd-nspawn")
        else:
            print(dedent(f"""
                You may read the systemd-nspawn manual online:
                https://manpages.debian.org/{release}/systemd-container/systemd-nspawn.1.en.html"""))

        # Backslashes and colons need to be escaped in bind mount options:
        # e.g. to bind mount a file called:
        # weird chars :?\"
        # the corresponding command would be:
        # --bind-ro='/mnt/data/weird chars \:?\\"'

        print(dedent("""
            For example to mount directories inside the jail you may add:
            --bind='/mnt/data/a writable directory/' --bind-ro='/mnt/data/a readonly directory/'
        """))

        # Enable tab auto completion of file paths after the = symbol
        readline.set_completer_delims('=')
        readline.parse_and_bind('tab: complete')

        readline_lib = ctypes.CDLL(readline.__file__)
        rl_completer_quote_characters = ctypes.c_char_p.in_dll(
            readline_lib,
            "rl_completer_quote_characters"
        )

        # Let the readline library know about quote characters for completion
        rl_completer_quote_characters.value = "\"'".encode('utf-8')

        # TODO: more robust tab completion of file paths with space or = character
        # Currently completing these only works when the path is quoted
        # https://thoughtbot.com/blog/tab-completion-in-gnu-readline
        # https://stackoverflow.com/a/67118744
        # https://github.com/python-cmd2/cmd2/blob/ee7599f9ac0dbb6ce3793f6b665ba1200d3ef9a3/cmd2/cmd2.py
        # https://stackoverflow.com/a/40152927

        systemd_nspawn_user_args = input("Additional flags: ") or ""
        # Disable tab auto completion
        readline.parse_and_bind('tab: self-insert')
        print()

        jail_config_path = os.path.join(jail_path, JAIL_CONFIG_NAME)
        jail_rootfs_path = os.path.join(jail_path, JAIL_ROOTFS_NAME)

        # Create directory for rootfs
        os.makedirs(jail_rootfs_path, exist_ok=True)
        # LXC download script needs to write to this file during install
        # but we don't need it so we will remove it later
        open(jail_config_path, "a").close()

        subprocess.run([lxc_download_script, f'--name={jail_name}', f'--path={jail_path}',  f'--rootfs={jail_rootfs_path}', f'--arch={arch}',
                        f'--dist={distro}', f'--release={release}'], check=True, env={"LXC_CACHE_PATH": lxc_cache})

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

        if os.path.basename(os.path.realpath(
                os.path.join(jail_rootfs_path, 'sbin/init'))) != "systemd":
            print(dedent(f"""
                {YELLOW}{BOLD}WARNING: DISTRO NOT SUPPORTED{NORMAL}
                
                Chosen distro appears not to use systemd...

                You probably will not get a shell with:
                machinectl shell {jail_name}

                You may get a shell with this command:
                nsenter -t $(machinectl show {jail_name} -p Leader --value) -a /bin/sh -l

                Read about the downsides of nsenter:
                https://github.com/systemd/systemd/issues/12785#issuecomment-503019081

                {BOLD}Using this distro with {SCRIPT_NAME} is NOT recommended.{NORMAL}
            """))

            if agree("Abort creating jail?", 'y'):
                exit(1)

        with contextlib.suppress(FileNotFoundError):
            # Remove config which systemd handles for us
            os.remove(os.path.join(jail_rootfs_path, 'etc/machine-id'))
            os.remove(os.path.join(jail_rootfs_path, 'etc/resolv.conf'))

        # https://github.com/systemd/systemd/issues/852
        print('\n'.join([f"pts/{i}" for i in range(0, 11)]),
              file=open(os.path.join(jail_rootfs_path, 'etc/securetty'), 'w'))

        network_dir_path = os.path.join(
            jail_rootfs_path, "etc/systemd/network")

        # Modify default network settings, if network_dir_path exists
        if os.path.isdir(network_dir_path):
            default_host0_network_file = os.path.join(
                jail_rootfs_path, "lib/systemd/network/80-container-host0.network")

            # Check if default host0 network file exists
            if os.path.isfile(default_host0_network_file):
                override_network_file = os.path.join(
                    network_dir_path, "80-container-host0.network")

                # Override the default 80-container-host0.network file (by using the same name)
                # This config applies when using the --network-bridge option of systemd-nspawn
                # Disable LinkLocalAddressing or else the container won't get IP address via DHCP
                # Enable DHCP only for ipv4 else systemd-networkd will complain that LinkLocalAddressing is disabled
                print(Path(default_host0_network_file).read_text().replace("LinkLocalAddressing=yes",
                      "LinkLocalAddressing=no").replace("DHCP=yes", "DHCP=ipv4"), file=open(override_network_file, 'w'))

            # Setup DHCP for macvlan network interfaces
            # This config applies when using the --network-macvlan option of systemd-nspawn
            # https://www.debian.org/doc/manuals/debian-reference/ch05.en.html#_the_modern_network_configuration_without_gui
            print(cleandoc("""
                [Match]
                Virtualization=container
                Name=mv-*

                [Network]
                DHCP=ipv4
                LinkLocalAddressing=no

                [DHCPv4]
                UseDNS=true
                UseTimezone=true
            """), file=open(os.path.join(network_dir_path, "mv-dhcp.network"), "w"))

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

        systemd_run_default_args = [
            '--property=KillMode=mixed',
            '--property=Type=notify',
            '--property=RestartForceExitStatus=133',
            '--property=SuccessExitStatus=133',
            '--property=Delegate=yes',
            '--property=TasksMax=infinity',
            '--collect',
            '--setenv=SYSTEMD_NSPAWN_LOCK=0'
        ]

        systemd_nspawn_default_args = [
            '--keep-unit',
            '--quiet',
            '--boot'
        ]

        config = cleandoc(f"""
            docker_compatible={docker_compatible}
            gpu_passthrough={gpu_passthrough}
            systemd_nspawn_user_args={systemd_nspawn_user_args}
            # You generally will not need to change the options below
            systemd_run_default_args={' '.join(systemd_run_default_args)}
            systemd_nspawn_default_args={' '.join(systemd_nspawn_default_args)}
        """)

        print(config, file=open(os.path.join(jail_path, 'config'), 'w'))

        os.chmod(jail_config_path, 0o600)

    # Cleanup on any exception and rethrow
    except BaseException as error:
        cleanup(jail_path)
        raise error

    print()
    if agree("Do you want to start the jail?", 'y'):
        start_jail(jail_name)


def delete_jail(jail_name):
    """
    Delete jail with given name.
    """
    # stop the jail
    os.system(f"machinectl stop {jail_name}")

    jail_path = os.path.join(JAILS_DIR_PATH, jail_name)

    if os.path.isdir(jail_path):
        eprint(f"Cleaning up: {jail_path}")
        shutil.rmtree(jail_path)


def main():
    if os.stat(__file__).st_uid != 0:
        fail("This script should be owned by the root user...")

    parser = argparse.ArgumentParser(
        description=DESCRIPTION, epilog=DISCLAIMER)
    parser.add_argument('--version', action='version', version=VERSION)

    subparsers = parser.add_subparsers(title='commands', dest='subcommand')

    create_parser = subparsers.add_parser(name='create', epilog=DISCLAIMER)
    create_parser.add_argument('name', nargs='?', help='name of the jail')

    start_parser = subparsers.add_parser(name='start', epilog=DISCLAIMER)
    start_parser.add_argument('name', help='name of the jail')

    start_parser = subparsers.add_parser(name='delete', epilog=DISCLAIMER)
    start_parser.add_argument('name', help='name of the jail')

    parser.usage = f"{parser.format_usage()[7:]}{create_parser.format_usage()}{start_parser.format_usage()}"

    if os.getuid() != 0:
        parser.print_usage()
        fail("Run this script as root...")

    os.chdir(SCRIPT_DIR_PATH)
    # Set appropriate permissions (if not already set) for this file, since it's executed as root
    stat_chmod(SCRIPT_NAME, 0o700)

    args = parser.parse_args()

    if args.subcommand == 'start':
        if args.name:
            start_jail(args.name)
        else:
            parser.error("Please specify the name of the jail to start.")

    elif args.subcommand == 'create':
        create_jail(args.name)

    elif args.subcommand == 'delete':
        delete_jail(args.name)

    elif args.subcommand:
        parser.print_usage()

    else:
        if agree("Create a new jail?", 'y'):
            print()
            create_jail("")
        else:
            parser.print_usage()


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
