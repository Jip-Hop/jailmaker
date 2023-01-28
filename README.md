# Jailmaker

Persistent Linux 'jails' on TrueNAS SCALE to install software (docker-compose, portainer, podman, etc.) with full access to all files via bind mounts. Without modifying the host OS at all thanks to systemd-nspawn! 

## Disclaimer

**USING THIS SCRIPT IS AT YOUR OWN RISK! IT COMES WITHOUT WARRANTY AND IS NOT SUPPORTED BY IXSYSTEMS.**

The systemd-container package may be removed from a future release of TrueNAS SCALE without warning. If that happens, you may be unable to start jails create with `jlmkr.sh`. The jail itself and the files within it will not be lost, but in order to start your jail you'd have to reinstall systemd-container, roll back to the previous release or migrate to LXC [if iXsystems includes it](https://ixsystems.atlassian.net/browse/NAS-114193?focusedCommentId=175214). Since systemd-container comes by default with Debian on which SCALE is built, I don't think it will be removed. But there's no guarantee!

## Summary

TrueNAS SCALE already has everything onboard to create persistent Linux 'jails' with systemd-nspawn. This script helps with the following:

- Setting up the jail so it won't be lost when you update SCALE
- Choosing a distro (Debian 11 strongly recommended, but Ubuntu, Arch Linux or Rocky Linux seem good choices too)
- Optional: configuring the jail so you can run Docker inside it
- Optional: GPU passthrough (including nvidia GPU with the drivers bind mounted from the host)
- Starting the jail with your config applied

## Installation

Create a new dataset called `jailmaker` with the default settings (from TrueNAS web interface). Then login as the root user and download `jlmkr.sh`.

```shell
cd /mnt/mypool/jailmaker
curl --location --remote-name https://raw.githubusercontent.com/Jip-Hop/jailmaker/main/jlmkr.sh
chmod +x jlmkr.sh
```

The `jlmkr.sh` script (and the jails + config it creates) are now stored on the `jailmaker` dataset and will survive updates of TrueNAS SCALE.

## Create Jail

Creating a jail is interactive. You'll be presented with questions which guide you through the process. The rootfs image it downloads comes from the [Linux Containers Image server](https://images.linuxcontainers.org). These images are made for LXC, but we can use them too (although not all of them).

```shell
./jlmkr.sh create myjail
```

## Start Jail

```shell
./jlmkr.sh start myjail
```

### Autostart Jail on Boot

In order to start a jail automatically after TrueNAS boots, run `/mnt/mypool/jailmaker/jlmkr.sh start myjail` as Post Init Script with Type `Command` from the TrueNAS web interface.

## Additional Commands

For additional commands we can use `machinectl`, `systemctl` and `journalctl` directly. The `jlmkr.sh` script does not play a role here.

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

## Edit Jail Config

Once you've created a jail, it will exist in a directory inside the `jails` dir next to `jlmkr.sh`. For example `./jails/myjail` if you've named your jail `myjail`. You may edit the jail configuration file. You'll have to stop the jail and start it again with `jlmkr.sh` for these changes to take effect.

## Networking

By default the jail will have full access to the host network. No further setup is required. You may download and install additional packages inside the jail. Note that some ports are already occupied by TrueNAS SCALE (e.g. 443 for the web interface), so your jail can't listen on these ports. This is inconvenient if you want to host some services (e.g. traefik) inside the jail. To workaround this issue when using host networking, you may disable DHCP and add several static IP addresses (Aliases) through the TrueNAS web interface. If you setup the TrueNAS web interface to only listen on one of these IP addresses, the ports on the remaining IP addresses remain available for the jail to listen on.

See [Advanced Networking](./NETWORKING.md) for more.

## Docker

Jailmaker won't install Docker for you, but it can setup the jail with the capabilities required to run docker. You can manually install Docker inside the jail using the [official installation guide](https://docs.docker.com/engine/install/#server) or use [convenience script](https://get.docker.com).

## Comparison

TODO: write comparison between systemd-nspawn (without jailmaker), LXC, VMs, Docker (on the host).

## References

- [systemd-nspawn](https://manpages.debian.org/bullseye/systemd-container/systemd-nspawn.1.en.html)
- [machinectl](https://manpages.debian.org/bullseye/systemd-container/machinectl.1.en.html)
- [systemd-run](https://manpages.debian.org/bullseye/systemd/systemd-run.1.en.html)
- [Run docker in systemd-nspawn](https://wiki.archlinux.org/title/systemd-nspawn#Run_docker_in_systemd-nspawn)
- [The original Jailmaker gist](https://gist.github.com/Jip-Hop/4704ba4aa87c99f342b2846ed7885a5d)