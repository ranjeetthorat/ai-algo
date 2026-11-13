#!/bin/bash

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# OpenAlgo Fleet Update Script
# Runs on the OPERATOR's machine (not on a client server). It SSHes into each
# host in a list and runs that host's install/update.sh, so one fix merged to
# main rolls out to every client. Hosts are updated one at a time; a failure on
# one host does not stop the rest, and the run ends with a summary.
#
#   ./update-all.sh                        # use /etc/openalgo/fleet.hosts
#   ./update-all.sh --hosts ./fleet.hosts  # use a specific list
#   ./update-all.sh --dry-run              # show targets and the command, run nothing
#
# Requirements on the operator machine:
#   - key-based SSH to each host (BatchMode is used; password prompts are not)
#   - the remote user can run update.sh with sudo without a password, OR is root
#
# Hosts file: one target per line, "user@host" or "user@host:port" or "host".
# Blank lines and lines starting with # are ignored.

HOSTS_FILE="/etc/openalgo/fleet.hosts"
DRY_RUN=false
SSH_TIMEOUT="${SSH_TIMEOUT:-15}"

# The command run on each host. Override with REMOTE_UPDATE_CMD for a non-default
# install path or a legacy multi-deploy layout.
REMOTE_UPDATE_CMD="${REMOTE_UPDATE_CMD:-sudo bash -lc 'cd /var/python/openalgo/install && ./update.sh'}"

log_message() {
    local message="$1" color="$2"
    echo -e "${color}${message}${NC}"
}

while [ $# -gt 0 ]; do
    case "$1" in
        --hosts) HOSTS_FILE="$2"; shift 2 ;;
        --dry-run) DRY_RUN=true; shift ;;
        -h|--help)
            echo "Usage: ./update-all.sh [--hosts FILE] [--dry-run]"
            echo "Env:   SSH_TIMEOUT (default 15), REMOTE_UPDATE_CMD"
            exit 0 ;;
        *) log_message "Unknown option: $1" "$RED"; exit 1 ;;
    esac
done

if [ ! -f "$HOSTS_FILE" ]; then
    log_message "Hosts file not found: $HOSTS_FILE" "$RED"
    log_message "Create it (one user@host per line) or pass --hosts FILE." "$YELLOW"
    exit 1
fi

# Read non-comment, non-blank lines into an array.
TARGETS=()
while IFS= read -r line; do
    line="${line%%#*}"                       # strip inline comments
    line="$(echo "$line" | xargs)"           # trim whitespace
    [ -n "$line" ] && TARGETS+=("$line")
done < "$HOSTS_FILE"

if [ ${#TARGETS[@]} -eq 0 ]; then
    log_message "No hosts listed in $HOSTS_FILE" "$RED"
    exit 1
fi

log_message "Fleet update over ${#TARGETS[@]} host(s) from $HOSTS_FILE" "$BLUE"
log_message "Remote command: $REMOTE_UPDATE_CMD" "$BLUE"
echo ""

if [ "$DRY_RUN" = true ]; then
    log_message "Dry run. These hosts would be updated, one at a time:" "$YELLOW"
    for t in "${TARGETS[@]}"; do echo "  $t"; done
    exit 0
fi

OK=()
FAILED=()

for target in "${TARGETS[@]}"; do
    # Split an optional :port into -p for ssh.
    host="$target"; port=""
    if [[ "$target" == *:* ]]; then
        host="${target%:*}"; port="${target##*:}"
    fi
    ssh_opts=(-o BatchMode=yes -o ConnectTimeout="$SSH_TIMEOUT")
    [ -n "$port" ] && ssh_opts+=(-p "$port")

    log_message "========================================" "$BLUE"
    log_message "Updating $target" "$BLUE"
    log_message "========================================" "$BLUE"
    if ssh "${ssh_opts[@]}" "$host" "$REMOTE_UPDATE_CMD"; then
        log_message "OK: $target" "$GREEN"
        OK+=("$target")
    else
        log_message "FAILED: $target (see output above)" "$RED"
        FAILED+=("$target")
    fi
    echo ""
done

log_message "========================================" "$GREEN"
log_message "  Fleet Update Summary" "$GREEN"
log_message "========================================" "$GREEN"
log_message "Updated: ${#OK[@]}/${#TARGETS[@]}" "$GREEN"
if [ ${#FAILED[@]} -ne 0 ]; then
    log_message "Failed:  ${#FAILED[@]}" "$RED"
    for t in "${FAILED[@]}"; do log_message "  $t" "$RED"; done
    exit 1
fi
log_message "All hosts updated successfully." "$GREEN"
