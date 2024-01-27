# Incus / LXD / LXC / KVM inside jail

## Disclaimer

**These notes are a work in progress. Using Incus in this setup hasn't been extensively tested.**

## Prerequisites

- TrueNAS SCALE 23.10 installed bare metal (not inside VM)
- Jailmaker installed
- Setup bridge networking (see Advanced Networking in the readme)

## Installation

Create a debian 12 jail and [install incus](https://github.com/zabbly/incus#installation). Also install the `incus-ui-canonical` package to install the web interface. Ensure the config file looks like the below:

Run `modprobe vhost_vsock` on the TrueNAS host.

```
startup=0
docker_compatible=1
gpu_passthrough_intel=1
gpu_passthrough_nvidia=0
systemd_nspawn_user_args=--network-bridge=br1 --resolv-conf=bind-host --bind=/dev/fuse --bind=/dev/kvm --bind=/dev/vsock --bind=/dev/vhost-vsock
# You generally will not need to change the options below
systemd_run_default_args=--property=KillMode=mixed --property=Type=notify --property=RestartForceExitStatus=133 --property=SuccessExitStatus=133 --property=Delegate=yes --property=TasksMax=infinity --collect --setenv=SYSTEMD_NSPAWN_LOCK=0
systemd_nspawn_default_args=--keep-unit --quiet --boot
```

Check out [First steps with Incus](https://linuxcontainers.org/incus/docs/main/tutorial/first_steps/).

## Create Ubuntu Desktop VM

Incus web GUI should be running on port 8443. Create new instance, call it `dekstop`, and choose the `Ubuntu	jammy desktop virtual-machine ubuntu/22.04/desktop` image.

## Bind mount / virtiofs

To access files from the TrueNAS host directly in a VM created with incus, we can use virtiofs.

```bash
incus config device add desktop test disk source=/home/test/ path=/mnt/test
```

The command above (when ran as root user inside the incus jail) adds a new virtiofs mount of a test directory inside the jail to a VM named desktop. The `/home/test` dir resides in the jail, but you can first bind mount any directory from the TrueNAS host inside the incus jail and then forward this to the VM using virtiofs. This could be an alternative to NFS mounts.

### Benchmarks

#### Inside LXD ubuntu desktop VM with virtiofs mount
root@desktop:/mnt/test# mount | grep test
incus_test on /mnt/test type virtiofs (rw,relatime)
root@desktop:/mnt/test# time iozone -a
[...]
real    2m22.389s
user    0m2.222s
sys     0m59.275s

#### In a jailmaker jail on the host:
root@incus:/home/test# time iozone -a
[...]
real	0m59.486s
user	0m1.468s
sys	0m25.458s

#### Inside LXD ubuntu desktop VM with virtiofs mount
root@desktop:/mnt/test# dd if=/dev/random of=./test1.img bs=1G count=1 oflag=dsync
1+0 records in
1+0 records out
1073741824 bytes (1.1 GB, 1.0 GiB) copied, 36.321 s, 29.6 MB/s

#### In a jailmaker jail on the host:
root@incus:/home/test# dd if=/dev/random of=./test2.img bs=1G count=1 oflag=dsync
1+0 records in
1+0 records out
1073741824 bytes (1.1 GB, 1.0 GiB) copied, 7.03723 s, 153 MB/s

## Create Ubuntu container

To be able to create unprivileged (rootless) containers with incus inside the jail, you need to increase the amount of UIDs available inside the jail. Please refer to the [Podman instructions](rootless_podman_in_rootless_jail.md) for more information. If you don't increase the UIDs you can only create privileged containers. You'd have to change `Privileged` to `Allow` in `Security policies` in this case.

## Canonical LXD install via snap

Installing the lxd snap is an alternative to Incus. But out of the box running `snap install lxd` will cause AppArmor issues when running inside a jailmaker jail on SCALE.

### Workaround 1: Disable AppArmor kernel module

[To my knowledge AppArmor is not uses on SCALE](https://github.com/truenas/charts/pull/428#issuecomment-1113936420). The AppArmor related packages aren't even installed.

Ensure to add --bind=/dev/fuse and ensure using bridge or macvlan networking:

```
# On the host
cat /sys/module/apparmor/parameters/enabled
Y
midclt call system.advanced.update '{"kernel_extra_options": "apparmor=0"}'
reboot
cat /sys/module/apparmor/parameters/enabled

# In Ubuntu jail
apt update
ln -s /bin/true /usr/local/bin/udevadm
apt install -y --no-install-recommends snapd
snap install lxd
lxd init
snap set lxd ui.enable=true
systemctl reload snap.lxd.daemon

# Check out: https://example:8443
```

### Workaround 2: inaccessible /sys/module/apparmor

If I don't want to mess with kernel parameters, I can trick the jail into thinking the apparmor module is not loaded by mounting over /sys/module/apparmor: `mount -v -r -t tmpfs -o size=50m test /sys/module/apparmor`. Then `snap install lxd` completes! Best way to do this is to add `--inaccessible=/sys/module/apparmor` to the systemd_nspawn_user_args.

## References

- [Running QEMU/KVM Virtual Machines in Unprivileged LXD Containers](https://dshcherb.github.io/2017/12/04/qemu-kvm-virtual-machines-in-unprivileged-lxd.html)