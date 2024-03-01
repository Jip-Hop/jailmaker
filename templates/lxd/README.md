# Ubuntu LXD Jail Template

## Disclaimer

**Experimental. Using LXD in this setup hasn't been extensively tested and has [known issues](#known-issues).**

## Setup

Check out the [config](./config) template file. You may provide it when asked during `jlmkr create` or, if you have the template file stored on your NAS, you may provide it directly by running `jlmkr create --config /mnt/tank/path/to/lxd/config mylxdjail`.

Unfortunately snapd doesn't want to install from the `initial_setup` script inside the config file. So we manually finish the setup by running the following after creating and starting the jail:

```bash
# Repeat listing the jail until you see it has an IPv4 address
jlmkr list

# Install packages
jlmkr exec mylxdjail bash -c 'apt-get update &&
    apt-get install -y --no-install-recommends snapd &&
    snap install lxd'

```

Choose the `dir` storage backend during `lxd init` and answer `yes` to "Would you like the LXD server to be available over the network?"

```bash
jlmkr exec mylxdjail bash -c 'lxd init &&
    snap set lxd ui.enable=true &&
    systemctl reload snap.lxd.daemon'
```

Then visit the `lxd` GUI inside the browser https://0.0.0.0:8443. To find out which IP address to use instead of 0.0.0.0, check the IP address for your jail with `jlmkr list`.

## Known Issues

### Instance creation failed

[LXD no longer has access to the LinuxContainers image server](https://discuss.linuxcontainers.org/t/important-notice-for-lxd-users-image-server/18479).

```
Failed getting remote image info: Failed getting image: The requested image couldn't be found for fingerprint "ubuntu/focal/desktop"
```

### SCALE Virtual Machines
Using LXD in the jail will cause the following error when starting a VM from the TrueNAS SCALE web GUI:

```
[EFAULT] internal error: process exited while connecting to monitor: Could not access KVM kernel module: Permission denied 2024-02-16T14:40:14.886658Z qemu-system-x86_64: -accel kvm: failed to initialize kvm: Permission denied
```

A reboot will resolve the issue (until you start the LXD jail again).

### ZFS Issues

If you create a new dataset on your pool (e.g. `tank`) called `lxd` from the TrueNAS SCALE web GUI and tell LXD to use it during `lxd init`, then you will run into issues. Firstly you'd have to run `apt-get install -y --no-install-recommends zfsutils-linux` inside the jail to install the ZFS userspace utils and you've have to add `--bind=/dev/zfs` to the `systemd_nspawn_user_args` in the jail config. By mounting `/dev/zfs` into this jail, **it will have total control of the storage on the host!**

But then SCALE doesn't seem to like the ZFS datasets created by LXD. I get the following errors when browsing the sub-datasets:

```
[EINVAL] legacy: path must be absolute
```

```
[EFAULT] Failed retreiving USER quotas for tank/lxd/virtual-machines
```

As long as you don't operate on these datasets in the SCALE GUI this may not be a real problem...

However, creating an LXD VM doesn't work with the ZFS storage backend (creating a container works though):

```
Failed creating instance from image: Could not locate a zvol for tank/lxd/images/1555b13f0e89bfcf516bd0090eee6f73a0db5f4d0d36c38cae94316de82bf817.block
```

Could this be the same issue as [Instance creation failed](#instance-creation-failed)?

## More info

Refer to the [Incus README](../incus/README.md) as a lot of it applies to LXD too.

## References

- [Running QEMU/KVM Virtual Machines in Unprivileged LXD Containers](https://dshcherb.github.io/2017/12/04/qemu-kvm-virtual-machines-in-unprivileged-lxd.html)