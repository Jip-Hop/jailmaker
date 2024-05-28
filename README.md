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

## Installation

Beginning with 24.04 (Dragonfish), TrueNAS SCALE officially includes the systemd-nspawn containerization program in the base system. Technically there's nothing to install. You only need the `jlmkr.py` script file in the right place. [Instructions with screenshots](https://www.truenas.com/docs/scale/scaletutorials/apps/sandboxes/) are provided on the TrueNAS website. Start by creating a new dataset called `jailmaker` with the default settings (from TrueNAS web interface). Then login as the root user and download `jlmkr.py`.

```shell
cd /mnt/mypool/jailmaker
curl --location --remote-name https://raw.githubusercontent.com/Jip-Hop/jailmaker/main/jlmkr.py
chmod +x jlmkr.py
```

The `jlmkr.py` script (and the jails + config it creates) are now stored on the `jailmaker` dataset and will survive updates of TrueNAS SCALE. If the automatically created `jails` directory is also a ZFS dataset (which is true for new users), then the `jlmkr.py` script will automatically create a new dataset for every jail created. This allows you to snapshot individual jails. For legacy users (where the `jails` directory is not a dataset) each jail will be stored in a plain directory.

### Alias

Optionally you may create a shell alias for the currently logged in (admin) user to conveniently run `jlmkr.py` without having to change into the `jailmaker` directory or specify the full absolute path. I suggest to create the `jlmkr` alias like this:

```shell
echo "alias jlmkr=\"sudo '/mnt/mypool/jailmaker/jlmkr.py'\"" > ~/.bashrc
```

Please replace `/mnt/mypool/jailmaker/` with the actual path to where you stored `jlmkr.py`. If you're using zsh instead of bash, then you should replace `.bashrc` in the command above with `.zshrc`. If you've created the alias, you may use it instead of `./jlmkr.py`.

## Usage

### Create Jail

Creating a jail with the default settings is as simple as:

```shell
./jlmkr.py create --start myjail
```

You may also specify a path to a config template, for a quick and consistent jail creation process.

```shell
./jlmkr.py create --start --config /path/to/config/template myjail
```

Or you can override the default config by using flags. See `./jlmkr.py create --help` for the available options. Anything passed after the jail name will be passed to `systemd-nspawn` when starting the jail. See the `systemd-nspawn` manual for available options, specifically [Mount Options](https://manpages.debian.org/bookworm/systemd-container/systemd-nspawn.1.en.html#Mount_Options) and [Networking Options](https://manpages.debian.org/bookworm/systemd-container/systemd-nspawn.1.en.html#Networking_Options) are frequently used.

```shell
./jlmkr.py create --start --distro=ubuntu --release=jammy myjail --bind-ro=/mnt
```

If you omit the jail name, the create process is interactive. You'll be presented with questions which guide you through the process.

```shell
./jlmkr.py create
```

After answering some questions you should have created your first jail (and it should be running if you chose to start it after creating)!

### Startup Jails on Boot

```shell
# Call startup using the absolute path to jlmkr.py
/mnt/mypool/jailmaker/jlmkr.py startup
```

In order to start jails automatically after TrueNAS boots, run `/mnt/mypool/jailmaker/jlmkr.py startup` as Post Init Script with Type `Command` from the TrueNAS web interface. This will start all the jails with `startup=1` in the config file.

### Start Jail

```shell
./jlmkr.py start myjail
```

### List Jails

See list of jails (including running, startup state, GPU passthrough, distro, and IP).

```shell
./jlmkr.py list
```

### Execute Command in Jail

You may want to execute a command inside a jail, for example manually from the TrueNAS shell, a shell script or a CRON job. The example below executes the `env` command inside the jail.

```shell
./jlmkr.py exec myjail env
```

This example executes bash inside the jail with a command as additional argument.

```shell
./jlmkr.py exec myjail bash -c 'echo test; echo $RANDOM;'
```

### Edit Jail Config

```shell
./jlmkr.py edit myjail
```

Once you've created a jail, it will exist in a directory inside the `jails` dir next to `jlmkr.py`. For example `/mnt/mypool/jailmaker/jails/myjail` if you've named your jail `myjail`. You may edit the jail configuration file using the `./jlmkr.py edit myjail` command. This opens the config file in your favorite editor, as determined by following [Debian's guidelines](https://www.debian.org/doc/debian-policy/ch-customized-programs.html#editors-and-pagers) on the matter. You'll have to stop the jail and start it again with `jlmkr` for these changes to take effect.

### Remove Jail

Delete a jail and remove it's files (requires confirmation).

```shell
./jlmkr.py remove myjail
```

### Stop Jail

```shell
./jlmkr.py stop myjail
```

### Restart Jail

```shell
./jlmkr.py restart myjail
```

### Jail Shell

Switch into the jail's shell.

```shell
./jlmkr.py shell myjail
```

### Jail Status

```shell
./jlmkr.py status myjail
```

### Jail Logs

View a jail's logs.

```shell
./jlmkr.py log myjail
```

### Additional Commands

Expert users may use the following additional commands to manage jails directly: `machinectl`, `systemd-nspawn`, `systemd-run`, `systemctl` and `journalctl`. The `jlmkr` script uses these commands under the hood and implements a subset of their functions. If you use them directly you will bypass any safety checks or configuration done by `jlmkr` and not everything will work in the context of TrueNAS SCALE.

## Security

By default the root user in the jail with uid 0 is mapped to the host's uid 0. This has [obvious security implications](https://linuxcontainers.org/lxc/security/#privileged-containers). If this is not acceptable to you, you may lock down the jails by [limiting capabilities](https://manpages.debian.org/bookworm/systemd-container/systemd-nspawn.1.en.html#Security_Options) and/or using [user namespacing](https://manpages.debian.org/bookworm/systemd-container/systemd-nspawn.1.en.html#User_Namespacing_Options) or use a VM instead.

### Seccomp
Seccomp is a Linux kernel feature that restricts programs from making unauthorized system calls.  This means that when seccomp is enabled there can be times where a process run inside a jail will be killed with the error "Operation not permitted."  In order to find out which syscall needs to be added to the `--system-call-filter=` configuration you can use `strace`.  

For example:
```
# /usr/bin/intel_gpu_top
Failed to initialize PMU! (Operation not permitted)

# strace /usr/bin/intel_gpu_top 2>&1 |grep Operation\ not\ permitted
perf_event_open({type=0x10 /* PERF_TYPE_??? */, size=PERF_ATTR_SIZE_VER7, config=0x100002, sample_period=0, sample_type=0, read_format=PERF_FORMAT_TOTAL_TIME_ENABLED|PERF_FORMAT_GROUP, precise_ip=0 /* arbitrary skid */, use_clockid=1, ...}, -1, 0, -1, 0) = -1 EPERM (Operation not permitted)
write(2, "Failed to initialize PMU! (Opera"..., 52Failed to initialize PMU! (Operation not permitted)
```
The syscall that needs to be added to the `--system-call-filter` option in the `jailmaker` config in this case would be `perf_event_open`. You may need to run strace multiple times.

Seccomp is important for security, but as a last resort can be disabled by setting `seccomp=0` in the jail config.

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

When in need of help or when you think you've found a bug in `jailmaker`, [please start with reading this](https://github.com/Jip-Hop/jailmaker/discussions/135).

## References

- [TrueNAS Forum Thread about Jailmaker](https://forums.truenas.com/t/linux-jails-sandboxes-containers-with-jailmaker/417)
- [systemd-nspawn](https://manpages.debian.org/bookworm/systemd-container/systemd-nspawn.1.en.html)
- [machinectl](https://manpages.debian.org/bookworm/systemd-container/machinectl.1.en.html)
- [systemd-run](https://manpages.debian.org/bookworm/systemd/systemd-run.1.en.html)
- [Run docker in systemd-nspawn](https://wiki.archlinux.org/title/systemd-nspawn#Run_docker_in_systemd-nspawn)
- [The original Jailmaker gist](https://gist.github.com/Jip-Hop/4704ba4aa87c99f342b2846ed7885a5d)
