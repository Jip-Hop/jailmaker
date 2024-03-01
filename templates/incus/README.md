# Debian Incus Jail Template (LXD / LXC / KVM)

## Disclaimer

**Experimental. Using Incus in this setup hasn't been extensively tested and has [known issues](#known-issues).**

## Setup

Check out the [config](./config) template file. You may provide it when asked during `jlmkr create` or, if you have the template file stored on your NAS, you may provide it directly by running `jlmkr create --config /mnt/tank/path/to/incus/config myincusjail`.

Unfortunately incus doesn't want to install from the `initial_setup` script inside the config file. So we manually finish the setup by running the following after creating and starting the jail:

```bash
jlmkr exec myincusjail bash -c 'apt-get -y install incus incus-ui-canonical &&
    incus admin init'
```    

Follow [First steps with Incus](https://linuxcontainers.org/incus/docs/main/tutorial/first_steps/).

Then visit the Incus GUI inside the browser https://0.0.0.0:8443. To find out which IP address to use instead of 0.0.0.0, check the IP address for your jail with `jlmkr list`.

## Known Issues

Using Incus in the jail will cause the following error when starting a VM from the TrueNAS SCALE web GUI:

```
[EFAULT] internal error: process exited while connecting to monitor: Could not access KVM kernel module: Permission denied 2024-02-16T14:40:14.886658Z qemu-system-x86_64: -accel kvm: failed to initialize kvm: Permission denied
```

A reboot will resolve the issue (until you start the Incus jail again).

## Create Ubuntu Desktop VM

Incus web GUI should be running on port 8443. Create new instance, call it `desktop`, and choose the `Ubuntu	jammy desktop virtual-machine ubuntu/22.04/desktop` image.

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

To be able to create unprivileged (rootless) containers with incus inside the jail, you need to increase the amount of UIDs available inside the jail. Please refer to the [Podman instructions](../podman/README.md) for more information. If you don't increase the UIDs you can only create privileged containers. You'd have to change `Privileged` to `Allow` in `Security policies` in this case.

## References

- [Running QEMU/KVM Virtual Machines in Unprivileged LXD Containers](https://dshcherb.github.io/2017/12/04/qemu-kvm-virtual-machines-in-unprivileged-lxd.html)