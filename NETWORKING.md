# Jailmaker

## Advanced Networking

These are notes on advanced networking setup you may want to try. Contributions are welcome!

### Bridge Networking

As an alternative to the default host networking mode, you may want to connect to a bridge interface instead and let the jail obtain its IP address via DHCP (although you may have to be patient for up to 20 seconds after the jail started for networking to work, [assigning the IP address is somehow slow](https://github.com/Jip-Hop/jailmaker/issues/7)).

[This YouTube video](https://www.youtube.com/watch?v=7clQw132w58) may be helpful when setting up the bridge interface. Note: You may lock yourself out... It may take several tries... TrueNAS is a bit picky when switching IP addresses and toggling DHCP. May be helpful to connect a monitor and keyboard to the NAS and use `/etc/netcli` to reset the networking interface. Kept bothering with "Register Default Gateway" warning... I just clicked Cancel.

Add the `--network-bridge=br1 --resolv-conf=bind-host` systemd-nspawn flag when asked for `Additional flags` during jail creation, or set it post-creation by [editing](./README.md#edit-jail-config) the `SYSTEMD_NSPAWN_USER_ARGS` variable inside the `config` file.

The TrueNAS host and the jail will be able to communicate with each other as if the jail was just another device on the LAN. It will use the same DNS servers as the TrueNAS host because the `--resolv-conf=bind-host` option bind mounts the `/etc/resolv.conf` file from the host inside the jail. If you want to use the DNS servers advertised via DHCP, then check [DNS via DHCP](#dns-via-dhcp).

To configure a **static IP** with our bridge interface, we need to edit the `80-container-host0.network` file located in `/etc/systemd/network`. Change the `[Network]` section to look like this:

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


### Macvlan Networking

To setup Macvlan Networking you may follow the [Bridge Networking](#bridge-networking) section, but skip the setup of a bridge interface and use these flags instead: `--network-macvlan=eno1 --resolv-conf=bind-host`. By default the TrueNAS host and jail will not be able to communicate with each other via the network if Macvlan Networking mode is used. If that's required it would be better to use [Bridge Networking](#bridge-networking).

### DNS via DHCP

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