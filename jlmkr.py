#!/usr/bin/env python3

import argparse
import contextlib
import hashlib
import os
import platform
import re
import readline
import shlex
import shutil
import stat
import subprocess
import sys
import textwrap
import urllib.request

def eprint(*args, **kwargs):
    print(*args, file=sys.stderr, **kwargs)

def stat_chmod(file_path, mode):
    current_mode = stat.S_IMODE(os.stat(file_path).st_mode)
    if current_mode != mode:
        os.chmod(file_path, mode)

def agree(question, default=None):

    if default == None:
        hint = "[yes/no]"
    elif default == "yes":
        hint = "[YES/no]"
    else:
        hint = "[yes/NO]"

    while True:
        user_input = input(f"{question} {hint} ") or default

        if user_input.lower() in ["yes", "no"]:
            return user_input.lower() == "yes"

        print("Invalid input. Please enter 'yes' or 'no'.")

def input_with_default(prompt, default):
    readline.set_startup_hook(lambda: readline.insert_text(default))
    try:
        return input(prompt)
    finally:
        readline.set_startup_hook()

def start_jail(jail_name, jails_dir_path, jail_config_name, jail_rootfs_name, script_name):
    
    jail_path = os.path.join(jails_dir_path, jail_name)
    jail_config_path = os.path.join(jail_path, jail_config_name)

    if not os.path.isfile(jail_config_path):
        sys.exit(1)

    config = {}

    with open(jail_config_path) as f:
        for line in f:
            try:
                key, value = line.strip().split("=", 1)
                if value:
                    config[key] = value
            except ValueError:
                pass

    systemd_run_additional_args = [
    "--unit=jlmkr-{}".format(jail_name),
    "--working-directory=./{}".format(jail_path),
    "--description=My nspawn jail {} [created with jailmaker]".format(jail_name),
    ]
    
    systemd_nspawn_additional_args = [
        "--machine={}".format(jail_name),
        "--directory={}".format(jail_rootfs_name),
    ]

    if config.get('DOCKER_COMPATIBLE') == '1':
        with open("/proc/sys/net/ipv4/ip_forward", "w") as f:
            f.write("1")
        systemd_run_additional_args += [
            "--setenv=SYSTEMD_SECCOMP=0",
            "--property=DevicePolicy=auto",
        ]
        systemd_nspawn_additional_args += [
            "--capability=all",
            "--system-call-filter=add_key keyctl bpf",
        ]

    if config.get('GPU_PASSTHROUGH') == '1':
        systemd_nspawn_additional_args += ["--property=DeviceAllow=char-drm rw"]

        try:
            subprocess.check_output(["ls", "/dev/dri"])
            systemd_nspawn_additional_args += ["--bind=/dev/dri"]
        except subprocess.CalledProcessError:
            pass

        try:
            subprocess.check_output(["ls", "/dev/nvidia"])
            output = subprocess.check_output(["nvidia-container-cli", "list"]).decode().split("\n")
            for line in output:
                if line.startswith("/dev/"):
                    systemd_nspawn_additional_args += ["--bind=" + line]
                else:
                    systemd_nspawn_additional_args += ["--bind-ro=" + line]
        except subprocess.CalledProcessError:
            pass

    args = []

    if config.get('SYSTEMD_RUN_DEFAULT_ARGS'):
        args += shlex.split(config['SYSTEMD_RUN_DEFAULT_ARGS'])

    args += systemd_run_additional_args + ["--", "systemd-nspawn"]

    if config.get('SYSTEMD_NSPAWN_DEFAULT_ARGS'):
        args += shlex.split(config['SYSTEMD_NSPAWN_DEFAULT_ARGS'])

    args += systemd_nspawn_additional_args

    if config.get('SYSTEMD_NSPAWN_USER_ARGS'):
        args += shlex.split(config['SYSTEMD_NSPAWN_USER_ARGS'])

    args_string = " ".join(args)
    # TODO: properly escape these, like printf %q
    print(f"systemd-run {args_string}")

    print(f"Starting jail with name: {jail_name}")

    try:
        subprocess.run(["systemd-run", *args], check=True)
    except subprocess.CalledProcessError:
        print("An error occurred")

def validate_sha256(file_path, digest):
    """
    Validates if a file matches a sha256 digest.
    """
    with open(file_path, 'rb') as f:
        file_hash = hashlib.sha256(f.read()).hexdigest()
        return file_hash == digest

def validate_download_script(file_path):
    if os.path.isfile(file_path):
        return validate_sha256(file_path, '6cca2eda73c7358c232fecb4e750b3bf0afa9636efb5de6a9517b7df78be12a4')

def download_file(url, file_path):
    try:
        urllib.request.urlretrieve(url, file_path)
    except Exception as e:
        print(f"Failed to download file {file_path} from {url}: {e}")

def cleanup(jail_path):
    if os.path.isdir(jail_path):
        eprint(f"Cleaning up: {jail_path}")
        shutil.rmtree(jail_path)

def create_jail(jail_name, jails_dir_path, jail_config_name, jail_rootfs_name, script_name, script_dir_path):

    print("TODO: DISCLAIMER")
    print()

    arch = 'amd64'

    lxc_dir = '.lxc'
    lxc_cache = os.path.join(lxc_dir, 'cache')
    lxc_download_script = os.path.join(lxc_dir, 'lxc-download.sh')

    if os.path.basename(os.getcwd()) != 'jailmaker':
        eprint(f"{script_name} needs to create files.")
        eprint('Currently it can not decide if it is safe to create files in:')
        eprint(f"{script_dir_path}")
        eprint(f"Please create a dedicated directory called 'jailmaker', store {script_name} there and try again.")
        sys.exit(1)

    # TODO: insert the findmnt part here

    # Create the lxc dirs if nonexistent
    os.makedirs(lxc_dir, exist_ok=True)
    stat_chmod(lxc_dir, 0o700)
    os.makedirs(lxc_cache, exist_ok=True)
    stat_chmod(lxc_cache, 0o700)

    # Create the dir where to store the jails
    os.makedirs(jails_dir_path, exist_ok=True)
    stat_chmod(jails_dir_path, 0o700)

    # Fetch the lxc download script if not present locally (or hash doesn't match)
    if not validate_download_script(lxc_download_script):
        download_file("https://raw.githubusercontent.com/Jip-Hop/lxc/58520263041b6864cadad96278848f9b8ce78ee9/templates/lxc-download.in", lxc_download_script)
        if not validate_download_script(lxc_download_script):
            eprint('Abort! Downloaded script has unexpected contents.')
            sys.exit(1)

    stat_chmod(lxc_download_script, 0o700)

    distro = 'debian'
    release = 'bullseye'

    if not agree("Install the recommended distro (Debian 11)?", 'yes'):
        print()
        print("${YELLOW}${BOLD}WARNING: ADVANCED USAGE${NORMAL}")
        print()
        print('You may now choose from a list which distro to install.')
        print(f"But not all of them will work with {script_name} since these images are made for LXC.")
        print('Distros based on systemd probably work (e.g. Ubuntu, Arch Linux and Rocky Linux).')
        print('Others (Alpine, Devuan, Void Linux) probably will not.')
        print()
        input('Press Enter to continue...')
        print()
        subprocess.call([lxc_download_script, "--list", "--arch=" + arch], env={"LXC_CACHE_PATH": lxc_cache})
        print()
        print('Choose from the DIST column.')
        print()
        distro = input("Distro: ")
        print()      
        print('Choose from the RELEASE column (or ARCH if RELEASE is empty).')
        print()
        release = input("Release: ")
    print()

    jail_path = None

    while jail_path == None:
        jail_name = input_with_default("Enter jail name: ", jail_name).strip()
        print()
        if not re.match(r"^[.a-zA-Z0-9-]{1,64}$", jail_name) or jail_name.startswith(".") or ".." in jail_name:
            # TODO: output colors
            eprint(textwrap.dedent('''

				${YELLOW}${BOLD}WARNING: INVALID NAME${NORMAL}

				A valid name consists of:
				- allowed characters (alphanumeric, dash, dot)
				- no leading or trailing dots
				- no sequences of multiple dots
				- max 64 characters
                
                '''))
        else:
            jail_path = os.path.join(jails_dir_path, jail_name)
            if os.path.exists(jail_path):
                eprint('A jail with this name already exists.')
                print()
                jail_path = None

    # Cleanup in except, but only once the jail_path is final
    # Otherwise we may cleanup the wrong directory
    try:
        print(f"Docker won't be installed by {script_name}.")
        print('But it can setup the jail with the capabilities required to run docker.')
        print('You can turn DOCKER_COMPATIBLE mode on/off post-install.')
        print()
        
        docker_compatible = 0
        
        if agree('Make jail docker compatible right now?', "no"):
            docker_compatible = 1
        
        print()

        gpu_passthrough = 0

        if agree('Give access to the GPU inside the jail?', "no"):
            gpu_passthrough = 1

        print()
        print("${YELLOW}${BOLD}WARNING: CHECK SYNTAX${NORMAL}")
        print()
        print('You may pass additional flags to systemd-nspawn.')
        print('With incorrect flags the jail may not start.')
        print('It is possible to correct/add/remove flags post-install.')
        print()

        if agree('Show the man page for systemd-nspawn?', "no"):
            os.system("man systemd-nspawn")
        else:
            print()
            print('You may read the systemd-nspawn manual online:')
            print(f"https://manpages.debian.org/{release}/systemd-container/systemd-nspawn.1.en.html")

        # Backslashes and colons need to be escaped in bind mount options:
        # e.g. to bind mount a file called:
        # weird chars :?\"
        # the corresponding command would be:
        # --bind-ro='/mnt/data/weird chars \:?\\"'

        print()
        print('For example to mount directories inside the jail you may add:')
        print('--bind=/mnt/a/readwrite/directory --bind-ro=/mnt/a/readonly/directory')
        print()
        systemd_nspawn_user_args = input("Additional flags: ") or ""
        print()

        jail_config_path = os.path.join(jail_path, jail_config_name)
        jail_rootfs_path = os.path.join(jail_path, jail_rootfs_name)

        # Create directory for rootfs
        os.makedirs(jail_rootfs_path, exist_ok=True)
        # LXC download script needs to write to this file during install
	    # but we don't need it so we will remove it later
        open(jail_config_path, "a").close()

        subprocess.run(f"{lxc_download_script} --name={jail_name} --path={jail_path} --rootfs={jail_rootfs_path} \
            --arch={arch} --dist={distro} --release={release}", shell=True, check=True, env={"LXC_CACHE_PATH": lxc_cache})
        
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
        print()

        # TODO: don't crash if init_path doesn't exist?
        init_path = os.path.realpath(os.path.join(jail_rootfs_path, 'sbin', 'init'))
        if os.path.basename(init_path) != "systemd":
            raise Exception("Error, not systemd!")
            # TODO: show warning and allow to continue

        with contextlib.suppress(FileNotFoundError):
            # Remove config which systemd handles for us
            os.remove(os.path.join(jail_rootfs_path, 'etc', 'machine-id'))
            os.remove(os.path.join(jail_rootfs_path, 'etc', 'resolv.conf'))

        # https://github.com/systemd/systemd/issues/852
        with open(os.path.join(jail_rootfs_path, 'etc', 'securetty'), "w") as f:
            for i in range(0, 11):
                f.write(f"pts/{i}\n")
        
        # TODO: fix networking config
#         network_dir_path = os.path.join(jail_rootfs_path, "etc", "systemd", "network")

#         if os.path.isdir(network_dir_path):
#             default_host0_network_file = os.path.join(jail_rootfs_path, "lib", "systemd", "network", "80-container-host0.network")

#             if os.path.isfile(default_host0_network_file):
#                 override_network_file = os.path.join(network_dir_path, "80-container-host0.network")
#                 with open(default_host0_network_file) as f:
#                     data = f.read().replace("LinkLocalAddressing=yes", "LinkLocalAddressing=no").replace("DHCP=yes", "DHCP=ipv4")
#                 with open(override_network_file, "w") as f:
#                     f.write(data)

#             with open(os.path.join(network_dir_path, "mv-dhcp.network"), "w") as f:
#                 f.write("""[Match]
# Virtualization=container
# Name=mv-*

# [Network]
# DHCP=ipv4
# LinkLocalAddressing=no

# [DHCPv4]
# UseDNS=true
# UseTimezone=true
# """)

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

        config = (
            f"DOCKER_COMPATIBLE={docker_compatible}\n"
            f"GPU_PASSTHROUGH={gpu_passthrough}\n"
            f"SYSTEMD_NSPAWN_USER_ARGS={systemd_nspawn_user_args}\n"
            "# You generally will not need to change the options below\n"
            f"SYSTEMD_RUN_DEFAULT_ARGS={' '.join(systemd_run_default_args)}\n"
            f"SYSTEMD_NSPAWN_DEFAULT_ARGS={' '.join(systemd_nspawn_default_args)}\n"
        )

        with open(os.path.join(jail_path, 'config'), "w") as f:
            f.write(config)

        os.chmod(jail_config_path, 0o600)

    except KeyboardInterrupt:
        print('Interrupted')
        cleanup(jail_path)
        sys.exit(130)

    except BaseException as error:
        eprint('An exception occurred: {}'.format(error))

        cleanup(jail_path)
        sys.exit(1)
    
    if agree("Do you want to start the jail?", 'yes'):
        start_jail(jail_name, jails_dir_path, jail_config_name, jail_rootfs_name, script_name)

def main():

    script_path = os.path.realpath(sys.argv[0])
    script_name = os.path.basename(script_path)
    script_dir_path = os.path.dirname(script_path)

    jails_dir_path = 'jails'
    jail_config_name = 'config'
    jail_rootfs_name = 'rootfs'
    
    if os.getuid() != 0:
        eprint('Run this script as root...')
        sys.exit(1)

    os.chdir(script_dir_path)
    # Set appropriate permissions (if not already set) for this file, since it's executed as root
    stat_chmod(script_name, 0o700)

    parser = argparse.ArgumentParser(description='Jailmaker')
    subparsers = parser.add_subparsers(title='subcommands', dest='subcommand')

    start_parser = subparsers.add_parser('start')
    start_parser.add_argument('name', help='Name of the jail')

    create_parser = subparsers.add_parser('create')
    create_parser.add_argument('name', nargs='?', help='Name of the jail')

    args = parser.parse_args()

    if args.subcommand == 'start':
        if args.name:
            start_jail(args.name, jails_dir_path, jail_config_name, jail_rootfs_name, script_name)
        else:
            parser.error('start subcommand requires a name argument')

    elif args.subcommand == 'create':
        create_jail(args.name, jails_dir_path, jail_config_name, jail_rootfs_name, script_name, script_dir_path)

    elif args.subcommand:
        parser.print_usage()

    else:
        if agree('Create a new jail?', 'yes'):
            print()
            create_jail("", jails_dir_path, jail_config_name, jail_rootfs_name, script_name, script_dir_path)
        else:
            parser.print_usage()

if __name__ == '__main__':
    # TODO: gracefully handle CTRL + C
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)