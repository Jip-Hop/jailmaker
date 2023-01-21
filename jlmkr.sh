#!/bin/bash

set -eEuo pipefail
shopt -s nullglob

ABSOLUTE_SCRIPT_PATH="$(realpath "${BASH_SOURCE[0]}")"
SCRIPT_NAME=$(basename "${ABSOLUTE_SCRIPT_PATH}")
SCRIPT_DIR_PATH="$(dirname "${ABSOLUTE_SCRIPT_PATH}")"
LXC_DIR_PATH='.lxc'
LXC_CACHE_PATH="${LXC_DIR_PATH}/cache"
LXC_DOWNLOAD_SCRIPT_PATH="${LXC_DIR_PATH}/lxc-download.sh"
ARCH="$(dpkg --print-architecture)"
JAILS_DIR_PATH='jails'
START_JAIL=0
JAIL_NAME=
JAIL_PATH=
DISTRO=
RELEASE=
SYSTEMD_RUN_CMD=(systemd-run --setenv=SYSTEMD_NSPAWN_LOCK=0 --property=KillMode=mixed
	--property=Type=notify --property=RestartForceExitStatus=133 --property=SuccessExitStatus=133
	--property=Delegate=yes --property=TasksMax=16384 --same-dir)
SYSTEMD_NSPAWN_CMD=(systemd-nspawn --keep-unit --quiet --boot)
DONE=0

USAGE="WARNING: EXPERIMENTAL AND WORK IN PROGRESS, USE ONLY FOR TESTING!

Usage: ./${SCRIPT_NAME} COMMAND [ARG...]

TODO: complete writing usage
"

err() {
	# https://unix.stackexchange.com/a/504829/477308
	echo 'Error occurred:'
	awk 'NR>L-4 && NR<L+4 { printf "%-5d%3s%s\n",NR,(NR==L?">>>":""),$0 }' L="${1}" "${0}"
}

cleanup() {
	# If the script didn't complete (not DONE) then
	# remove the JAIL_PATH (if set and a directory)
	if [[ "${DONE}" -ne 1 && -n "${JAIL_PATH}" && -d "${JAIL_PATH}" &&
		"${JAIL_PATH}" != "${JAILS_DIR_PATH}" && "${JAIL_PATH}" != "/" ]]; then
		echo -e "\n\nCleaning up: ${JAIL_PATH}\n"
		rm -rf "${JAIL_PATH}"
	fi
}

# Trap errors and cleanup on exit
trap 'err $LINENO' ERR && trap cleanup EXIT

fail() {
	echo -e "$1" >&2 && exit 1
}

stat_chmod() {
	# Only run chmod if mode is different from current mode
	if [[ "$(stat -c%a "${2}")" -ne "${1}" ]]; then chmod "${1}" "${2}"; fi
}

validate_download_script() {
	echo "6cca2eda73c7358c232fecb4e750b3bf0afa9636efb5de6a9517b7df78be12a4  ${LXC_DOWNLOAD_SCRIPT_PATH}" | sha256sum --check >/dev/null
}

read_name() {
	local jail_name
	local jail_path

	while true; do
		read -r -p "Enter jail name: " jail_name && echo
		if ! [[ "${jail_name}" =~ ^[.a-zA-Z0-9-]{1,64}$ && "${jail_name}" != '.'* && "${jail_name}" != *'.' && "${jail_name}" != *'..'* ]]; then
			cat <<-'EOF'
				A valid name consists of:
				- allowed characters (alphanumeric, dash, dot)
				- no leading or trailing dots
				- no sequences of multiple dots
				- max 64 characters

			EOF
		else
			jail_path="${JAILS_DIR_PATH}/${jail_name}"

			if [[ -e "${jail_path}" ]]; then
				echo "A jail with this name already exists."
				echo
			else
				# Only set global variables if we accept the name,
				# else the wrong directory may be cleaned up!
				JAIL_NAME="${jail_name}"
				JAIL_PATH="${jail_path}"
				return
			fi
		fi
	done
}

run_jail() (
	# Create a sub-shell to source the conf file
	set -eEuo pipefail

	RUN_DOCKER=
	GPU_PASSTHROUGH=
	SYSTEMD_RUN_CMD=()
	SYSTEMD_NSPAWN_CMD=()

	# Load the config
	# shellcheck disable=SC1090
	. "${1}"

	if [[ ${#SYSTEMD_RUN_CMD[@]} -ne 0 && ${#SYSTEMD_NSPAWN_CMD[@]} -ne 0 ]]; then
		if [[ "${RUN_DOCKER}" -eq 1 ]]; then
			# Enable ip forwarding on the host (docker needs it)
			echo 1 >/proc/sys/net/ipv4/ip_forward
			# To properly run docker inside the jail, we need to lift restrictions
			# Without DevicePolicy=auto images with device nodes may not be pulled
			# https://github.com/kinvolk/kube-spawn/pull/328
			SYSTEMD_RUN_CMD+=(--setenv=SYSTEMD_SECCOMP=0 --property=DevicePolicy=auto)
			# Add additional flags required for docker
			SYSTEMD_NSPAWN_CMD+=(--capability=all "--system-call-filter='add_key keyctl bpf'")
		fi

		if [[ "${GPU_PASSTHROUGH}" -eq 1 ]]; then
			SYSTEMD_NSPAWN_CMD+=("--property=DeviceAllow='char-drm rw'")

			# Detect intel GPU device and if present add bind flag
			[[ -d /dev/dri ]] && SYSTEMD_NSPAWN_CMD+=(--bind=/dev/dri)

			# TODO: add bind mount flags in case of nvidia GPU passthrough
		fi

		FINAL_COMMAND=" ${SYSTEMD_RUN_CMD[*]} -- ${SYSTEMD_NSPAWN_CMD[*]}"
		echo "Starting jail with the following command:"
		echo "${FINAL_COMMAND}"
		echo
		eval "${FINAL_COMMAND}"
	fi
)

[[ $UID -ne 0 ]] && echo "${USAGE}" && fail "Run this script as root..."

read -p "Create a new jail? [Y/n] " -n 1 -r REPLY && echo
# Enter accepts default (yes)
# https://stackoverflow.com/a/1885534
! [[ "${REPLY}" =~ ^([Yy]|)$ ]] && echo "${USAGE}" && exit

[[ "$(basename "${SCRIPT_DIR_PATH}")" != 'jailmaker' ]] && fail "${SCRIPT_NAME} needs to create files.
Currently it can't decide if it's safe to create files in:
${SCRIPT_DIR_PATH}
Please create a dedicated directory called 'jailmaker', store ${SCRIPT_NAME} there and try again."

read -p "Start the jail when the installation is complete? [Y/n] " -n 1 -r REPLY && echo
# Enter accepts default (yes)
[[ "${REPLY}" =~ ^([Yy]|)$ ]] && START_JAIL=1

if [[ $(findmnt --target . --output TARGET --noheadings --first-only) != /mnt/* ]]; then
	echo "${SCRIPT_NAME} should be on a pool mounted under /mnt (it currently isn't)."
	echo "Storing it on the boot-pool means losing all jails when updating TrueNAS."
	echo "If you continue, jails will be stored under:"
	echo "${SCRIPT_DIR_PATH}"
	read -p "Do you wish to ignore this warning and continue? [y/N] " -n 1 -r REPLY && echo
	# Enter accepts default (no)
	! [[ "${REPLY}" =~ ^[Yy]$ ]] && exit
fi

cd "${SCRIPT_DIR_PATH}" || fail "Could not change working directory to ${SCRIPT_DIR_PATH}..."

# Set appropriate permissions (if not already set) for this file, since it's executed as root
stat_chmod 700 "${SCRIPT_NAME}"

# Create the lxc dirs if nonexistent
mkdir -p "${LXC_DIR_PATH}"
stat_chmod 700 "${LXC_DIR_PATH}"
mkdir -p "${LXC_CACHE_PATH}"
stat_chmod 700 "${LXC_CACHE_PATH}"

# Create the dir where to store the jails
mkdir -p "${JAILS_DIR_PATH}"
stat_chmod 700 "${JAILS_DIR_PATH}"

# Fetch the lxc download script if not present locally (or hash doesn't match)
if ! validate_download_script; then
	curl -fSL https://raw.githubusercontent.com/lxc/lxc/58520263041b6864cadad96278848f9b8ce78ee9/templates/lxc-download.in -o "${LXC_DOWNLOAD_SCRIPT_PATH}"
	# Validate after download to prevent executing arbritrary code as root
	validate_download_script || fail 'Abort! Downloaded script has unexpected contents.'
fi

stat_chmod 700 "${LXC_DOWNLOAD_SCRIPT_PATH}"

read_name

# Create directory for rootfs
JAIL_ROOTFS_PATH="${JAIL_PATH}/rootfs"
mkdir -p "${JAIL_ROOTFS_PATH}"

SYSTEMD_RUN_CMD+=("--description='jailmaker ${JAIL_NAME}'")
SYSTEMD_NSPAWN_CMD+=(--machine="${JAIL_NAME}" "--directory='./${JAIL_ROOTFS_PATH}'")

echo "You may choose which distro to install (Ubuntu, CentOS, Alpine etc.)"
echo "Or you may install the recommended distro: Debian 11."
read -p "Install Debian 11? [Y/n] " -n 1 -r REPLY && echo
if [[ "${REPLY}" =~ ^([Yy]|)$ ]]; then
	DISTRO='debian'
	RELEASE='bullseye'
fi

JAIL_CONFIG_NAME='config'
JAIL_CONFIG_PATH="${JAIL_PATH}/${JAIL_CONFIG_NAME}"
# LXC download script needs to write to this file during install
# but we don't need it so we will remove it later
touch "${JAIL_CONFIG_PATH}"

LXC_CACHE_PATH=${LXC_CACHE_PATH} "${LXC_DOWNLOAD_SCRIPT_PATH}" \
	--name="${JAIL_NAME}" --path="${JAIL_PATH}" --rootfs="${JAIL_ROOTFS_PATH}" \
	--arch="${ARCH}" --dist="${DISTRO}" --release="${RELEASE}" ||
	fail "Aborted creating rootfs..."
echo

# Remove file we no longer need
rm -f "${JAIL_CONFIG_PATH}"
# Config which systemd handles for us
rm -f "${JAIL_ROOTFS_PATH}/etc/machine-id"
rm -f "${JAIL_ROOTFS_PATH}/etc/resolv.conf"
rm -f "${JAIL_ROOTFS_PATH}/etc/resolv.conf"
# https://github.com/systemd/systemd/issues/852
# printf 'pts/%d\n' $(seq 0 10) >"${JAIL_ROOTFS_PATH}/etc/securetty"

read -p "Give access to the GPU inside the jail? [y/N] " -n 1 -r REPLY && echo
# Enter accepts default (no)
if ! [[ "${REPLY}" =~ ^[Yy]$ ]]; then GPU_PASSTHROUGH=0; else GPU_PASSTHROUGH=1; fi

# TODO: ask for additional flags (to bind mount etc.)
# TODO: ask for network setup (host, macvlan, bridge, physical nic)

read -p "Install Docker inside the jail? [y/N] " -n 1 -r REPLY && echo
# Enter accepts default (no)
if ! [[ "${REPLY}" =~ ^[Yy]$ ]]; then INSTALL_DOCKER=0; else INSTALL_DOCKER=1; fi
if [[ "${INSTALL_DOCKER}" -eq 1 ]]; then
	DOCKER_INSTALL_SCRIPT_NAME='get-docker.sh'
	DOCKER_INSTALL_SCRIPT_PATH="${JAIL_ROOTFS_PATH}/${DOCKER_INSTALL_SCRIPT_NAME}"
	curl -fsSL https://get.docker.com -o "${DOCKER_INSTALL_SCRIPT_PATH}"
	chmod +x "${DOCKER_INSTALL_SCRIPT_PATH}"
	echo "Running docker install script..."
	systemd-nspawn -q -D "${JAIL_ROOTFS_PATH}" "./${DOCKER_INSTALL_SCRIPT_NAME}"
	rm "${DOCKER_INSTALL_SCRIPT_PATH}"
	# TODO: also install nvidia-docker2 if GPU_PASSTHROUGH=1 and nvidia GPU is present
fi

JAIL_CONFIG_NAME='conf'
JAIL_CONFIG_PATH="${JAIL_PATH}/${JAIL_CONFIG_NAME}"

echo "${SYSTEMD_RUN_CMD[*]}"
echo "${SYSTEMD_NSPAWN_CMD[*]}"
cat <<-EOF >"${JAIL_CONFIG_PATH}"
	# This file will be sourced in a a bash sub-shell before starting the jail.
	# You can change the settings below and/or add custom code.
	RUN_DOCKER=${INSTALL_DOCKER}
	GPU_PASSTHROUGH=${GPU_PASSTHROUGH}
EOF

# Also add arrays containing the commands to run
declare -p SYSTEMD_RUN_CMD SYSTEMD_NSPAWN_CMD >>"${JAIL_CONFIG_PATH}"

echo "FROM CONF"
cat "${JAIL_CONFIG_PATH}"
chmod 600 "${JAIL_CONFIG_PATH}"

[[ "${START_JAIL}" -eq 1 ]] && run_jail "${JAIL_CONFIG_PATH}"

DONE=1
