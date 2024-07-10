# Jailmaker Docs

## Host Networking

[Notes on the default host networking are in the main README.md file](../README.md#networking).

## Bridge Networking

As an alternative to the default host networking mode, you may want to connect to a bridge interface instead and let the jail obtain its IP address via DHCP.

[![TrueNAS Scale: Setting up a Static IP and Network Bridge // Access NAS host from VM - YouTube Video](https://img.youtube.com/vi/uPkoeWUfiHU/0.jpg)<br>Watch on YouTube](https://www.youtube.com/watch?v=uPkoeWUfiHU "TrueNAS Scale: Setting up a Static IP and Network Bridge // Access NAS host from VM - YouTube Video")

The above YouTube video may be helpful when setting up the bridge interface.

### Bridge Flaws

This type of interface takes much longer to set up both in complexity and wait time (you may have to be patient for up to 90 seconds after the jail started for networking to work, [assigning the IP address via DHCP is slow by default because STP is enabled](https://github.com/Jip-Hop/jailmaker/issues/90#issuecomment-2162032080)). Furthermore, if the configuration is not correct it can render your TrueNAS inaccessible via ssh or the web interface, necessitating a reset using a keyboard and monitor plugged into the TrueNAS server and use `/etc/netcli` to reset the networking interface.

### Bridge Setup

Add the `--network-bridge=br1 --resolv-conf=bind-host` systemd-nspawn flag when asked for `Additional flags` during jail creation, or set it post-creation by [editing](./README.md#edit-jail-config) the `SYSTEMD_NSPAWN_USER_ARGS` variable inside the `config` file.

The TrueNAS host and the jail will be able to communicate with each other as if the jail was just another device on the LAN. It will use the same DNS servers as the TrueNAS host because the `--resolv-conf=bind-host` option bind mounts the `/etc/resolv.conf` file from the host inside the jail. If you want to use the DNS servers advertised via DHCP, then check [DNS via DHCP](#dns-via-dhcp).

### Bridge Static IP
To configure a static IP with our bridge interface, we need to edit the `/etc/systemd/network/80-container-host0.network` file. Change the [Network] section to look like this:

```ini
[Network]
DHCP=false
Address=192.168.0.12/24
Gateway=192.168.0.1
LinkLocalAddressing=no
LLDP=yes
EmitLLDP=customer-bridge
```
Then restart the `systemd-networkd` service and check your network configuration.

```shell
systemctl restart systemd-networkd
systemctl status systemd-networkd
ifconfig
```

### Multiple Bridge Interfaces
[Systemd-nspawn](https://www.freedesktop.org/software/systemd/man/latest/systemd-nspawn.html), the technology on which jailmaker is built, [currently](https://github.com/systemd/systemd/issues/11087) only supports the definition and automatic configuration of a single bridge interface via the [`--network-bridge`](https://www.freedesktop.org/software/systemd/man/latest/systemd-nspawn.html#--network-bridge=) argument. In some cases however, for instance when trying to utilize different vlan interfaces, it can be useful to configure multiple bridge interfaces within a jail. It is possible to create extra interfaces and join them to host bridges manually with systemd-nspwan using a combination of the [`--network-veth-extra`](https://www.freedesktop.org/software/systemd/man/latest/systemd-nspawn.html#--network-veth-extra=) argument and a service config containing `ExecStartPost` commands as outlined [here](https://wiki.csclub.uwaterloo.ca/Systemd-nspawn#Multiple_network_interfaces).

The `--network-veth-extra` argument instructs system-nspawn to create an addition linked interface between the host and jail and uses a syntax of
```
--network-veth-extra=<host_interface_name>:<jail_interface_name>
```

The service config `ExecStartPost` commands is then used to add the host side of the interface link to an existing host bridge and bring the interface up. Jailmaker has simplified this process by including a `post_start_hook` configuration parameter which can automate the creation of the service config by including the `ExecStartPost` commands as below.

```
post_start_hook=#!/usr/bin/bash
    set -euo pipefail
    echo 'POST_START_HOOK'
    ip link set dev ve-docker-1 master br40
    ip link set dev ve-docker-1 up
    ip link set dev ve-docker-2 master br70
    ip link set dev ve-docker-2 up
```

With the new `--network-veth-extra` interface link created and the host side added to an existing host bridge, the jail side of the link still needs to be configured. Jailmaker provides a network file in the form of `/etc/systemd/network/vee-dhcp.network` which will automatically perform this configuration. In order for `vee-dhcp.network` to successfully match and configure the link's jail side interface, the `<jail_interface_name>` must begin with a ***vee-*** prefix. An example jailmaker config with properly named `--network-veth-extra` interfaces and `post_start_hook` commands is available [here](https://github.com/Jip-Hop/jailmaker/discussions/179#discussioncomment-9499289).

## Macvlan Networking

Some services require the use of port 80 or 443, or would benefit from a separate IP. For these situations the easiest network configuration is the MAC VLAN configuration. This creates a virtual interface with its own separate randomly generated MAC address and IP. The default config uses DHCP by default, but can easily be set to a Static IP.

### Macvlan Flaws
Any services in the jail cannot communicate with the direct host (TrueNAS). The jail can communicate with any other jail or device on the network, besides TrueNAS or VMs hosted on TrueNAS. This may be a benefit (security) or disadvantage (no communication) depending on your service. If that's required it would be better to use [Bridge Networking](#bridge-networking).

### Macvlan Setup

Add the following argument to the "additional flags" prompt of jail creation or the "systemd_nspawn_user_arguments" line of the jail config file: `--network-macvlan=eno1 --resolv-conf=bind-host`. Where eno1 is the name of your physical network interface.

### Macvlan Static IP
To set a Static IP you need to disable DHCP in the macvlan config file `/etc/systemd/network/mv-dhcp.network`. You can do this with a network client like WinSCP by navigating into the jail's filesystem then the path above, or by using a text editing program like nano by running `nano /etc/systemd/network/mv-dhcp.network` in the jail's shell.

The DHCP in [Network] needs to be set to false, an Address (static IP) needs to be added, a Gateway needs to be defined (e.g your router such as 192.168.0.1) and the entire DHCP section needs to be removed.

An example static IP configuration is as follows:
```
[Match]
Virtualization=container
Name=mv-*

[Network]
DHCP=false
Address=192.168.X.XXX/24
Gateway=192.168.X.X
```
Then restart the network interface inside the jail `systemctl restart systemd-networkd` or restart the jail by running `./jlmkr.py stop JAILNAME && ./jlmkr.py start JAILNAME` from the TrueNAS shell. Use `ifconfig` to verify the interface is up and has the correct IP.

## DNS via DHCP

If you're not using host networking, and you're not using the `--resolv-conf=` in case of bridge/macvlan networking, then you have to configure the DNS servers to use.

To get DNS servers via DHCP install and enable `resolvconf`.

```shell
# Only run this inside the jail!

# Temporarily fix DNS resolution,
# otherwise we can't install packages
echo 'nameserver 8.8.8.8' > /etc/resolv.conf
# On debian based distro
apt update && apt -y install resolvconf
```

## References

- [systemd-nspawn](https://manpages.debian.org/bullseye/systemd-container/systemd-nspawn.1.en.html)- [Setting up Systemd-nspawn](https://www.cocode.se/linux/systemd_nspawn.html#orge360318)
- [Debian Reference - Chapter 5. Network setup](https://www.debian.org/doc/manuals/debian-reference/ch05.en.html#_the_hostname_resolution)
- [Disabling link-local addressing](https://jerrington.me/posts/2017-08-06-systemd-nspawn-disabling-link-local-addressing.html#disabling-link-local-addressing)
