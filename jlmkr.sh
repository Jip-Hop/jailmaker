#!/bin/bash

set -euo pipefail
shopt -s nullglob

ABSOLUTE_SCRIPT_PATH="$(realpath "${BASH_SOURCE[0]}")"
SCRIPT_NAME=$(basename "${ABSOLUTE_SCRIPT_PATH}")
SCRIPT_DIR_PATH="$(dirname "${ABSOLUTE_SCRIPT_PATH}")"

USAGE="WARNING: EXPERIMENTAL AND WORK IN PROGRESS, USE ONLY FOR TESTING!
TODO: add version string
Usage: ./${SCRIPT_NAME} COMMAND [ARG...]

TODO: complete writing usage
"

JAILS_DIR_PATH='jails'
JAIL_ROOTFS_NAME='rootfs'
JAIL_CONFIG_NAME='config'

fail() {
	echo -e "$1" >&2 && exit 1
}

[[ $UID -ne 0 ]] && echo "${USAGE}" && fail "Run this script as root..."

err() {
	# https://unix.stackexchange.com/a/504829/477308
	echo 'Error occurred:'
	awk 'NR>L-4 && NR<L+4 { printf "%-5d%3s%s\n",NR,(NR==L?">>>":""),$0 }' L="${1}" "${ABSOLUTE_SCRIPT_PATH}"
}

# Trap errors
trap 'err $LINENO' ERR

#####################
# START FUNCTIONALITY
#####################

start_jail() {
	local jail_name="${1}"
	local jail_path="${JAILS_DIR_PATH}/${jail_name}"
	local jail_config_path="${jail_path}/${JAIL_CONFIG_NAME}"

	! [[ -f "${jail_config_path}" ]] && fail "ERROR: Couldn't find: ${jail_config_path}"

	echo 'Load the config'

	local key value

	while read -r line || [ -n "$line" ]; do
		key="${line%%=*}"
		value="${line#*=}"

		case "${key}" in
		"DOCKER_COMPATIBLE") local docker_compatible="$value" ;;
		"GPU_PASSTHROUGH") local gpu_passthrough="$value" ;;
		"SYSTEMD_NSPAWN_USER_ARGS") local systemd_nspawn_user_args="$value" ;;
		"SYSTEMD_RUN_DEFAULT_ARGS") local systemd_run_default_args="$value" ;;
		"SYSTEMD_NSPAWN_DEFAULT_ARGS") local systemd_nspawn_default_args="$value" ;;
		esac

	done <"${jail_config_path}"

	echo 'Config loaded'

	local systemd_run_additional_args=("--unit='jlmkr-${jail_name}'" "--working-directory='./${jail_path}'" "--description='jailmaker ${jail_name}'")
	local systemd_nspawn_additional_args=("--machine='${jail_name}'" "--directory='${JAIL_ROOTFS_NAME}'")

	if [[ "${docker_compatible}" -eq 1 ]]; then
		# Enable ip forwarding on the host (docker needs it)
		echo 1 >/proc/sys/net/ipv4/ip_forward
		# To properly run docker inside the jail, we need to lift restrictions
		# Without DevicePolicy=auto images with device nodes may not be pulled
		# https://github.com/kinvolk/kube-spawn/pull/328
		systemd_run_additional_args+=(--setenv=SYSTEMD_SECCOMP=0 --property=DevicePolicy=auto)
		# Add additional flags required for docker
		systemd_nspawn_additional_args+=(--capability=all "--system-call-filter='add_key keyctl bpf'")
	fi

	if [[ "${gpu_passthrough}" -eq 1 ]]; then
		systemd_nspawn_additional_args+=("--property=DeviceAllow='char-drm rw'")

		# Detect intel GPU device and if present add bind flag
		[[ -d /dev/dri ]] && systemd_nspawn_additional_args+=(--bind=/dev/dri)

		# Detect nvidia GPU
		if [[ -d /dev/nvidia ]]; then
			# Mount the nvidia driver files, so we are always in sync with the host
			while read -r line; do
				if [[ "${line}" == /dev/* ]]; then
					systemd_nspawn_additional_args+=("--bind='${line}'")
				else
					systemd_nspawn_additional_args+=("--bind-ro='${line}'")
				fi
			done < <(nvidia-container-cli list)
		fi
	fi

	local cmd=(systemd-run "${systemd_run_default_args}" "${systemd_run_additional_args[*]}" --
		systemd-nspawn "${systemd_nspawn_default_args}" "${systemd_nspawn_additional_args[*]} ${systemd_nspawn_user_args}")

	echo "Starting jail with command:"
	echo "${cmd[*]}"

	eval "${cmd[*]}"
}

######################
# CREATE FUNCTIONALITY
#######################

cleanup() {
	# Remove the jail_path if it's a directory
	local jail_path="${1}"
	[[ -d "${jail_path}" ]] && echo -e "\n\nCleaning up: ${jail_path}\n" && rm -rf "${jail_path}"
}

stat_chmod() {
	# Only run chmod if mode is different from current mode
	if [[ "$(stat -c%a "${2}")" -ne "${1}" ]]; then chmod "${1}" "${2}"; fi
}

validate_download_script() {
	echo "6cca2eda73c7358c232fecb4e750b3bf0afa9636efb5de6a9517b7df78be12a4  ${1}" | sha256sum --check >/dev/null
}

create_jail() {
	# TODO: show disclaimer

	local arch
	arch="$(dpkg --print-architecture)"
	local lxc_dir_path='.lxc'
	local lxc_cache_path="${lxc_dir_path}/cache"
	local lxc_download_script_path="${lxc_dir_path}/lxc-download.sh"

	[[ "$(basename "${SCRIPT_DIR_PATH}")" != 'jailmaker' ]] && {
		echo "${SCRIPT_NAME} needs to create files."
		echo "Currently it can't decide if it's safe to create files in:"
		echo "${SCRIPT_DIR_PATH}"
		fail "Please create a dedicated directory called 'jailmaker', store ${SCRIPT_NAME} there and try again."
	}

	local reply

	if [[ $(findmnt --target . --output TARGET --noheadings --first-only) != /mnt/* ]]; then
		echo "${SCRIPT_NAME} should be on a pool mounted under /mnt (it currently isn't)."
		echo "Storing it on the boot-pool means losing all jails when updating TrueNAS."
		echo "If you continue, jails will be stored under:"
		echo "${SCRIPT_DIR_PATH}"
		read -p "Do you wish to ignore this warning and continue? [y/N] " -n 1 -r reply && echo
		# Enter accepts default (no)
		! [[ "${reply}" =~ ^[Yy]$ ]] && exit
	fi

	cd "${SCRIPT_DIR_PATH}" || fail "Could not change working directory to ${SCRIPT_DIR_PATH}..."

	# Set appropriate permissions (if not already set) for this file, since it's executed as root
	stat_chmod 700 "${SCRIPT_NAME}"

	# Create the lxc dirs if nonexistent
	mkdir -p "${lxc_dir_path}"
	stat_chmod 700 "${lxc_dir_path}"
	mkdir -p "${lxc_cache_path}"
	stat_chmod 700 "${lxc_cache_path}"

	# Create the dir where to store the jails
	mkdir -p "${JAILS_DIR_PATH}"
	stat_chmod 700 "${JAILS_DIR_PATH}"

	# Fetch the lxc download script if not present locally (or hash doesn't match)
	if ! validate_download_script "${lxc_download_script_path}"; then
		curl -fSL
		https://raw.githubusercontent.com/Jip-Hop/lxc/58520263041b6864cadad96278848f9b8ce78ee9/templates/lxc-download.in -o "${lxc_download_script_path}"
		# Validate after download to prevent executing arbitrary code as root
		validate_download_script "${lxc_download_script_path}" || fail 'Abort! Downloaded script has unexpected contents.'
	fi

	stat_chmod 700 "${lxc_download_script_path}"

	local distro release

	read -p "Install the recommended distro (Debian 11)? [Y/n] " -n 1 -r reply && echo
	if [[ "${reply}" =~ ^([Yy]|)$ ]]; then
		distro='debian'
		release='bullseye'
	else
		echo
		echo "ADVANCED USAGE"
		echo "You may now choose from a list which distro to install."
		echo "Not all of them will work with ${SCRIPT_NAME} (these images are made for LXC)."
		echo "Distros based on systemd probably work (e.g. Ubuntu, Arch Linux and Rocky Linux)."
		echo "Others (Alpine, Devuan, Void Linux) probably won't."
		echo
		read -p "Press any key to continue: " -n 1 -r reply && echo
		lxc_cache_path=${lxc_cache_path} "${lxc_download_script_path}" --list --arch="${arch}" || :
		echo "Choose from the DIST column."
		read -e -r -p "Distribution: " distro && echo
		echo "Choose from the RELEASE column (or ARCH if RELEASE is empty)."
		read -e -r -p "Release: " release && echo
	fi

	local jail_name jail_path

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
				# Accept the name
				break
			fi
		fi
	done

	# Cleanup on exit, but only once the jail_path is final
	# Otherwise we may cleanup the wrong directory
	trap 'cleanup "${jail_path}"' EXIT

	local docker_compatible gpu_passthrough systemd_nspawn_user_args

	echo "${SCRIPT_NAME} will not install docker for you."
	echo "But it can configure the jail with the capabilities required to run docker."
	echo "You can turn docker_compatible mode on/off post-install."
	echo
	read -p "Make jail docker compatible right now? [y/N] " -n 1 -r reply && echo
	# Enter accepts default (no)
	if ! [[ "${reply}" =~ ^[Yy]$ ]]; then docker_compatible=0; else docker_compatible=1; fi

	read -p "Give access to the GPU inside the jail? [y/N] " -n 1 -r reply && echo
	# Enter accepts default (no)
	if ! [[ "${reply}" =~ ^[Yy]$ ]]; then gpu_passthrough=0; else gpu_passthrough=1; fi

	# TODO: ask to show nspawn manual
	echo
	echo "You may pass additional systemd-nspawn flags."
	echo "For example to mount directories inside the jail you may add:"
	echo "--bind=/mnt/a/readwrite/directory --bind-ro=/mnt/a/readonly/directory"
	echo
	echo "Double check the syntax:"
	echo "https://manpages.debian.org/bullseye/systemd-container/systemd-nspawn.1.en.html"
	echo "With incorrect flags the jail may not start."
	echo "It's possible to correct/add/remove flags post-install."
	echo
	read -e -r -p "Additional flags: " systemd_nspawn_user_args && echo
	# Backslashes and colons need to be escaped for systemd-nspawn by the user:
	# e.g. to bind mount a file called:
	# weird chars :?\"
	# the corresponding command would be:
	# --bind-ro='/mnt/data/weird chars \:?\\"'

	# Create directory for rootfs
	JAIL_ROOTFS_PATH="${jail_path}/${JAIL_ROOTFS_NAME}"
	mkdir -p "${JAIL_ROOTFS_PATH}"

	local jail_config_path="${jail_path}/${JAIL_CONFIG_NAME}"
	# LXC download script needs to write to this file during install
	# but we don't need it so we will remove it later
	touch "${jail_config_path}"

	echo
	LXC_CACHE_PATH=${lxc_cache_path} "${lxc_download_script_path}" \
		--name="${jail_name}" --path="${jail_path}" --rootfs="${JAIL_ROOTFS_PATH}" \
		--arch="${arch}" --dist="${distro}" --release="${release}" ||
		fail "Aborted creating rootfs..."
	echo

	if [[ "$(basename "$(readlink -f "${JAIL_ROOTFS_PATH}/sbin/init")")" != systemd ]]; then
		echo "Chosen distro appears not to use systemd..."
		echo
		echo "You probably won't get a shell with:"
		echo "machinectl shell ${jail_name}"
		echo
		echo "You may get a shell with this command:"
		# About nsenter:
		# https://github.com/systemd/systemd/issues/12785#issuecomment-503019081
		# https://github.com/systemd/systemd/issues/3144
		# shellcheck disable=SC2016
		echo 'nsenter -t $(machinectl show '"${jail_name}"' -p Leader --value) -a /bin/sh -l'
		echo
		echo "Using this distro with ${SCRIPT_NAME} is not recommended."
		echo
		read -p "Abort creating jail? [Y/n] " -n 1 -r reply && echo
		# Enter accepts default (yes)
		[[ "${reply}" =~ ^([Yy]|)$ ]] && exit
	fi

	# Config which systemd handles for us
	rm -f "${JAIL_ROOTFS_PATH}/etc/machine-id"
	rm -f "${JAIL_ROOTFS_PATH}/etc/resolv.conf"
	rm -f "${JAIL_ROOTFS_PATH}/etc/resolv.conf"
	# https://github.com/systemd/systemd/issues/852
	printf 'pts/%d\n' $(seq 0 10) >"${JAIL_ROOTFS_PATH}/etc/securetty"

	# Use mostly default settings for systemd-nspawn but with systemd-run instead of a service file
	# https://github.com/systemd/systemd/blob/main/units/systemd-nspawn%40.service.in
	# TODO: also compare settings for docker: https://github.com/docker/engine/blob/master/contrib/init/systemd/docker.service

	local systemd_run_default_args=(--property=KillMode=mixed --property=Type=notify --property=RestartForceExitStatus=133
		--property=SuccessExitStatus=133 --property=Delegate=yes --property=TasksMax=16384 --collect
		--setenv=SYSTEMD_NSPAWN_LOCK=0)

	local systemd_nspawn_default_args=(--keep-unit --quiet --boot)

	{
		echo "DOCKER_COMPATIBLE=${docker_compatible}"
		echo "GPU_PASSTHROUGH=${gpu_passthrough}"
		echo "SYSTEMD_NSPAWN_USER_ARGS=${systemd_nspawn_user_args}"
		echo
		echo "# You generally won't need to change the options below"
		echo "SYSTEMD_RUN_DEFAULT_ARGS=${systemd_run_default_args[*]}"
		echo "SYSTEMD_NSPAWN_DEFAULT_ARGS=${systemd_nspawn_default_args[*]}"
	} >"${jail_config_path}"

	chmod 700 "${jail_config_path}"

	# Remove the cleanup trap on exit
	trap - EXIT
	echo "Done creating the jail."
	echo
	read -p "Start the jail now? [Y/n] " -n 1 -r reply && echo
	# Enter accepts default (yes)
	if [[ "${reply}" =~ ^([Yy]|)$ ]]; then
		start_jail "${jail_name}"
	else
		echo 'Skipped starting jail.'
	fi
}

#######################
# COMMAND LINE HANDLING
#######################

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
# TODO: document journalctl -u jlmkr-jailname

case "${1-""}" in

'')
	read -p "Create a new jail? [Y/n] " -n 1 -r reply && echo
	# Enter accepts default (yes)
	# https://stackoverflow.com/a/1885534
	if [[ "${reply}" =~ ^([Yy]|)$ ]]; then
		create_jail
	else
		echo "${USAGE}"
	fi
	;;

create)
	create_jail
	;;

start)
	start_jail "${2}"
	;;

*)
	echo "${USAGE}"
	;;
esac
