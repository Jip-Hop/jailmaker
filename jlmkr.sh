#!/bin/bash

set -euo pipefail
shopt -s nullglob

ABSOLUTE_SCRIPT_PATH="$(realpath "${BASH_SOURCE[0]}")"
SCRIPT_NAME=$(basename "${ABSOLUTE_SCRIPT_PATH}")
SCRIPT_DIR_PATH="$(dirname "${ABSOLUTE_SCRIPT_PATH}")"

BOLD=$(tput bold)
RED=$(tput setaf 1)
YELLOW=$(tput setaf 3)
NORMAL=$(tput sgr0)

DISCLAIMER="${YELLOW}${BOLD}USING THIS SCRIPT IS AT YOUR OWN RISK!
IT COMES WITHOUT WARRANTY AND IS NOT SUPPORTED BY IX-SYSTEMS.${NORMAL}"

JAILS_DIR_PATH='jails'
JAIL_ROOTFS_NAME='rootfs'
JAIL_CONFIG_NAME='config'

USAGE="${DISCLAIMER}

Version: 0.0.0

Usage: ./${SCRIPT_NAME} [COMMAND] [NAME]

Commands:
  create	Create new jail [NAME] in the ${JAILS_DIR_PATH} dir
  start		Start jail NAME from the ${JAILS_DIR_PATH} dir
"

error() {
	echo -e "${RED}${BOLD}${1}${NORMAL}" >&2
}

fail() {
	error "${1}" && exit 1
}

[[ $UID -ne 0 ]] && echo "${USAGE}" && fail "Run this script as root..."

trace() {
	# https://unix.stackexchange.com/a/504829/477308
	echo 'Error occurred:'
	awk 'NR>L-4 && NR<L+4 { printf "%-5d%3s%s\n",NR,(NR==L?">>>":""),$0 }' L="${1}" "${ABSOLUTE_SCRIPT_PATH}"
}

# Trap errors
trap 'trace $LINENO' ERR

#####################
# START FUNCTIONALITY
#####################

start_jail() {
	[[ -z "${1}" ]] && fail "Please specify the name of the jail to start."
	local jail_name="${1}"
	local jail_path="${JAILS_DIR_PATH}/${jail_name}"
	local jail_config_path="${jail_path}/${JAIL_CONFIG_NAME}"

	! [[ -f "${jail_config_path}" ]] && fail "ERROR: Couldn't find: ${jail_config_path}."

	echo 'Loading config...'

	local key value

	while read -r line || [ -n "$line" ]; do
		key="${line%%=*}"
		value="${line#*=}"

		case "${key}" in
		"DOCKER_COMPATIBLE") local docker_compatible="${value}" ;;
		"GPU_PASSTHROUGH") local gpu_passthrough="${value}" ;;
		"SYSTEMD_NSPAWN_USER_ARGS") local systemd_nspawn_user_args="${value}" ;;
		"SYSTEMD_RUN_DEFAULT_ARGS") local systemd_run_default_args="${value}" ;;
		"SYSTEMD_NSPAWN_DEFAULT_ARGS") local systemd_nspawn_default_args="${value}" ;;
		esac

	done <"${jail_config_path}"

	echo 'Config loaded!'

	local systemd_run_additional_args=("--unit=jlmkr-${jail_name}" "--working-directory=./${jail_path}" "--description=My nspawn jail ${jail_name} [created with jailmaker]")
	local systemd_nspawn_additional_args=("--machine=${jail_name}" "--directory=${JAIL_ROOTFS_NAME}")

	if [[ "${docker_compatible}" -eq 1 ]]; then
		# Enable ip forwarding on the host (docker needs it)
		echo 1 >/proc/sys/net/ipv4/ip_forward
		
		# To properly run docker inside the jail, we need to lift restrictions
		# Without DevicePolicy=auto images with device nodes may not be pulled
		# For example docker pull ljishen/sysbench would fail
		#
		# Issue: https://github.com/moby/moby/issues/35245
		# Workaround: https://github.com/kinvolk/kube-spawn/pull/328
		# However, it seems like the DeviceAllow= workaround may break in
		# a future Debian release with systemd version 250 or higher
		# https://github.com/systemd/systemd/issues/21987
		#
		# The systemd-nspawn manual explicitly mentions:
		# Device nodes may not be created
		# https://www.freedesktop.org/software/systemd/man/systemd-nspawn.html
		#
		# Fortunately I didn't encounter many images with device nodes...
		#
		# Use SYSTEMD_SECCOMP=0: https://github.com/systemd/systemd/issues/18370
		systemd_run_additional_args+=(--setenv=SYSTEMD_SECCOMP=0 --property=DevicePolicy=auto)
		# Add additional flags required for docker
		systemd_nspawn_additional_args+=(--capability=all "--system-call-filter=add_key keyctl bpf")
	fi

	if [[ "${gpu_passthrough}" -eq 1 ]]; then
		systemd_nspawn_additional_args+=("--property=DeviceAllow=char-drm rw")

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

	local args=()

	# Build the array of arguments
	local arg
	# Append each argument, one at a time, to the array
	while read -r arg; do args+=("${arg}"); done < <(printf '%s' "${systemd_run_default_args}" | xargs -n 1)
	# Append each element in systemd_run_additional_args to the args array
	args+=("${systemd_run_additional_args[@]}")
	# Add two more args to the array
	args+=(-- systemd-nspawn)
	# Append each argument, one at a time, to the array
	while read -r arg; do args+=("${arg}"); done < <(printf '%s' "${systemd_nspawn_default_args}" | xargs -n 1)
	# Append each element in systemd_nspawn_additional_args to the args array
	args+=("${systemd_nspawn_additional_args[@]}")
	# Append each argument, one at a time, to the array
	while read -r arg; do args+=("${arg}"); done < <(printf '%s' "${systemd_nspawn_user_args}" | xargs -n 1)

	# Concat all arguments in the array into a single space separated string,
	# but use %q to output each argument in a format that can be reused as shell input
	# This escapes special characters for us, which were 'lost' when xargs read the input above
	# https://ss64.com/bash/printf.html
	args_string="$(printf '%q ' "${args[@]}")"

	echo
	echo "All the arguments to pass to systemd-run:"
	printf '%s' "${args_string}" | xargs -n 1
	echo
	echo "Starting jail with the following command:"
	echo
	echo "systemd-run ${args_string}"
	echo

	printf '%s' "${args_string}" | xargs systemd-run || {
		echo
		error 'Failed to start the jail...'
		fail "Please check and fix the config file with \"nano ${jail_config_path}\"."
	}

	echo
	echo "Check logging:"
	echo "journalctl -u jlmkr-${jail_name}"
	echo
	echo "Check status:"
	echo "systemctl status jlmkr-${jail_name}"
	echo
	echo "Stop the jail:"
	echo "machinectl stop ${jail_name}"
	echo
	echo "Get a shell:"
	echo "machinectl shell ${jail_name}"
}

######################
# CREATE FUNCTIONALITY
######################

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
	echo -e "${DISCLAIMER}"
	echo

	local name_from_arg="${1}"
	local arch
	arch="$(dpkg --print-architecture)"
	local lxc_dir_path='.lxc'
	local lxc_cache_path="${lxc_dir_path}/cache"
	local lxc_download_script_path="${lxc_dir_path}/lxc-download.sh"

	[[ "$(basename "${SCRIPT_DIR_PATH}")" != 'jailmaker' ]] && {
		error "${SCRIPT_NAME} needs to create files."
		error "Currently it can't decide if it's safe to create files in:"
		error "${SCRIPT_DIR_PATH}"
		fail "Please create a dedicated directory called 'jailmaker', store ${SCRIPT_NAME} there and try again."
	}

	local reply

	if [[ $(findmnt --target . --output TARGET --noheadings --first-only) != /mnt/* ]]; then
		echo "${YELLOW}${BOLD}WARNING: BEWARE OF DATA LOSS${NORMAL}"
		echo
		echo "${SCRIPT_NAME} should be on a dataset mounted under /mnt (it currently isn't)."
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

	local distro='debian' release='bullseye'

	read -p "Install the recommended distro (Debian 11)? [Y/n] " -n 1 -r reply && echo
	if ! [[ "${reply}" =~ ^([Yy]|)$ ]]; then
		echo
		echo "${YELLOW}${BOLD}WARNING: ADVANCED USAGE${NORMAL}"
		echo
		echo "You may now choose from a list which distro to install."
		echo "But not all of them will work with ${SCRIPT_NAME} since these images are made for LXC."
		echo "Distros based on systemd probably work (e.g. Ubuntu, Arch Linux and Rocky Linux)."
		echo "Others (Alpine, Devuan, Void Linux) probably won't."
		echo
		read -p "Press any key to continue: " -n 1 -r reply && echo
		echo
		lxc_cache_path=${lxc_cache_path} "${lxc_download_script_path}" --list --arch="${arch}" || :
		echo
		echo "Choose from the DIST column."
		echo
		read -e -r -p "Distribution: " distro && echo
		echo "Choose from the RELEASE column (or ARCH if RELEASE is empty)."
		echo
		read -e -r -p "Release: " release
	fi
	echo
	local jail_name jail_path

	while true; do
		read -e -r -p "Enter jail name: " -i "${name_from_arg}" jail_name && echo
		if ! [[ "${jail_name}" =~ ^[.a-zA-Z0-9-]{1,64}$ && "${jail_name}" != '.'* && "${jail_name}" != *'.' && "${jail_name}" != *'..'* ]]; then
			cat <<-EOF
				${YELLOW}${BOLD}WARNING: INVALID NAME${NORMAL}

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

	echo "Docker won't be installed by ${SCRIPT_NAME}."
	echo "But it can setup the jail with the capabilities required to run docker."
	echo "You can turn DOCKER_COMPATIBLE mode on/off post-install."
	echo
	read -p "Make jail docker compatible right now? [y/N] " -n 1 -r reply && echo
	# Enter accepts default (no)
	if ! [[ "${reply}" =~ ^[Yy]$ ]]; then docker_compatible=0; else docker_compatible=1; fi
	echo
	read -p "Give access to the GPU inside the jail? [y/N] " -n 1 -r reply && echo
	# Enter accepts default (no)
	if ! [[ "${reply}" =~ ^[Yy]$ ]]; then gpu_passthrough=0; else gpu_passthrough=1; fi
	echo
	echo "${YELLOW}${BOLD}WARNING: CHECK SYNTAX${NORMAL}"
	echo
	echo "You may pass additional flags to systemd-nspawn."
	echo "With incorrect flags the jail may not start."
	echo "It's possible to correct/add/remove flags post-install."
	echo
	read -p "Show the man page for systemd-nspawn? [y/N] " -n 1 -r reply && echo

	# Enter accepts default (no)
	if [[ "${reply}" =~ ^[Yy]$ ]]; then
		man systemd-nspawn
	else
		echo
		echo "You may read the systemd-nspawn manual online:"
		echo "https://manpages.debian.org/${distro}/systemd-container/systemd-nspawn.1.en.html"
	fi

	# Backslashes and colons need to be escaped in bind mount options:
	# e.g. to bind mount a file called:
	# weird chars :?\"
	# the corresponding command would be:
	# --bind-ro='/mnt/data/weird chars \:?\\"'

	echo
	echo "For example to mount directories inside the jail you may add:"
	echo "--bind=/mnt/a/readwrite/directory --bind-ro=/mnt/a/readonly/directory"
	echo
	read -e -r -p "Additional flags: " systemd_nspawn_user_args && echo

	# Create directory for rootfs
	JAIL_ROOTFS_PATH="${jail_path}/${JAIL_ROOTFS_NAME}"
	mkdir -p "${JAIL_ROOTFS_PATH}"

	local jail_config_path="${jail_path}/${JAIL_CONFIG_NAME}"
	# LXC download script needs to write to this file during install
	# but we don't need it so we will remove it later
	touch "${jail_config_path}"

	LXC_CACHE_PATH=${lxc_cache_path} "${lxc_download_script_path}" \
		--name="${jail_name}" --path="${jail_path}" --rootfs="${JAIL_ROOTFS_PATH}" \
		--arch="${arch}" --dist="${distro}" --release="${release}" ||
		fail "Aborted creating rootfs..."
	echo

	# Assuming the name of your jail is "myjail"
	# and "machinectl shell myjail" doesn't work
	# Try:
	#
	# Stop the jail with:
	# machinectl stop myjail
	# And start a shell inside the jail without the --boot option:
	# systemd-nspawn -q -D jails/myjail/rootfs /bin/sh
	# Then set a root password with:
	# In case of amazonlinux you may need to run:
	# yum update -y && yum install -y passwd
	# passwd
	# exit
	# Then you may login from the host via:
	# machinectl login myjail
	#
	# You could also enable SSH inside the jail to login
	#
	# Or if that doesn't work (e.g. for alpine) get a shell via:
	# nsenter -t $(machinectl show myjail -p Leader --value) -a /bin/sh -l
	# But alpine jails made with jailmaker have other issues
	# They don't shutdown cleanly via systemctl and machinectl...

	if [[ "$(basename "$(readlink -f "${JAIL_ROOTFS_PATH}/sbin/init")")" != systemd ]]; then
		echo "${YELLOW}${BOLD}WARNING: DISTRO NOT SUPPORTED${NORMAL}"
		echo
		echo "Chosen distro appears not to use systemd..."
		echo
		echo "You probably won't get a shell with:"
		echo "machinectl shell ${jail_name}"
		echo
		echo "You may get a shell with this command:"
		# About nsenter:
		# shellcheck disable=SC2016
		echo 'nsenter -t $(machinectl show '"${jail_name}"' -p Leader --value) -a /bin/sh -l'
		echo
		echo 'Read about the downsides of nsenter:'
		echo 'https://github.com/systemd/systemd/issues/12785#issuecomment-503019081'
		echo
		echo "${BOLD}Using this distro with ${SCRIPT_NAME} is NOT recommended.${NORMAL}"
		echo
		read -p "Abort creating jail? [Y/n] " -n 1 -r reply && echo
		# Enter accepts default (yes)
		[[ "${reply}" =~ ^([Yy]|)$ ]] && exit
		echo
	fi

	# Config which systemd handles for us
	rm -f "${JAIL_ROOTFS_PATH}/etc/machine-id"
	rm -f "${JAIL_ROOTFS_PATH}/etc/resolv.conf"
	rm -f "${JAIL_ROOTFS_PATH}/etc/resolv.conf"
	# https://github.com/systemd/systemd/issues/852
	printf 'pts/%d\n' $(seq 0 10) >"${JAIL_ROOTFS_PATH}/etc/securetty"

	# Use mostly default settings for systemd-nspawn but with systemd-run instead of a service file:
	# https://github.com/systemd/systemd/blob/main/units/systemd-nspawn%40.service.in
	# Use TasksMax=infinity since this is what docker does:
	# https://github.com/docker/engine/blob/master/contrib/init/systemd/docker.service

	# Use SYSTEMD_NSPAWN_LOCK=0: otherwise jail won't start jail after a shutdown (but why?)
	# Would give "directory tree currently busy" error and I'd have to run
	# `rm /run/systemd/nspawn/locks/*` and remove the .lck file from jail_path
	# Disabling locking isn't a big deal as systemd-nspawn will prevent starting a container
	# with the same name anyway: as long as we're starting jails using this script,
	# it won't be possible to start the same jail twice

	local systemd_run_default_args=(--property=KillMode=mixed --property=Type=notify --property=RestartForceExitStatus=133
		--property=SuccessExitStatus=133 --property=Delegate=yes --property=TasksMax=infinity --collect
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
		echo
		echo 'Skipped starting jail.'
	fi
}

#######################
# COMMAND LINE HANDLING
#######################

case "${1-""}" in

'')
	read -p "Create a new jail? [Y/n] " -n 1 -r reply && echo
	echo
	# Enter accepts default (yes)
	# https://stackoverflow.com/a/1885534
	if [[ "${reply}" =~ ^([Yy]|)$ ]]; then
		create_jail ""
	else

		echo "${USAGE}"
	fi
	;;

create)
	create_jail "${2-""}"
	;;

start)
	start_jail "${2-""}"
	;;

*)
	echo "${USAGE}"
	;;
esac
