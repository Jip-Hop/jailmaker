# Fedora Podman Jail Template

Check out the [config](./config) template file. You may provide it when asked during `jlmkr create` or, if you have the template file stored on your NAS, you may provide it directly by running `jlmkr create mypodmanjail /mnt/tank/path/to/podman/config`.

## Rootless

### Disclaimer

**These notes are a work in progress. Using podman in this setup hasn't been extensively tested.**

### Installation

Prerequisites: created a jail using the [config](./config) template file.

Run `jlmkr edit mypodmanjail` and add `--private-users=524288:65536 --private-users-ownership=chown` to `systemd_nspawn_user_args`. We start at UID 524288, as this is the [systemd range used for containers](https://github.com/systemd/systemd/blob/main/docs/UIDS-GIDS.md#summary).

The `--private-users-ownership=chown` option will ensure the rootfs ownership is corrected.

After the jail has started run `jlmkr stop mypodmanjail && jlmkr edit mypodmanjail`, remove `--private-users-ownership=chown` and increase the UID range to `131072` to double the number of UIDs available in the jail. We need more than 65536 UIDs available in the jail, since rootless podman also needs to be able to map UIDs. If I leave the `--private-users-ownership=chown` option I get the following error:

> systemd-nspawn[678877]: Automatic UID/GID adjusting is only supported for UID/GID ranges starting at multiples of 2^16 with a range of 2^16

The flags look like this now:

```
systemd_nspawn_user_args=--network-macvlan=eno1
    --resolv-conf=bind-host
    --system-call-filter='add_key keyctl bpf'
    --private-users=524288:131072
```

Start the jail with `jlmkr start mypodmanjail` and open a shell session inside the jail (as the remapped root user) with `jlmkr shell mypodmanjail`.

Then inside the jail setup the new rootless user:

```bash
# Create new user
adduser rootless
# Set password for user
passwd rootless

# Clear the subuids and subgids which have been assigned by default when creating the new user
usermod --del-subuids 0-4294967295 --del-subgids 0-4294967295 rootless
# Set a specific range, so it fits inside the number of available UIDs
usermod --add-subuids 65536-131071 --add-subgids 65536-131071 rootless

# Check the assigned range
cat /etc/subuid
# Check the available range
cat /proc/self/uid_map

exit
```

From the TrueNAS host, open a shell as the rootless user inside the jail.

```bash
jlmkr shell --uid 1000 mypodmanjail
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

### Binding to Privileged Ports:

Add `sysctl net.ipv4.ip_unprivileged_port_start=23` to the `pre_start_hook` inside the config to lower the range of privileged ports. This will still prevent an unprivileged process from impersonating the sshd daemon. Since this lowers the range globally on the TrueNAS host, a better solution would be to specifically add the capability to bind to privileged ports.

## Cockpit Management

Install and enable cockpit:

```bash
jlmkr exec mypodmanjail bash -c "dnf -y install cockpit cockpit-podman && \
  systemctl enable --now cockpit.socket && \
  ip a &&
  ip route | awk '/default/ { print \$9 }'"
```

Check the IP address of the jail and access the Cockpit web interface at https://0.0.0.0:9090 where 0.0.0.0 is the IP address you just found using `ip a`.

If you've setup the `rootless` user, you may login with the password you've created earlier. Otherwise you'd have to add an admin user first:

```bash
jlmkr exec podmantest bash -c 'adduser admin
passwd admin
usermod -aG wheel admin'
```

Click on `Podman containers`. In case it shows `Podman service is not active` then click `Start podman`. You can now manage your (rootless) podman containers in the (rootless) jailmaker jail using the Cockpit web GUI.

## Additional Resources:

Resources mentioning `add_key keyctl bpf`
- https://bbs.archlinux.org/viewtopic.php?id=252840
- https://wiki.archlinux.org/title/systemd-nspawn
- https://discourse.nixos.org/t/podman-docker-in-nixos-container-ideally-in-unprivileged-one/22909/12
Resources mentioning `@keyring`
- https://github.com/systemd/systemd/issues/17606
- https://github.com/systemd/systemd/blob/1c62c4fe0b54fb419b875cb2bae82a261518a745/src/shared/seccomp-util.c#L604
`@keyring` also includes `request_key` but doesn't include `bpf`