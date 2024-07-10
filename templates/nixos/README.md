# Nixos Jail Template

## Disclaimer

**Experimental. Using nixos in this setup hasn't been extensively tested and has [known issues](#known-issues).**

## Setup

Check out the [config](./config) template file. You may provide it when asked during `./jlmkr.py create` or, if you have the template file stored on your NAS, you may provide it directly by running `./jlmkr.py create --start --config /mnt/tank/path/to/nixos/config mynixosjail`.

## Manual Setup

```bash
# Create the jail without starting
./jlmkr.py create --distro=nixos --release=24.05 nixos --network-bridge=br1 --resolv-conf=bind-host --bind-ro=./lxd.nix:/etc/nixos/lxd.nix
# Create empty nix module to satisfy import in default lxc configuration.nix
echo '{ ... }:{}' > ./jails/nixos/lxd.nix
# Start the nixos jail
./jlmkr.py start nixos
sleep 90
# Network should be up by now
./jlmkr.py shell nixos /bin/sh -c 'ifconfig'
# Try to rebuild the system
./jlmkr.py shell nixos /bin/sh -c 'nixos-rebuild switch'
```

## Known Issues

### Environment jlmkr exec

Running `./jlmkr.py exec mynixosjail ifconfig` doesn't work because the shell environment isn't setup properly. You can run `./jlmkr.py shell mynixosjail /bin/sh -c 'ifconfig'` or `./jlmkr.py exec mynixosjail /bin/sh -c '. /etc/bashrc; ifconfig'` instead.

### Bridge networking only

This setup has NOT been tested with macvlan networking.