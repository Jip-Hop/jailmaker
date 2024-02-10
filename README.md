# Jailmaker

Persistent Linux 'jails' on TrueNAS SCALE to install software (docker-compose, portainer, podman, etc.) with full access to all files via bind mounts.

## Disclaimer

**USING THIS SCRIPT IS AT YOUR OWN RISK! IT COMES WITHOUT WARRANTY AND IS NOT SUPPORTED BY IXSYSTEMS.**

## Summary

TrueNAS SCALE can create persistent Linux 'jails' with systemd-nspawn. This script helps with the following:

- Setting up the jail so it won't be lost when you update SCALE
- Choosing a distro (Debian 12 strongly recommended, but Ubuntu, Arch Linux or Rocky Linux seem good choices too)
- Optional: configuring the jail so you can run Docker inside it
- Optional: GPU passthrough (including [nvidia GPU](README.md#nvidia-gpu) with the drivers bind mounted from the host)
- Starting the jail with your config applied

## Security

Despite what the word 'jail' implies, jailmaker's intended use case is to create one or more additional filesystems to run alongside SCALE with minimal isolation. By default the root user in the jail with uid 0 is mapped to the host's uid 0. This has [obvious security implications](https://linuxcontainers.org/lxc/security/#privileged-containers). If this is not acceptable to you, you may lock down the jails by [limiting capabilities](https://manpages.debian.org/bookworm/systemd-container/systemd-nspawn.1.en.html#Security_Options) and/or using [user namespacing](https://manpages.debian.org/bookworm/systemd-container/systemd-nspawn.1.en.html#User_Namespacing_Options) or use a VM instead.

## Installation

[Installation steps with screenshots](https://www.truenas.com/docs/scale/scaletutorials/apps/sandboxes/) are provided on the TrueNAS website. Start by creating a new dataset called `jailmaker` with the default settings (from TrueNAS web interface). Then login as the root user and download `jlmkr.py`.

```shell
cd /mnt/mypool/jailmaker
curl --location --remote-name https://raw.githubusercontent.com/Jip-Hop/jailmaker/main/jlmkr.py
chmod +x jlmkr.py
./jlmkr.py install
```

The `jlmkr.py` script (and the jails + config it creates) are now stored on the `jailmaker` dataset and will survive updates of TrueNAS SCALE. A symlink has been created so you can call `jlmkr` from anywhere (unless the boot pool is readonly, which is the default since SCALE 24.04). Additionally shell aliases have been setup, so you can still call `jlmkr` in an interactive shell (even if the symlink couldn't be created).

After an update of TrueNAS SCALE the symlink will be lost (but the shell aliases will remain). To restore the symlink, just run `./jlmkr.py install` again or use [the `./jlmkr.py startup` command](#startup-jails-on-boot).

## Usage

### Create Jail

Creating a jail is interactive. You'll be presented with questions which guide you through the process.

```shell
jlmkr create myjail
```

After answering a few questions you should have your first jail up and running!

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

```shell
jlmkr list
```

### Execute Command in Jail

You may want to execute a command inside a jail, for example from a shell script or a CRON job. The example below executes the `env` command inside the jail.

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

Once you've created a jail, it will exist in a directory inside the `jails` dir next to `jlmkr.py`. For example `/mnt/mypool/jailmaker/jails/myjail` if you've named your jail `myjail`. You may edit the jail configuration file, e.g. using the `jlmkr edit myjail` command (which uses the nano text editor). You'll have to stop the jail and start it again with `jlmkr` for these changes to take effect.

### Remove Jail

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

```shell
jlmkr shell myjail
```

### Jail Status

```shell
jlmkr status myjail
```

### Jail Logs

```shell
jlmkr log myjail
```

### Additional Commands

Expert users may use the following additional commands to manage jails directly: `machinectl`, `systemd-nspawn`, `systemd-run`, `systemctl` and `journalctl`. The `jlmkr` script uses these commands under the hood and implements a subset of their functions. If you use them directly you will bypass any safety checks or configuration done by `jlmkr` and not everything will work in the context of TrueNAS SCALE.

## Networking

By default the jail will have full access to the host network. No further setup is required. You may download and install additional packages inside the jail. Note that some ports are already occupied by TrueNAS SCALE (e.g. 443 for the web interface), so your jail can't listen on these ports. This is inconvenient if you want to host some services (e.g. traefik) inside the jail. To workaround this issue when using host networking, you may disable DHCP and add several static IP addresses (Aliases) through the TrueNAS web interface. If you setup the TrueNAS web interface to only listen on one of these IP addresses, the ports on the remaining IP addresses remain available for the jail to listen on.

See [Advanced Networking](./NETWORKING.md) for more.

## Docker

The `jailmaker` script won't install Docker for you, but it can setup the jail with the capabilities required to run docker. You can manually install Docker inside the jail using the [official installation guide](https://docs.docker.com/engine/install/#server) or use [convenience script](https://get.docker.com).

## Documentation

Additional documentation contributed by the community can be found in [the docs directory](./docs/).

## Comparison

TODO: write comparison between systemd-nspawn (without `jailmaker`), LXC, VMs, Docker (on the host).

## Incompatible Distros

The rootfs image `jlmkr.py` downloads comes from the [Linux Containers Image server](https://images.linuxcontainers.org). These images are made for LXC. We can use them with systemd-nspawn too, although not all of them work properly. For example, the `alpine` image doesn't work well. If you stick with common systemd based distros (Debian, Ubuntu, Arch Linux...) you should be fine.

## Tips & Tricks

### Colorized bash prompt

To visually distinguish between a root shell inside the jail and a root shell outside the jail, it's possible to colorize the shell prompt. When using a debian jail with the bash shell, you may run the following command to get a yellow prompt inside the jail (will be activated the next time you run `jlmkr shell myjail`):

```bash
echo "PS1='${debian_chroot:+($debian_chroot)}\[\033[01;33m\]\u@\h\[\033[00m\]:\[\033[01;34m\]\w\[\033[00m\]\$ '" >> ~/.bashrc
```

## References

- [TrueNAS Forum Thread about Jailmaker](https://www.truenas.com/community/threads/linux-jails-experimental-script.106926/)
- [systemd-nspawn](https://manpages.debian.org/bullseye/systemd-container/systemd-nspawn.1.en.html)
- [machinectl](https://manpages.debian.org/bullseye/systemd-container/machinectl.1.en.html)
- [systemd-run](https://manpages.debian.org/bullseye/systemd/systemd-run.1.en.html)
- [Run docker in systemd-nspawn](https://wiki.archlinux.org/title/systemd-nspawn#Run_docker_in_systemd-nspawn)
- [The original Jailmaker gist](https://gist.github.com/Jip-Hop/4704ba4aa87c99f342b2846ed7885a5d)
