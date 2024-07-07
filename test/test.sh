#!/usr/bin/env bash
set -euo pipefail

# TODO: create a path and/or zfs pool with a space in it to test if jlmkr.py still works properly when ran from inside
# mkdir -p "/tmp/path with space/jailmaker"

# TODO: test jlmkr.py from inside another working directory, with a relative path to a config file to test if it uses the config file (and doesn't look for it relative to the jlmkr.py file itself)
./jlmkr.py create --start --config=./templates/docker/config test --network-veth --system-call-filter='add_key' --system-call-filter='bpf' --system-call-filter='keyctl'
./jlmkr.py exec test docker run hello-world

# TODO: many more test cases and checking if actual output (text, files on disk etc.) is correct instead of just a 0 exit code