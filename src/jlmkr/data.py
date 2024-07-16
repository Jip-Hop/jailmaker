# SPDX-FileCopyrightText: © 2024 Jip-Hop and the Jailmakers <https://github.com/Jip-Hop/jailmaker>
#
# SPDX-License-Identifier: LGPL-3.0-only

from utils.console import BOLD, NORMAL, YELLOW

from __main__ import __disclaimer__

DISCLAIMER = f"""{YELLOW}{BOLD}{__disclaimer__}{NORMAL}"""


DEFAULT_CONFIG = """startup=0
gpu_passthrough_intel=0
gpu_passthrough_nvidia=0
# Turning off seccomp filtering improves performance at the expense of security
seccomp=1

# Below you may add additional systemd-nspawn flags behind systemd_nspawn_user_args=
# To mount host storage in the jail, you may add: --bind='/mnt/pool/dataset:/home'
# To readonly mount host storage, you may add: --bind-ro=/etc/certificates
# To use macvlan networking add: --network-macvlan=eno1 --resolv-conf=bind-host
# To use bridge networking add: --network-bridge=br1 --resolv-conf=bind-host
# Ensure to change eno1/br1 to the interface name you want to use
# To allow syscalls required by docker add: --system-call-filter='add_key keyctl bpf'
systemd_nspawn_user_args=

# Specify command/script to run on the HOST before starting the jail
# For example to load kernel modules and config kernel settings
pre_start_hook=
# pre_start_hook=#!/usr/bin/bash
#     set -euo pipefail
#     echo 'PRE_START_HOOK_EXAMPLE'
#     echo 1 > /proc/sys/net/ipv4/ip_forward
#     modprobe br_netfilter
#     echo 1 > /proc/sys/net/bridge/bridge-nf-call-iptables
#     echo 1 > /proc/sys/net/bridge/bridge-nf-call-ip6tables

# Specify command/script to run on the HOST after starting the jail
# For example to attach to multiple bridge interfaces 
# when using --network-veth-extra=ve-myjail-1:veth1
post_start_hook=
# post_start_hook=#!/usr/bin/bash
#     set -euo pipefail
#     echo 'POST_START_HOOK_EXAMPLE'
#     ip link set dev ve-myjail-1 master br2
#     ip link set dev ve-myjail-1 up

# Specify a command/script to run on the HOST after stopping the jail
post_stop_hook=
# post_stop_hook=echo 'POST_STOP_HOOK_EXAMPLE'

# Only used while creating the jail
distro=debian
release=bookworm

# Specify command/script to run IN THE JAIL on the first start (once networking is ready in the jail)
# Useful to install packages on top of the base rootfs
initial_setup=
# initial_setup=bash -c 'apt-get update && apt-get -y upgrade'

# Usually no need to change systemd_run_default_args
systemd_run_default_args=--collect
    --property=Delegate=yes
    --property=RestartForceExitStatus=133
    --property=SuccessExitStatus=133
    --property=TasksMax=infinity
    --property=Type=notify
    --setenv=SYSTEMD_NSPAWN_LOCK=0
    --property=KillMode=mixed

# Usually no need to change systemd_nspawn_default_args
systemd_nspawn_default_args=--bind-ro=/sys/module
    --boot
    --inaccessible=/sys/module/apparmor
    --quiet
    --keep-unit"""
