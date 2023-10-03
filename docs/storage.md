# Default storage system
When creating a jail, an entire Linux filesystem is created in the 'rootfs' folder within the jail's folder of the jailmaker directory E.g `/mnt/tank/vault/jailmaker/jails/jailname/rootfs`. No files from the TrueNAS host will be available. 

Common locations for services are:
`/home` for user accessible files
`/var/www/` for webpages
`/tmp` for temporary application data such as build files

# Linking folders to TrueNAS folders
To allow file access by either the jail, another jail, or TrueNAS a bind can be made. A bind creates a link between two locations. Think of this as a portal, anything that goes in one side is visible from the other side and vice versa.

Note that creating a file in the jail or TrueNAS will reflect in both binded locations, so be careful of overwrites and corruption.

### Setup
Add the following to your user arguments during setup or into the jail's config file, with your two linked locations separated by a colon:
```
--bind='/host/path/to/:/jail/path/to'
```
Where `/host/path/to/` is the folder on the TrueNAS filesystem you want shared.
And where `/jail/path/to/` is the folder you want those shared files accessible by the jail.

### Example
A use of this is making files available in a jail for it to use or serve, such as media files in Plex/Jellyfin:
Example: `--bind='/mnt/tank/content/:/media'` will make any files inside the content dataset of the tank pool available inside the jail's /media folder. To visualise or test this you can copy some files to `/mnt/tank/content/` such as `media1.mp4`, `media2.mkv` and `photo.jpg`. Then change directory to that folder inside the jail `cd /media` and list files in that directory `ls -l` where those files should appear.

### Warning
Do not bind your TrueNAS system directories (`/root` `/mnt` `/dev` `/bin` `/etc` `/home` `/var` `/usr` or anything else in the root directory) to your jail as this can cause TrueNAS to lose permissions and render your TrueNAS system unusable.
Best practice is to create a dataset in a pool which also allows zfs, raidz, permissions, and backups to function. E.g creating a `websites` dataset in a pool named `tank` then binding `--bind='/mnt/tank/websites/websitename/:/var/www/websitename/'`
