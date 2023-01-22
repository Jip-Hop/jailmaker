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
JAIL_NAME=
JAIL_PATH=
DISTRO=
RELEASE=
SYSTEMD_RUN_UNIT_NAME=
DONE=0

USAGE="WARNING: EXPERIMENTAL AND WORK IN PROGRESS, USE ONLY FOR TESTING!

Usage: ./${SCRIPT_NAME} COMMAND [ARG...]

TODO: complete writing usage
"

fail() {
	echo -e "$1" >&2 && exit 1
}

[[ $UID -ne 0 ]] && echo "${USAGE}" && fail "Run this script as root..."

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

stat_chmod() {
	# Only run chmod if mode is different from current mode
	if [[ "$(stat -c%a "${2}")" -ne "${1}" ]]; then chmod "${1}" "${2}"; fi
}

read_name() {
	local jail_name
	local jail_path

	while true; do
		read -e -r -p "Enter jail name: " jail_name && echo
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
				SYSTEMD_RUN_UNIT_NAME="jlmkr-${JAIL_NAME}"
				return
			fi
		fi
	done
}

validate_download_script() {
	echo "6cca2eda73c7358c232fecb4e750b3bf0afa9636efb5de6a9517b7df78be12a4  ${LXC_DOWNLOAD_SCRIPT_PATH}" | sha256sum --check >/dev/null
}

run_jail() (
	# Create a sub-shell to source the conf file

	RUN_DOCKER=
	GPU_PASSTHROUGH=
	SYSTEMD_RUN_ADDITIONAL_ARGS=()
	SYSTEMD_NSPAWN_ADDITIONAL_ARGS=()

	echo 'Load the config'
	# shellcheck disable=SC1090
	. "${1}"
	echo 'Config loaded'

	set -eEuo pipefail
	if [[ "$(type -t start)" == 'function' ]]; then
		if [[ "${RUN_DOCKER}" -eq 1 ]]; then
			# Enable ip forwarding on the host (docker needs it)
			echo 1 >/proc/sys/net/ipv4/ip_forward
			# To properly run docker inside the jail, we need to lift restrictions
			# Without DevicePolicy=auto images with device nodes may not be pulled
			# https://github.com/kinvolk/kube-spawn/pull/328
			SYSTEMD_RUN_ADDITIONAL_ARGS+=(--setenv=SYSTEMD_SECCOMP=0 --property=DevicePolicy=auto)
			# Add additional flags required for docker
			SYSTEMD_NSPAWN_ADDITIONAL_ARGS+=(--capability=all --system-call-filter='add_key keyctl bpf')
		fi

		if [[ "${GPU_PASSTHROUGH}" -eq 1 ]]; then
			SYSTEMD_NSPAWN_ADDITIONAL_ARGS+=(--property=DeviceAllow='char-drm rw')

			# Detect intel GPU device and if present add bind flag
			[[ -d /dev/dri ]] && SYSTEMD_NSPAWN_ADDITIONAL_ARGS+=(--bind=/dev/dri)

			# TODO: add bind mount flags in case of nvidia GPU passthrough
		fi

		echo "Starting jail..."
		start
	else
		echo "Can't call the start function since the conf file didn't contain one..."
	fi
)

# Properly escape value of variable so it can be echoed to a bash file
escape() {
    local tmp
    tmp="${1}"
    tmp="$(declare -p tmp)"
    tmp="${tmp#*=}"
    echo "${tmp}"
}

create_jail() {

	read -p "Create a new jail? [Y/n] " -n 1 -r REPLY && echo
	# Enter accepts default (yes)
	# https://stackoverflow.com/a/1885534
	! [[ "${REPLY}" =~ ^([Yy]|)$ ]] && echo "${USAGE}" && exit

	[[ "$(basename "${SCRIPT_DIR_PATH}")" != 'jailmaker' ]] && fail "${SCRIPT_NAME} needs to create files.
Currently it can't decide if it's safe to create files in:
${SCRIPT_DIR_PATH}
Please create a dedicated directory called 'jailmaker', store ${SCRIPT_NAME} there and try again."

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
		curl -fSL
		https://raw.githubusercontent.com/Jip-Hop/lxc/58520263041b6864cadad96278848f9b8ce78ee9/templates/lxc-download.in -o "${LXC_DOWNLOAD_SCRIPT_PATH}"
		# Validate after download to prevent executing arbritrary code as root
		validate_download_script || fail 'Abort! Downloaded script has unexpected contents.'
	fi

	stat_chmod 700 "${LXC_DOWNLOAD_SCRIPT_PATH}"

	read -p "Install the recommended distro (Debian 11)? [Y/n] " -n 1 -r REPLY && echo
	if [[ "${REPLY}" =~ ^([Yy]|)$ ]]; then
		DISTRO='debian'
		RELEASE='bullseye'
	else
		echo
		echo "ADVANCED USAGE"
		echo "You may now choose from a list which distro to install."
		echo "Not all of them will work with ${SCRIPT_NAME} (these images are made for LXC)."
		echo "Distros based on systemd probably work (e.g. Ubuntu, Arch Linux and Rocky Linux)."
		echo "Others (Alpine, Devuan, Void Linux) probably won't."
		echo
		read -p "Press any key to continue: " -n 1 -r REPLY && echo
		LXC_CACHE_PATH=${LXC_CACHE_PATH} "${LXC_DOWNLOAD_SCRIPT_PATH}" --list --arch="${ARCH}" || :
		echo "Choose from the DIST column."
		read -e -r -p "Distribution: " DISTRO && echo
		echo "Choose from the RELEASE column (or ARCH if RELEASE is empty)."
		read -e -r -p "Release: " RELEASE && echo
	fi

	read_name

	echo "${SCRIPT_NAME} will not install docker for you."
	echo "But it can configure the jail with the capabilities required to run docker."
	echo "You can turn DOCKER_COMPATIBLE mode on/off post-install."
	echo
	read -p "Make jail docker compatible right now? [y/N] " -n 1 -r REPLY && echo
	# Enter accepts default (no)
	if ! [[ "${REPLY}" =~ ^[Yy]$ ]]; then DOCKER_COMPATIBLE=0; else DOCKER_COMPATIBLE=1; fi

	read -p "Give access to the GPU inside the jail? [y/N] " -n 1 -r REPLY && echo
	# Enter accepts default (no)
	if ! [[ "${REPLY}" =~ ^[Yy]$ ]]; then GPU_PASSTHROUGH=0; else GPU_PASSTHROUGH=1; fi

	# TODO: ask for bind mounts (and warn if trying to mount a parent directory of the jailmaker dir?)
	# TODO: ask for network setup (host, macvlan, bridge, physical nic)
	# TODO: ask for additional flags (to bind mount etc.)
	echo "You may pass additional systemd-nspawn flags."
	echo "For example to mount directories inside the jail you may add:"
	echo "--bind=/mnt/a/readwrite/directory --bind-ro=/mnt/a/readonly/directory"
	echo
	echo "WARNING: double check the syntax:"
	echo "https://manpages.debian.org/bullseye/systemd-container/systemd-nspawn.1.en.html"
	echo "With incorrect flags the jail may not start."
	echo "It's possible to correct/add/remove flags post-install."
	echo
	read -e -r -p "Additional flags: " SYSTEMD_NSPAWN_USER_ARGS_STRING && echo
	# Backslashes and colons need to be escaped for systemd-nspawn by the user:
	# e.g. to bind mount a file called:
	# weird chars :?\"
	# the corresponding command would be:
	# --bind-ro='/mnt/data/weird chars \:?\\"'
	local systemd_nspawn_user_args
	eval "$(echo "${SYSTEMD_NSPAWN_USER_ARGS_STRING}" | xargs bash -c 'declare -a systemd_nspawn_user_args=("$@"); declare -p systemd_nspawn_user_args' --)"
	# https://superuser.com/a/1529316/1268213
	# https://superuser.com/a/1627765
	
	# Create directory for rootfs
	JAIL_ROOTFS_NAME='rootfs'
	JAIL_ROOTFS_PATH="${JAIL_PATH}/${JAIL_ROOTFS_NAME}"
	mkdir -p "${JAIL_ROOTFS_PATH}"

	JAIL_CONFIG_NAME='config'
	JAIL_CONFIG_PATH="${JAIL_PATH}/${JAIL_CONFIG_NAME}"
	# LXC download script needs to write to this file during install
	# but we don't need it so we will remove it later
	touch "${JAIL_CONFIG_PATH}"

	echo
	LXC_CACHE_PATH=${LXC_CACHE_PATH} "${LXC_DOWNLOAD_SCRIPT_PATH}" \
		--name="${JAIL_NAME}" --path="${JAIL_PATH}" --rootfs="${JAIL_ROOTFS_PATH}" \
		--arch="${ARCH}" --dist="${DISTRO}" --release="${RELEASE}" ||
		fail "Aborted creating rootfs..."
	echo

	if [[ "$(basename "$(readlink -f "${JAIL_ROOTFS_PATH}/sbin/init")")" != systemd ]]; then
		echo "Chosen distro appears not to use systemd..."
		echo
		echo "You probably won't get a shell with:"
		echo "machinectl shell ${JAIL_NAME}"
		echo
		echo "You may get a shell with this command:"
		# About nsenter:
		# https://github.com/systemd/systemd/issues/12785#issuecomment-503019081
		# https://github.com/systemd/systemd/issues/3144
		# shellcheck disable=SC2016
		echo 'nsenter -t $(machinectl show '"${JAIL_NAME}"' -p Leader --value) -a /bin/sh -l'
		echo
		echo "Using this distro with ${SCRIPT_NAME} is not recommended."
		echo
		read -p "Abort creating jail? [Y/n] " -n 1 -r REPLY && echo
		# Enter accepts default (yes)
		[[ "${REPLY}" =~ ^([Yy]|)$ ]] && exit
	fi

	# Remove file we no longer need
	rm -f "${JAIL_CONFIG_PATH}"
	# Config which systemd handles for us
	rm -f "${JAIL_ROOTFS_PATH}/etc/machine-id"
	rm -f "${JAIL_ROOTFS_PATH}/etc/resolv.conf"
	rm -f "${JAIL_ROOTFS_PATH}/etc/resolv.conf"
	# https://github.com/systemd/systemd/issues/852
	printf 'pts/%d\n' $(seq 0 10) >"${JAIL_ROOTFS_PATH}/etc/securetty"

	JAIL_CONFIG_NAME='start.sh'
	JAIL_CONFIG_PATH="${JAIL_PATH}/${JAIL_CONFIG_NAME}"

	local systemd_run_additional_args systemd_nspawn_additional_args
	systemd_run_additional_args="--unit='${SYSTEMD_RUN_UNIT_NAME}' --description='jailmaker ${JAIL_NAME}'"
	systemd_nspawn_additional_args="--machine='${JAIL_NAME}' --directory='./${JAIL_ROOTFS_NAME}'"
	for i in "${systemd_nspawn_user_args[@]}"; do systemd_nspawn_additional_args+=" $(escape "$i")"; done

	cat <<-EOF >"${JAIL_CONFIG_PATH}"
		#!/bin/bash
		# This file will be sourced in a a bash sub-shell by ${SCRIPT_NAME}
		# The start function will be called to start the jail
		# You can change the settings below and/or add custom code
		set -eEuo pipefail
		# Move into the directory where this script is stored (commands are relative to this directory)
		cd "\$(dirname "\${BASH_SOURCE[0]}")" || exit

		# Set RUN_DOCKER=1 to automatically add additional arguments required to properly run docker inside the jail
		RUN_DOCKER=${DOCKER_COMPATIBLE}
		# Set GPU_PASSTHROUGH=1 to automatically add additional arguments to access the GPU inside the jail
		GPU_PASSTHROUGH=${GPU_PASSTHROUGH}

		# You may add additional args to the two arrays below
		# These args will be passed to systemd-run and systemd-nspawn in the start function
		SYSTEMD_RUN_ADDITIONAL_ARGS=(${systemd_run_additional_args})
		SYSTEMD_NSPAWN_ADDITIONAL_ARGS=(${systemd_nspawn_additional_args})

		start(){
			# Use mostly default settings for systemd-nspawn but with systemd-run instead of a service file
			# https://github.com/systemd/systemd/blob/main/units/systemd-nspawn%40.service.in
			systemd-run --property=KillMode=mixed --property=Type=notify --property=RestartForceExitStatus=133 \\
				--property=SuccessExitStatus=133 --property=Delegate=yes --property=TasksMax=16384 --same-dir \\
				--collect --setenv=SYSTEMD_NSPAWN_LOCK=0 \\
				"\${SYSTEMD_RUN_ADDITIONAL_ARGS[@]}" \\
				-- \\
				systemd-nspawn --keep-unit --quiet --boot \\
				"\${SYSTEMD_NSPAWN_ADDITIONAL_ARGS[@]}"
		}

		# Call the start function if this script is executed directly (not sourced)
		# https://stackoverflow.com/a/28776166
		(return 0 2>/dev/null) || {
			echo 'This script was called directly, not sourced.'
			echo 'The jail will now start...'
			echo 'But the RUN_DOCKER and GPU_PASSTHROUGH settings are not considered.'
			echo 'For this to work, start the jail from ${SCRIPT_NAME}.'
			start
		}
	EOF

	echo "FROM CONF"
	cat "${JAIL_CONFIG_PATH}"
	chmod 700 "${JAIL_CONFIG_PATH}"

	echo "Done creating the jail."
	DONE=1
	echo
	read -p "Start the jail now? [Y/n] " -n 1 -r REPLY && echo
	# Enter accepts default (yes)
	if [[ "${REPLY}" =~ ^([Yy]|)$ ]]; then
		run_jail "${JAIL_CONFIG_PATH}"
	else
		echo 'Skipped starting jail.'
	fi
}

create_jail

# TODO document
# machinectl shell
# If that doesn't work try
# machinectl login
# But since there's no root password set, that won't work either
# So you'd have to get a shell via
# nsenter -t $(machinectl show alpine -p Leader --value) -a /bin/sh -l
# Then set a root password via passwd
# Then you may login via
# machinectl login
# TODO: recommend ssh ;)
# TODO: create a jlmkr shell command to try the above in case machinectl shell doesn't work
