#!/bin/bash
#
# fastalgo - one simple command to run and maintain a FastAlgo server install.
#
# Installed to /usr/local/bin/fastalgo by install.sh. It is a thin, friendly
# wrapper over systemctl and the ops scripts (update.sh, change-broker.sh,
# scripts/reset_broker_data.py) so an operator never has to remember long paths
# or service names. It only ever starts, stops, updates or cleans up the running
# app - it never edits source code.
#
# Usage:
#   fastalgo status          Show service state, address and version
#   fastalgo start           Start the server
#   fastalgo stop            Stop the server (the machine stays up)
#   fastalgo restart         Restart the server
#   fastalgo logs [N]        Follow live logs, or show the last N lines and exit
#   fastalgo errors [N]      Show the last N application errors (default 50)
#   fastalgo update          Pull the latest version from the repo and restart
#   fastalgo reset-broker    Clear the broker session and history, keep login and work
#   fastalgo change-broker   Switch this install to a different broker
#   fastalgo url             Print the site address
#   fastalgo version         Print the installed version
#   fastalgo help            Show this help

set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; BLUE='\033[0;34m'; YELLOW='\033[1;33m'; NC='\033[0m'
say()  { echo -e "${BLUE}$1${NC}"; }
ok()   { echo -e "${GREEN}$1${NC}"; }
warn() { echo -e "${YELLOW}$1${NC}"; }
die()  { echo -e "${RED}$1${NC}" >&2; exit 1; }

# --- discover the deployment (same rules as the other ops scripts) ---------------
OPENALGO_PATH=""; OPENALGO_SERVICE="openalgo"; OPENALGO_RUN_USER=""; OPENALGO_DOMAIN=""
if [ -f /etc/openalgo/deploy.env ]; then
    # shellcheck disable=SC1091
    . /etc/openalgo/deploy.env
fi
OPENALGO_PATH="${OPENALGO_PATH:-/var/python/openalgo}"
SERVICE="${OPENALGO_SERVICE:-openalgo}"
RUN_USER="${OPENALGO_RUN_USER:-$(stat -c '%U' "$OPENALGO_PATH" 2>/dev/null || echo root)}"
VENV_PATH="$OPENALGO_PATH/.venv"
INSTALL_DIR="$OPENALGO_PATH/install"

need_install() {
    [ -d "$OPENALGO_PATH" ] || die "No FastAlgo install found at $OPENALGO_PATH. Is this the server box?"
}

site_url() {
    if [ -n "${OPENALGO_DOMAIN:-}" ]; then
        echo "https://$OPENALGO_DOMAIN"
    else
        echo "http://127.0.0.1:5000"
    fi
}

installed_version() {
    local vf="$OPENALGO_PATH/utils/version.py"
    [ -f "$vf" ] && grep -oE 'VERSION = "[^"]+"' "$vf" | head -1 | cut -d'"' -f2 || echo "unknown"
}

cmd_status() {
    need_install
    local state; state="$(sudo systemctl is-active "$SERVICE" 2>/dev/null || true)"
    echo
    say   "FastAlgo $(installed_version)"
    case "$state" in
        active)  ok   "Service:  running ($SERVICE)";;
        failed)  echo -e "${RED}Service:  failed ($SERVICE) - run: fastalgo logs${NC}";;
        *)       warn "Service:  $state ($SERVICE)";;
    esac
    echo -e "${BLUE}Address:  $(site_url)${NC}"
    local code
    code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "$(site_url)/" 2>/dev/null || echo "---")"
    if [ "$code" = "200" ] || [ "$code" = "302" ]; then
        ok   "Website:  reachable (HTTP $code)"
    else
        warn "Website:  not answering yet (HTTP $code)"
    fi
    echo
}

cmd_start()   { need_install; say "Starting FastAlgo..."; sudo systemctl start "$SERVICE"; ok "Started."; }
cmd_stop()    { need_install; say "Stopping FastAlgo..."; sudo systemctl stop "$SERVICE"; ok "Stopped. The machine is still running; use 'fastalgo start' to run it again."; }
cmd_restart() { need_install; say "Restarting FastAlgo..."; sudo systemctl restart "$SERVICE"; ok "Restarted."; }

cmd_logs() {
    need_install
    if [ $# -gt 0 ]; then
        sudo journalctl -u "$SERVICE" -n "$1" --no-pager
    else
        say "Live logs - press Ctrl-C to stop."
        sudo journalctl -u "$SERVICE" -f
    fi
}

cmd_errors() {
    need_install
    local n="${1:-50}" ef="$OPENALGO_PATH/log/errors.jsonl"
    [ -f "$ef" ] || { ok "No errors logged."; return 0; }
    sudo tail -n "$n" "$ef"
}

cmd_update() {
    need_install
    [ -f "$INSTALL_DIR/update.sh" ] || die "update.sh not found at $INSTALL_DIR."
    say "Updating FastAlgo to the latest version from the repository..."
    sudo bash "$INSTALL_DIR/update.sh"
}

cmd_change_broker() {
    need_install
    [ -f "$INSTALL_DIR/change-broker.sh" ] || die "change-broker.sh not found at $INSTALL_DIR."
    sudo bash "$INSTALL_DIR/change-broker.sh"
}

cmd_reset_broker() {
    need_install
    [ -x "$VENV_PATH/bin/python" ] || die "No virtualenv at $VENV_PATH."
    [ -f "$OPENALGO_PATH/scripts/reset_broker_data.py" ] || die "reset_broker_data.py not found."
    local flag="--yes"
    if [ "${1:-}" = "--dry-run" ]; then
        flag="--dry-run"
        warn "Dry run - showing what would be cleared, changing nothing."
    else
        warn "This clears the broker session, symbol master and trading history."
        warn "Your login, strategies, workflows and settings are kept."
        read -r -p "Proceed? [y/N] " reply
        [[ "$reply" =~ ^[Yy]$ ]] || { echo "Cancelled."; return 0; }
    fi
    sudo -u "$RUN_USER" bash -c \
        "source '$VENV_PATH/bin/activate' && cd '$OPENALGO_PATH' && python scripts/reset_broker_data.py $flag"
    if [ "$flag" = "--yes" ]; then
        say "Restarting so the clean session takes effect..."
        sudo systemctl restart "$SERVICE"
        ok "Done. Log in again at $(site_url)"
    fi
}

cmd_help() { sed -n '3,30p' "$0" | sed 's/^# \{0,1\}//'; }

case "${1:-help}" in
    status)                 cmd_status ;;
    start)                  cmd_start ;;
    stop)                   cmd_stop ;;
    restart)                cmd_restart ;;
    logs)                   shift; cmd_logs "$@" ;;
    errors)                 shift; cmd_errors "$@" ;;
    update)                 cmd_update ;;
    reset-broker)           shift; cmd_reset_broker "${1:-}" ;;
    change-broker)          cmd_change_broker ;;
    url)                    site_url ;;
    version)                installed_version ;;
    help|-h|--help)         cmd_help ;;
    *)                      die "Unknown command: $1 (try 'fastalgo help')" ;;
esac
