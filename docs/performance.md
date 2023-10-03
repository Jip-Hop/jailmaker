(Anecdotal from observations, actual measurements with resource monitor captures and wall power meter coming soon.)

Kubernetes Server (TrueNAS Apps) with no apps installed:
* Idle on 7100T: ~20% / 15W
* Idle on 10600K: ~10%

Kubernetes Server (TrueNAS Apps) with 10 apps installed:
* Idle on 7100T: ~26% / 18W
* Idle on 10600K: ~15%

Systemd-nspawn container (jailmaker) with no apps installed:
* Idle on 7100T: ~1% / 6W
* Idle on 10600K: ~0%

Systemd-nspawn container (jailmaker) with 10 apps installed:
* Idle on 7100T: ~4% / 8W
* Idle on 10600K: ~0%


Systemd-nspawn container (jailmaker) with 20 apps installed:
* Idle on 10600K: ~1%
