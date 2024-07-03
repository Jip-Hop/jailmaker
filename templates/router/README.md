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
*Example usage*: deploy an army of headless/diskless Raspberry Pi worker nodes for Kubernetes; each netbooting into an iSCSI or NFS root volume.

## Setup

Use the TrueNAS SCALE administrative UI to create a network bridge interface. Assign to that bridge a physical interface that's not shared with the host network.

Optional: place assets in the TFTP directory for netbooting clients.

Attach more jails to this same bridge to host e.g. a K3s control plane, an nginx load balancer, a PostgreSQL database...

Check out the [config](./config) template file. You may provide it when asked during `./jlmkr.py create` or, if you have the template file stored on your NAS, you may provide it directly by running `./jlmkr.py create --start --config /mnt/tank/path/to/router/config myrouterjail`.
