# Jailmaker Docs

Anything described on this page is completely optional. You do NOT need to do anything of this in order to start using jailmaker.

## User Management
The root user (also known as the superuser or su) can access any file, make system changes, and lots of room for security vulnerabilities.
For this reason you should aspire to run services as a non-root user.

### Create a non-root user
`useradd USERNAME`

Where username can be anything, but should reflect the service/jail's name for diagnostic.

Then a password should be created as some commands require a non-blank password to be inserted:
`passwd USERNAME`

If you want the ability to run commands as root, add the user to the sudo group:

```sh
usermod -aG sudo USERNAME
```

This WILL require a non-blank password, and any command run with sudo will be run as root not as the user. But it saves time compared to switching users to root to install/change things then switching back.

### Switch to user

```sh
su -l USERNAME
```

### Put a password on Root

While logged in as root run `passwd`.

## Common Tweaks

### Update repository list 

```sh
sudo apt update
```

### Install common services 

```sh
sudo apt install nano wget curl git
```

### Set Static IP

See [Networking](./network.md)

### Colorized bash prompt

To visually distinguish between a root shell inside the jail and a root shell outside the jail, it's possible to colorize the shell prompt. When using a debian jail with the bash shell, you may run the following command **inside the jail** to get a yellow prompt inside the jail (will be activated the next time you run `./jlmkr.py shell myjail`):

```bash
echo "PS1='${debian_chroot:+($debian_chroot)}\[\033[01;33m\]\u@\h\[\033[00m\]:\[\033[01;34m\]\w\[\033[00m\]\$ '" >> ~/.bashrc
```

### Install Docker

It's advised to use the [docker config template](../templates/docker/README.md). But you can install it manually like this as well:

```sh
apt install curl && cd /tmp && curl -fsSL https://get.docker.com -o get-docker.sh && sudo sh get-docker.sh && cd ~ && docker
```
