#!/usr/bin/env bash
set -euo pipefail

# TODO: create a path and/or zfs pool with a space in it to test if jlmkr.py still works properly when ran from inside
# mkdir -p "/tmp/path with space/jailmaker"

# TODO: many more test cases and checking if actual output (text, files on disk etc.) is correct instead of just a 0 exit code

./jlmkr.py create --start examiner --network-bridge=br1 --resolv-conf=bind-host
echo "About to run debug logging in jail"
cat <<EOF > jails/examiner/rootfs/root/debug.sh
for path in /etc/systemd/network* /etc/systemd/resolve* /etc/resolv.conf ; do
	echo "✳️ \$path"
	[ -d "\$path" ] && ls -la "\$path" || cat "\$path"
	echo
done
netstat -n -r
sleep 3
ip addr
resolvectl query deb.debian.org
ping -c1 1.1.1.1
ping -c1 deb.debian.org
EOF

sleep 5
./jlmkr.py exec examiner bash /root/debug.sh

# TODO: test jlmkr.py from inside another working directory, with a relative path to a config file to test if it uses the config file (and doesn't look for it relative to the jlmkr.py file itself)
./jlmkr.py create --start --config=./templates/docker/config test
./jlmkr.py exec test docker run hello-world
