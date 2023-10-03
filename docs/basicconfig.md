# User Management
The root user (also known as the superuser or su) can access any file, make system changes, and lots of room for security vulnerabilities.
For this reason you should aspire to run services as a non-root user.

### Create a non-root user
`useradd USERNAME`

Where username can be anything, but should reflect the service/jail's name for diagnostic.

Then a password should be created as some commands require a non-blank password to be inserted:
`passwd USERNAME`

If you want the ability to run commands as root, add the user to the sudo group
`usermod -aG sudo USERNAME`

This WILL require a non-blank password, and any command run with sudo will be run as root not as the user. But it saves time compared to switching users to root to install/change things then switching back.

### Switch to user
`su -l USERNAME`

### Put a password on Root
While logged in as root run `passwd`

# Common tweaks
### Update repository list 
`sudo apt update`

### Install common services 
`sudo apt install nano wget curl git`

### Set Static IP
See `Networking`

### Install Docker
```
apt install curl && cd /tmp && curl -fsSL https://get.docker.com -o get-docker.sh && sudo sh get-docker.sh && cd ~ && docker
```
