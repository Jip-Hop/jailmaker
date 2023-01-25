#!/bin/bash

set -eEuo pipefail
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
JAIL_PATH=
JAIL_CONFIG_NAME='config'
JAIL_START_SCRIPT_NAME='start.sh'

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

#########################
# START RUN FUNCTIONALITY
#########################

start_jail() {
	local jail_config_path jail_start_script_path docker_compatible gpu_passthrough key value

	jail_config_path="${1}/${JAIL_CONFIG_NAME}"
	jail_start_script_path="${1}/${JAIL_START_SCRIPT_NAME}"

	! [[ -f "${jail_start_script_path}" ]] && fail "ERROR: Couldn't find: ${jail_start_script_path}"
	! [[ -f "${jail_config_path}" ]] && fail "ERROR: Couldn't find: ${jail_config_path}"

	echo 'Load the config'

	# TODO: also load the additional (user) args for nspawn from this file!
	while IFS="=" read -r key value || [ -n "$key" ]; do
		case "${key}" in
		"DOCKER_COMPATIBLE") docker_compatible="$value" ;;
		"GPU_PASSTHROUGH") gpu_passthrough="$value" ;;
		esac
	done <"${jail_config_path}"

	echo 'Config loaded'

	SYSTEMD_RUN_ADDITIONAL_ARGS=()
	SYSTEMD_NSPAWN_ADDITIONAL_ARGS=()

	if [[ "${docker_compatible}" -eq 1 ]]; then
		# Enable ip forwarding on the host (docker needs it)
		echo 1 >/proc/sys/net/ipv4/ip_forward
		# To properly run docker inside the jail, we need to lift restrictions
		# Without DevicePolicy=auto images with device nodes may not be pulled
		# https://github.com/kinvolk/kube-spawn/pull/328
		SYSTEMD_RUN_ADDITIONAL_ARGS+=(--setenv=SYSTEMD_SECCOMP=0 --property=DevicePolicy=auto)
		# Add additional flags required for docker
		SYSTEMD_NSPAWN_ADDITIONAL_ARGS+=(--capability=all --system-call-filter='add_key keyctl bpf')
	fi

	if [[ "${gpu_passthrough}" -eq 1 ]]; then
		SYSTEMD_NSPAWN_ADDITIONAL_ARGS+=(--property=DeviceAllow='char-drm rw')

		# Detect intel GPU device and if present add bind flag
		[[ -d /dev/dri ]] && SYSTEMD_NSPAWN_ADDITIONAL_ARGS+=(--bind=/dev/dri)

		# TODO: add bind mount flags in case of nvidia GPU passthrough
	fi

	# Pass the two arrays to the start script
	# https://stackoverflow.com/a/43687593
	echo "Starting jail..."

	"./${jail_start_script_path}" \
		"${#SYSTEMD_RUN_ADDITIONAL_ARGS[@]}" "${SYSTEMD_RUN_ADDITIONAL_ARGS[@]}" \
		"${#SYSTEMD_NSPAWN_ADDITIONAL_ARGS[@]}" "${SYSTEMD_NSPAWN_ADDITIONAL_ARGS[@]}"
}

############################
# START CREATE FUNCTIONALITY
############################

cleanup() {
	# Remove the JAIL_PATH (if set, a directory and not the root directory)
	[[ -d "${JAIL_PATH}" ]] && echo -e "\n\nCleaning up: ${JAIL_PATH}\n" && rm -rf "${JAIL_PATH}"
}

stat_chmod() {
	# Only run chmod if mode is different from current mode
	if [[ "$(stat -c%a "${2}")" -ne "${1}" ]]; then chmod "${1}" "${2}"; fi
}

validate_download_script() {
	echo "6cca2eda73c7358c232fecb4e750b3bf0afa9636efb5de6a9517b7df78be12a4  ${1}" | sha256sum --check >/dev/null
}

# Use a function as template instead of heredoc
# This allows syntax highlighting and linting to work
# Template function must return the line number,
# this marks the start of the template
template_start_script() {
	echo "$((LINENO + 1))" && return
	# TEMPLATE START
	#!/bin/bash
	set -euo pipefail

	# If this script is called from PLACEHOLDER_SCRIPT_NAME
	# and DOCKER_COMPATIBLE or GPU_PASSTHROUGH is enabled
	# then these arrays will be filled with additional args
	SYSTEMD_RUN_ADDITIONAL_ARGS=("${@:2:$1}") && shift "$(($1 + 1))"
	SYSTEMD_NSPAWN_ADDITIONAL_ARGS=("${@:2:$1}") && shift "$(($1 + 1))"

	# Move into the directory where this script is stored (commands are relative to this directory)
	cd "$(dirname "${BASH_SOURCE[0]}")" || exit
	# Get the name of the jail from the directory name
	JAIL_NAME="$(basename "$(pwd)")"

	# Use mostly default settings for systemd-nspawn but with systemd-run instead of a service file
	# https://github.com/systemd/systemd/blob/main/units/systemd-nspawn%40.service.in
	# TODO: also compare settings for docker: https://github.com/docker/engine/blob/master/contrib/init/systemd/docker.service
	systemd-run --property=KillMode=mixed --property=Type=notify --property=RestartForceExitStatus=133 \
		--property=SuccessExitStatus=133 --property=Delegate=yes --property=TasksMax=16384 --same-dir \
		--collect --setenv=SYSTEMD_NSPAWN_LOCK=0 \
		--unit="jlmkr-${JAIL_NAME}" --description="jailmaker ${JAIL_NAME}" \
		"${SYSTEMD_RUN_ADDITIONAL_ARGS[@]}" \
		-- \
		systemd-nspawn --keep-unit --quiet --boot \
		--machine="${JAIL_NAME}" --directory='./PLACEHOLDER_ROOTFS_NAME' \
		PLACEHOLDER_SYSTEMD_NSPAWN_USER_ARGS \
		"${SYSTEMD_NSPAWN_ADDITIONAL_ARGS[@]}"
	# TEMPLATE END
}

# Helper function to process the body of a function into a bash string
# which can be written as a new bash script
# Includes find-replace functionality to substitute placeholders in the template
process_template() {
	local indent=""
	# Read the current script file, starting from the passed line number
	while IFS=$'\n' read -r line; do
		# Get the indent level from the first line
		[[ -z "${indent}" ]] && indent="${line%%#*}" && continue

		# Break when we find the end of the template
		[[ "$line" = "${indent}# TEMPLATE END" ]] && break

		# Remove the indent from the start
		line="${line#"$indent"}"

		local find replace
		# Loop over the additional argument pairs passed
		# and find/replace template key with value
		for ((n = 2; n <= $#; n++)); do
			# https://stackoverflow.com/a/3575950
			# Indirect expansion: look up the value of the variable whose name is in the variable
			# So this looks up the nth argument passed to this function
			find=${!n}
			# Increment counter by one to get next argument
			((n++))
			replace=${!n}
			line=${line//$find/$replace}
		done

		echo "${line}"
	done < <(tail -n "+${1}" "${ABSOLUTE_SCRIPT_PATH}")
}

create_jail() {
	# TODO: show disclaimer
	local reply arch distro release lxc_dir_path lxc_cache_path lxc_download_script_path
	local jail_config_path jail_start_script_path docker_compatible gpu_passthrough
	local jail_name systemd_nspawn_user_args

	arch="$(dpkg --print-architecture)"
	lxc_dir_path='.lxc'
	lxc_cache_path="${lxc_dir_path}/cache"
	lxc_download_script_path="${lxc_dir_path}/lxc-download.sh"

	[[ "$(basename "${SCRIPT_DIR_PATH}")" != 'jailmaker' ]] && {
		echo "${SCRIPT_NAME} needs to create files."
		echo "Currently it can't decide if it's safe to create files in:"
		echo "${SCRIPT_DIR_PATH}"
		fail "Please create a dedicated directory called 'jailmaker', store ${SCRIPT_NAME} there and try again."
	}

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
			JAIL_PATH="${JAILS_DIR_PATH}/${jail_name}"

			if [[ -e "${JAIL_PATH}" ]]; then
				echo "A jail with this name already exists."
				echo
			else
				# Accept the name
				break
			fi
		fi
	done

	# Cleanup on exit, but only once the JAIL_PATH is final
	# Otherwise we may cleanup the wrong directory
	trap cleanup EXIT

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

	# TODO: ask for network setup (host, macvlan, bridge, physical nic)
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
	JAIL_ROOTFS_PATH="${JAIL_PATH}/${JAIL_ROOTFS_NAME}"
	mkdir -p "${JAIL_ROOTFS_PATH}"

	jail_config_path="${JAIL_PATH}/${JAIL_CONFIG_NAME}"
	# LXC download script needs to write to this file during install
	# but we don't need it so we will remove it later
	touch "${jail_config_path}"

	echo
	LXC_CACHE_PATH=${lxc_cache_path} "${lxc_download_script_path}" \
		--name="${jail_name}" --path="${JAIL_PATH}" --rootfs="${JAIL_ROOTFS_PATH}" \
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

	jail_start_script_path="${JAIL_PATH}/${JAIL_START_SCRIPT_NAME}"

	cat <<-EOF >"${jail_config_path}"
		DOCKER_COMPATIBLE=${docker_compatible}
		GPU_PASSTHROUGH=${gpu_passthrough}
	EOF

	chmod 700 "${jail_config_path}"

	process_template "$(template_start_script)" \
		PLACEHOLDER_ROOTFS_NAME "${JAIL_ROOTFS_NAME}" PLACEHOLDER_SYSTEMD_NSPAWN_USER_ARGS "${systemd_nspawn_user_args}" \
		PLACEHOLDER_SCRIPT_NAME "${SCRIPT_NAME}" >"${jail_start_script_path}"

	chmod 700 "${jail_start_script_path}"

	# Remove the cleanup trap on exit
	trap - EXIT
	echo "Done creating the jail."
	echo
	read -p "Start the jail now? [Y/n] " -n 1 -r reply && echo
	# Enter accepts default (yes)
	if [[ "${reply}" =~ ^([Yy]|)$ ]]; then
		start_jail "${JAIL_PATH}"
	else
		echo 'Skipped starting jail.'
	fi
}

##########################
# END CREATE FUNCTIONALITY
##########################

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
	start_jail "${JAILS_DIR_PATH}/${2}"
	;;

*)
	echo "${USAGE}"
	;;
esac
