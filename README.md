# Jailmaker

Persistent Linux 'jails' on TrueNAS SCALE to install software (docker-compose, portainer, podman, etc.) with full access to all files via bind mounts.

## Disclaimer

**USING THIS SCRIPT IS AT YOUR OWN RISK! IT COMES WITHOUT WARRANTY AND IS NOT SUPPORTED BY IXSYSTEMS.**

Update: 15-6-2023. Looks like the `systemd-container` package has been removed since 22.12.3...

The systemd-container package may be removed from a future release of TrueNAS SCALE without warning ([unless it gets integrated](https://ixsystems.atlassian.net/browse/NAS-119787)). If that happens, you may be unable to start jails create with `jlmkr.py`. The jail itself and the files within it will not be lost, but in order to start your jail you'd have to reinstall systemd-container, roll back to the previous release or migrate to LXC [if iXsystems includes that](https://ixsystems.atlassian.net/browse/NAS-114193?focusedCommentId=175214). Since systemd-container comes by default with Debian on which SCALE is built, I don't think it will be removed. But there's no guarantee!

**THIS SCRIPT NEEDS MORE COMMUNITY TESTING BEFORE ITS FIRST 1.0.0 RELEASE.**

## Summary

TrueNAS SCALE already has everything onboard to create persistent Linux 'jails' with systemd-nspawn. This script helps with the following:

- Setting up the jail so it won't be lost when you update SCALE
- Choosing a distro (Debian 11 strongly recommended, but Ubuntu, Arch Linux or Rocky Linux seem good choices too)
- Optional: configuring the jail so you can run Docker inside it
- Optional: GPU passthrough (including [nvidia GPU](README.md#nvidia-gpu) with the drivers bind mounted from the host)
- Starting the jail with your config applied

## Installation

Create a new dataset called `jailmaker` with the default settings (from TrueNAS web interface). Then login as the root user and download `jlmkr.py`.

```shell
cd /mnt/mypool/jailmaker
curl --location --remote-name https://raw.githubusercontent.com/Jip-Hop/jailmaker/main/jlmkr.py
chmod +x jlmkr.py
```

The `jlmkr.py` script (and the jails + config it creates) are now stored on the `jailmaker` dataset and will survive updates of TrueNAS SCALE.

## Create Jail

Creating a jail is interactive. You'll be presented with questions which guide you through the process.

```shell
./jlmkr.py create myjail
```

After answering a few questions you should have your first jail up and running!

### Autostart Jail on Boot

In order to start a jail automatically after TrueNAS boots, run `/mnt/mypool/jailmaker/jlmkr.py start myjail` as Post Init Script with Type `Command` from the TrueNAS web interface.

## Additional Commands

### Start Jail

```shell
./jlmkr.py start myjail
```

### List Jails

```shell
./jlmkr.py list
```

### Remove Jail

```shell
./jlmkr.py remove myjail
```

For additional commands we can use `machinectl`, `systemctl` and `journalctl` directly. The `jlmkr.py` script does not play a role here.

### Stop Jail

```shell
machinectl stop myjail
```

### Jail Shell

```shell
machinectl shell myjail
```

### Jail Status

```shell
systemctl status jlmkr-myjail
```

### Jail Logs

```shell
journalctl -u jlmkr-myjail
```

### Run Command in Jail

If you want to run a command inside a jail, for example from a shell script or a CRON job, you may use `systemd-run` with the `--machine` flag. The example below runs the `env` command inside the jail.

```
systemd-run --machine myjail --quiet --pipe --wait --collect --service-type=exec env
```

## Edit Jail Config

Once you've created a jail, it will exist in a directory inside the `jails` dir next to `jlmkr.py`. For example `./jails/myjail` if you've named your jail `myjail`. You may edit the jail configuration file. You'll have to stop the jail and start it again with `jlmkr.py` for these changes to take effect.

## Networking

By default the jail will have full access to the host network. No further setup is required. You may download and install additional packages inside the jail. Note that some ports are already occupied by TrueNAS SCALE (e.g. 443 for the web interface), so your jail can't listen on these ports. This is inconvenient if you want to host some services (e.g. traefik) inside the jail. To workaround this issue when using host networking, you may disable DHCP and add several static IP addresses (Aliases) through the TrueNAS web interface. If you setup the TrueNAS web interface to only listen on one of these IP addresses, the ports on the remaining IP addresses remain available for the jail to listen on.

See [Advanced Networking](./NETWORKING.md) for more.

## Docker

Jailmaker won't install Docker for you, but it can setup the jail with the capabilities required to run docker. You can manually install Docker inside the jail using the [official installation guide](https://docs.docker.com/engine/install/#server) or use [convenience script](https://get.docker.com).

## Nvidia GPU

To make passthrough of the nvidia GPU work, you need to schedule a Pre Init command. The reason is that TrueNAS SCALE by default doesn't load the nvidia kernel modules (and jailmaker doesn't do that either). [This screenshot](https://user-images.githubusercontent.com/1704047/222915803-d6dd51b0-c4dd-4189-84be-a04d38cca0b3.png) shows what the configuration should look like.

```
[ ! -f /dev/nvidia-uvm ] && modprobe nvidia-current-uvm && /usr/bin/nvidia-modprobe -c0 -u
```

## Comparison

TODO: write comparison between systemd-nspawn (without jailmaker), LXC, VMs, Docker (on the host).

## Known Issues

### Incompatible Distros

The rootfs image `jlmkr.py` downloads comes from the [Linux Containers Image server](https://images.linuxcontainers.org). These images are made for LXC. We can use them with systemd-nspawn too, although not all of them work properly. For example, the `alpine` image doesn't work well. If you stick with common systemd based distros (Debian, Ubuntu, Arch Linux...) you should be fine.

## References

- [systemd-nspawn](https://manpages.debian.org/bullseye/systemd-container/systemd-nspawn.1.en.html)
- [machinectl](https://manpages.debian.org/bullseye/systemd-container/machinectl.1.en.html)
- [systemd-run](https://manpages.debian.org/bullseye/systemd/systemd-run.1.en.html)
- [Run docker in systemd-nspawn](https://wiki.archlinux.org/title/systemd-nspawn#Run_docker_in_systemd-nspawn)
- [The original Jailmaker gist](https://gist.github.com/Jip-Hop/4704ba4aa87c99f342b2846ed7885a5d)
