# Rootless podman in rootless Fedora jail

## Disclaimer

**These notes are a work in progress. Using podman in this setup hasn't been extensively tested.**

## Installation

Prerequisites. Installed jailmaker and setup bridge networking.

Run `jlmkr create rootless` to create a new jail. During jail creation choose fedora 39. This way we get the most recent version of podman available. Don't enable docker compatibility, we're going to enable only the required options manually.

Add `--network-bridge=br1 --resolv-conf=bind-host --system-call-filter='add_key keyctl bpf' --private-users=524288:65536 --private-users-ownership=chown` when asked for additional systemd-nspawn flags during jail creation.

We start at UID 524288, as this is the [systemd range used for containers](https://github.com/systemd/systemd/blob/main/docs/UIDS-GIDS.md#summary).

The `--private-users-ownership=chown` option will ensure the rootfs ownership is corrected.

After the jail has started run `jlmkr stop rootless && jlmkr edit rootless`, remove `--private-users-ownership=chown` and increase the UID range to `131072` to double the number of UIDs available in the jail. We need more than 65536 UIDs available in the jail, since rootless podman also needs to be able to map UIDs. If I leave the `--private-users-ownership=chown` option I get the following error:

> systemd-nspawn[678877]: Automatic UID/GID adjusting is only supported for UID/GID ranges starting at multiples of 2^16 with a range of 2^16

The flags look like this now:

```
systemd_nspawn_user_args=--network-bridge=br1 --resolv-conf=bind-host --system-call-filter='add_key keyctl bpf' --private-users=524288:131072
```

For some reason the network inside the jail doesn't come up by default. Correct this manually.

Run the following from the TrueNAS host, from inside your jailmaker directory.

```bash
nano jails/rootless/rootfs/lib/systemd/network/80-container-host0.network
# Manually set LinkLocalAddressing=yes to LinkLocalAddressing=ipv6
```

Start the jail with `jlmkr start rootless` and open a shell session inside the jail (as the remapped root user) with `jlmkr shell rootless`.

Then inside the jail start the network services (wait to get IP address via DHCP) and install podman:
```bash
systemctl  enable  systemd-networkd
systemctl  start   systemd-networkd

# Add the required capabilities to the `newuidmap` and `newgidmap` binaries.
# https://github.com/containers/podman/issues/2788#issuecomment-1016301663
# https://github.com/containers/podman/issues/2788#issuecomment-479972943
# https://github.com/containers/podman/issues/12637#issuecomment-996524341
setcap cap_setuid+eip /usr/bin/newuidmap
setcap cap_setgid+eip /usr/bin/newgidmap

# Create new user
adduser rootless

# Clear the subuids and subgids which have been assigned by default when creating the new user
usermod --del-subuids 0-4294967295 --del-subgids 0-4294967295 rootless
# Set a specific range, so it fits inside the number of available UIDs
usermod --add-subuids 65536-131071 --add-subgids 65536-131071 rootless
# Check the assigned range
cat /etc/subuid
# Check the available range
cat /proc/self/uid_map

dnf -y install podman
exit
```

From the TrueNAS host, open a shell as the rootless user inside the jail.

```bash
machinectl shell --uid 1000 rootless
```

Run rootless podman as user 1000.

```bash
id
podman run hello-world
podman info
```

The output of podman info should contain:

```
  graphDriverName: overlay
  graphOptions: {}
  graphRoot: /home/rootless/.local/share/containers/storage
  [...]
  graphStatus:
    Backing Filesystem: zfs
    Native Overlay Diff: "true"
    Supports d_type: "true"
    Supports shifting: "false"
    Supports volatile: "true"
    Using metacopy: "false"
```

## TODO:
On truenas host do:
sudo sysctl net.ipv4.ip_unprivileged_port_start=23
> Which would prevent a process by your user impersonating the sshd daemon.
Actually make it persistent.

## Additional resources:

Resources mentioning `add_key keyctl bpf`
- https://bbs.archlinux.org/viewtopic.php?id=252840
- https://wiki.archlinux.org/title/systemd-nspawn
- https://discourse.nixos.org/t/podman-docker-in-nixos-container-ideally-in-unprivileged-one/22909/12
Resources mentioning `@keyring`
- https://github.com/systemd/systemd/issues/17606
- https://github.com/systemd/systemd/blob/1c62c4fe0b54fb419b875cb2bae82a261518a745/src/shared/seccomp-util.c#L604
`@keyring` also includes `request_key` but doesn't include `bpf`