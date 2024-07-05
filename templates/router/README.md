# Router Jail Template

Host a subordinate LAN using nftables and dnsmasq for DHCP, DNS, routing, and netboot infrastructure.
```
router   laptop  desktop
  |         |       |
  +-- LAN --+-------+
       |
      { TrueNAS SCALE }
                     |
    +-----+-----+-- LAN2 --+------+------+-------+
    |     |     |          |      |      |       |
   RPi1  RPi2  RPi3      NUC01  NUC02  NUC03  CrayYMP
```
*Example usage*: deploy a flock of headless/diskless Raspberry Pi worker nodes for Kubernetes; each netbooting into an iSCSI or NFS root volume.

## Setup

Use the TrueNAS SCALE administrative UI to create a network bridge interface. Assign to that bridge a physical interface that's not shared with the host network.

Use the `dnsmasq-example.conf` file as a starting point for your own dnsmasq settings file(s). Copy or mount them inside `/etc/dnsmasq.d/` within the jail.

Optional: place assets in the mounted `/tftp/` directory for netbooting clients.

Optional: attach more jails to this same bridge to host e.g. a K3s control plane, an nginx load balancer, a PostgreSQL database...

Check out the [config](./config) template file. You may provide it when asked during `./jlmkr.py create` or, if you have the template file stored on your NAS, you may provide it directly by running `./jlmkr.py create --start --config /mnt/tank/path/to/router/config myrouterjail`.

## Additional Resources

There are as many reasons to host LAN infrastructure as there are to connect a LAN. This template can help you kick-start such a leaf network, using a TrueNAS jail as its gateway host.

For those specifically interested in *netbooting Raspberry Pi*, the following **external** links might help you get started.

* [Network Booting a Raspberry Pi 4 with an iSCSI Root via FreeNAS][G1]; the title says it all
* [Raspberry Pi Network Boot Guide][G2] covers more Raspberry Pi models; written for Synology users
* [pi_iscsi_netboot][s1] and [prep-netboot-storage][s2] are scripts showing preparation of boot assets and iSCSI root volumes

Good luck!

[G1]: https://shawnwilsher.com/2020/05/network-booting-a-raspberry-pi-4-with-an-iscsi-root-via-freenas/
[G2]: https://warmestrobot.com/blog/2021/6/21/raspberry-pi-network-boot-guide
[s1]: https://github.com/tjpetz/pi_iscsi_netboot
[s2]: https://gitlab.com/jnicpon/rpi-prep/-/blob/main/scripts/prep-netboot-storage.fish?ref_type=heads
