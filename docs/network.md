# Host Passthrough (Default network configuration)
By default jails will use the same physical interface as the TrueNAS host. If a service attempts to bind to port 80 or 443, it will either fail or render both the service and TrueNAS unavailable. 
### Flaws
Depending on the service this may be ok, for example Home Assistant will bind to port 8123, leaving the 80 and 443 ports free from clashes for the TrueNAS web interface. You can then either connect to the service with the port, or use a reverse proxy such as [nginx](https://www.nginx.com/#).
### Setup
No configuration is necessary

# MAC VLAN Virtual Interface
Some services require the use of port 80 or 443, or would benefit from a separate IP. For these situations the easiest network configuration is the MAC VLAN configuration. This creates a virtual interface with its own separate randomly generated MAC address and IP.
The default config uses DHCP by default, but can easily be set to a Static IP.
### Flaws
Any services in the jail cannot communicate with the direct host (TrueNAS). The jail can communicate with any other jail or device on the network, besides TrueNAS. This may or not be a benefit (security) or disadvantage (no communication) depending on your service.
### Setup
Add the following argument to the "additional flags" prompt of jail creation or the "systemd_nspawn_user_arguments" line of the jail config file:
```
--network-macvlan=eno1 --resolv-conf=bind-host
```

### Setting a Static IP
To set a Static IP you need to disable DHCP in the macvlan config file `/etc/systemd/network/mv-dhcp.network`
You can do this with a network client like WinSCP by navigating into the jail's filesystem then the path above, or by using a text editing program like nano by running `nano /etc/systemd/network/mv-dhcp.network` in the jail's shell.

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
Then restart the network interface inside the jail `systemctl restart systemd-networkd` or restart the jail by running `jlmkr stop JAILNAME && jlmkr start JAILNAME` from the TrueNAS shell. Use `ifconfig` to verify the interface is up and has the correct IP.

# Passthrough a TrueNAS Bridge Interface
By creating a network bridge in the TrueNAS Network page you can bridge the incoming physical network interface to a virtual interface that can be passed to the jail. This type of interface has the benefits of a MAC VLAN interface without the flaws (host to jail networking). Once working the virtual interface can either be assigned a static IP or obtain one automatically via DHCP.
### Flaws
This type of interface takes much longer to set up both in complexity and wait time as there is a current flaw in which HDCP can take between 10 seconds and a minute.
Furthermore, if the configuration is not correct it can render your TrueNAS inaccessible via ssh, necessitating a reset using a keyboard and monitor plugged into the TrueNAS server.
### Setup
[TrueNAS Bridge interface guide](https://www.youtube.com/watch?v=7clQw132w58)
May be helpful to connect a monitor and keyboard to the NAS and use /etc/netcli to reset the networking interface. Kept bothering with "Register Default Gateway" warning... I just clicked Cancel.

Add the `--network-bridge=br1 --resolv-conf=bind-host` flag when asked for additional flags during jail creation, or set it post-creation by editing the `SYSTEMD_NSPAWN_USER_ARGS` variable inside the config file.

### Static IP
To configure a static IP with our bridge interface, we need to edit the  `/etc/systemd/network/80-container-host0.network` file. Change the [Network] section to look like this:
```
[Network]
DHCP=false
Address=192.168.X.XXX/24
Gateway=192.168.X.X
```
Then restart the network interface inside the jail `systemctl restart systemd-networkd` or restart the jail by running `jlmkr stop JAILNAME && jlmkr start JAILNAME` from the TrueNAS shell. Use `ifconfig` to verify the interface is up and has the correct IP.
