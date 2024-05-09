# Jailmaker

Persistent Linux 'jails' on TrueNAS SCALE to install software (docker-compose, portainer, podman, etc.) with full access to all files via bind mounts.

## Video Tutorial

[![TrueNAS Scale - Setting up Sandboxes with Jailmaker - YouTube Video](https://img.youtube.com/vi/S0nTRvAHAP8/0.jpg)<br>Watch on YouTube](https://www.youtube.com/watch?v=S0nTRvAHAP8 "TrueNAS Scale - Setting up Sandboxes with Jailmaker - YouTube Video")

## Disclaimer

**USING THIS SCRIPT IS AT YOUR OWN RISK! IT COMES WITHOUT WARRANTY AND IS NOT SUPPORTED BY IXSYSTEMS.**

## Summary

TrueNAS SCALE can create persistent Linux 'jails' with systemd-nspawn. This script helps with the following:

- Setting up the jail so it won't be lost when you update SCALE
- Choosing a distro (Debian 12 strongly recommended, but Ubuntu, Arch Linux or Rocky Linux seem good choices too)
- Will create a ZFS Dataset for each jail if the `jailmaker` directory is a dataset (easy snapshotting)
- Optional: configuring the jail so you can run Docker inside it
- Optional: GPU passthrough (including nvidia GPU with the drivers bind mounted from the host)
- Starting the jail with your config applied

## Security

Despite what the word 'jail' implies, jailmaker's intended use case is to create one or more additional filesystems to run alongside SCALE with minimal isolation. By default the root user in the jail with uid 0 is mapped to the host's uid 0. This has [obvious security implications](https://linuxcontainers.org/lxc/security/#privileged-containers). If this is not acceptable to you, you may lock down the jails by [limiting capabilities](https://manpages.debian.org/bookworm/systemd-container/systemd-nspawn.1.en.html#Security_Options) and/or using [user namespacing](https://manpages.debian.org/bookworm/systemd-container/systemd-nspawn.1.en.html#User_Namespacing_Options) or use a VM instead.

## Installation

Beginning with 24.04 (Dragonfish), TrueNAS SCALE includes the systemd-nspawn containerization program in the base system. Technically there's nothing to install. You only need the `jlmkr.py` script file in the right place. [Instructions with screenshots](https://www.truenas.com/docs/scale/scaletutorials/apps/sandboxes/) are provided on the TrueNAS website. Start by creating a new dataset called `jailmaker` with the default settings (from TrueNAS web interface). Then login as the root user and download `jlmkr.py`. If you login as non-root user (e.g. as admin), **you must become root first** by executing `sudo su`.

```shell
cd /mnt/mypool/jailmaker
curl --location --remote-name https://raw.githubusercontent.com/Jip-Hop/jailmaker/main/jlmkr.py
chmod +x jlmkr.py
./jlmkr.py install
```

The `jlmkr.py` script (and the jails + config it creates) are now stored on the `jailmaker` dataset and will survive updates of TrueNAS SCALE. If the automatically created `jails` directory is also a ZFS dataset (which is true for new users), then the `jlmkr.py` script will automatically create a new dataset for every jail created. This allows you to snapshot individual jails. For legacy users (where the `jails` directory is not a dataset) each jail will be stored in a plain directory.

A symlink has been created so you can call `jlmkr` from anywhere (unless the boot pool is readonly, which is the default since SCALE 24.04). Additionally shell aliases have been setup, so you can still call `jlmkr` in an interactive shell (even if the symlink couldn't be created).

After an update of TrueNAS SCALE the symlink will be lost (but the shell aliases will remain). To restore the symlink, just run `./jlmkr.py install` again or use [the `./jlmkr.py startup` command](#startup-jails-on-boot).

## Usage

### Create Jail

Creating jail with the default settings is as simple as:

```shell
jlmkr create --start myjail
```

You may also specify a path to a config template, for a quick and consistent jail creation process.

```shell
jlmkr create --start --config /path/to/config/template myjail
```

Or you can override the default config by using flags. See `jlmkr create --help` for the available options. Anything passed after the jail name will be passed to `systemd-nspawn` when starting the jail. See the `systemd-nspawn` manual for available options, specifically [Mount Options](https://manpages.debian.org/bookworm/systemd-container/systemd-nspawn.1.en.html#Mount_Options) and [Networking Options](https://manpages.debian.org/bookworm/systemd-container/systemd-nspawn.1.en.html#Networking_Options) are frequently used.

```shell
jlmkr create --start --distro=ubuntu --release=jammy myjail --bind-ro=/mnt
```

If you omit the jail name, the create process is interactive. You'll be presented with questions which guide you through the process.

```shell
jlmkr create
```

After answering some questions you should have created your first jail (and it should be running if you chose to start it after creating)!

### Startup Jails on Boot

```shell
# Call startup using the absolute path to jlmkr.py
# The jlmkr shell alias doesn't work in Init/Shutdown Scripts
/mnt/mypool/jailmaker/jlmkr.py startup
```

In order to start jails automatically after TrueNAS boots, run `/mnt/mypool/jailmaker/jlmkr.py startup` as Post Init Script with Type `Command` from the TrueNAS web interface. This creates the `jlmkr` symlink (if possible), as well as start all the jails with `startup=1` in the config file.

### Start Jail

```shell
jlmkr start myjail
```

### List Jails

See list of jails (including running, startup state, GPU passthrough, distro, and IP).

```shell
jlmkr list
```

### Execute Command in Jail

You may want to execute a command inside a jail, for example manually from the TrueNAS shell, a shell script or a CRON job. The example below executes the `env` command inside the jail.

```shell
jlmkr exec myjail env
```

This example executes bash inside the jail with a command as additional argument.

```shell
jlmkr exec myjail bash -c 'echo test; echo $RANDOM;'
```

### Edit Jail Config

```shell
jlmkr edit myjail
```

Once you've created a jail, it will exist in a directory inside the `jails` dir next to `jlmkr.py`. For example `/mnt/mypool/jailmaker/jails/myjail` if you've named your jail `myjail`. You may edit the jail configuration file using the `jlmkr edit myjail` command. This opens the config file in your favorite editor, as determined by following [Debian's guidelines](https://www.debian.org/doc/debian-policy/ch-customized-programs.html#editors-and-pagers) on the matter. You'll have to stop the jail and start it again with `jlmkr` for these changes to take effect.

### Remove Jail

Delete a jail and remove it's files (requires confirmation).

```shell
jlmkr remove myjail
```

### Stop Jail

```shell
jlmkr stop myjail
```

### Restart Jail

```shell
jlmkr restart myjail
```

### Jail Shell

Switch into the jail's shell.

```shell
jlmkr shell myjail
```

### Jail Status

```shell
jlmkr status myjail
```

### Jail Logs

View a jail's logs.

```shell
jlmkr log myjail
```

### Additional Commands

Expert users may use the following additional commands to manage jails directly: `machinectl`, `systemd-nspawn`, `systemd-run`, `systemctl` and `journalctl`. The `jlmkr` script uses these commands under the hood and implements a subset of their functions. If you use them directly you will bypass any safety checks or configuration done by `jlmkr` and not everything will work in the context of TrueNAS SCALE.

## Networking

By default a jails will use the same networking namespace, with access to all (physical) interfaces the TrueNAS host has access to. No further setup is required. You may download and install additional packages inside the jail. Note that some ports are already occupied by TrueNAS SCALE (e.g. 443 for the web interface), so your jail can't listen on these ports.

Depending on the service this may be o.k. For example Home Assistant will bind to port 8123, leaving the 80 and 443 ports free from clashes for the TrueNAS web interface. You can then either connect to the service on 8123, or use a reverse proxy such as traefik.

But clashes may happen if you want some services (e.g. traefik) inside the jail to listen on port 443. To workaround this issue when using host networking, you may disable DHCP and add several static IP addresses (Aliases) through the TrueNAS web interface. If you setup the TrueNAS web interface to only listen on one of these IP addresses, the ports on the remaining IP addresses remain available for the jail to listen on.

See [the networking docs](./docs/network.md) for more advanced options (bridge and macvlan networking).

## Docker

Using the [docker config template](./templates/docker/README.md) is recommended if you want to run docker inside the jail. You may of course manually install docker inside a jail. But keep in mind that you need to add `--system-call-filter='add_key keyctl bpf'` (or disable seccomp filtering). It is [not recommended to use host networking for a jail in which you run docker](https://github.com/Jip-Hop/jailmaker/issues/119). Docker needs to manage iptables rules, which it can safely do in its own networking namespace (when using [bridge or macvlan networking](./docs/network.md) for the jail).

## Documentation

Additional documentation can be found in [the docs directory](./docs/) (contributions are welcome!).

## Comparison

TODO: write comparison between systemd-nspawn (without `jailmaker`), LXC, VMs, Docker (on the host).

## Incompatible Distros

The rootfs image `jlmkr.py` downloads comes from the [Linux Containers Image server](https://images.linuxcontainers.org). These images are made for LXC. We can use them with systemd-nspawn too, although not all of them work properly. For example, the `alpine` image doesn't work well. If you stick with common systemd based distros (Debian, Ubuntu, Arch Linux...) you should be fine.

## Filing Issues and Community Support

When in need of help or when you think you've found a bug in jailmaker, [please start with reading this](https://github.com/Jip-Hop/jailmaker/discussions/135).

## References

- [TrueNAS Forum Thread about Jailmaker](https://forums.truenas.com/t/linux-jails-sandboxes-containers-with-jailmaker/417)
- [systemd-nspawn](https://manpages.debian.org/bookworm/systemd-container/systemd-nspawn.1.en.html)
- [machinectl](https://manpages.debian.org/bookworm/systemd-container/machinectl.1.en.html)
- [systemd-run](https://manpages.debian.org/bookworm/systemd/systemd-run.1.en.html)
- [Run docker in systemd-nspawn](https://wiki.archlinux.org/title/systemd-nspawn#Run_docker_in_systemd-nspawn)
- [The original Jailmaker gist](https://gist.github.com/Jip-Hop/4704ba4aa87c99f342b2846ed7885a5d)
