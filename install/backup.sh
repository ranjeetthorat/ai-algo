#!/bin/bash

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# OpenAlgo Backup Script
# Backs up a deployment's databases and .env to a compressed archive, with
# retention. Non-interactive and safe to run from cron. Covers every deployment
# it finds (single install, or each legacy multi-deploy).
#
#   sudo ./backup.sh                 # back up now
#   sudo ./backup.sh --list          # list existing backups
#   sudo ./backup.sh --install-cron  # install a nightly cron job (02:30)
#   sudo ./backup.sh --install-cron 03:15
#
# Restore is manual and deliberate; see the operator runbook in docs/.

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Where backups are written, and how many to keep per deployment. Override from
# the environment (useful from cron): BACKUP_ROOT=/mnt/backups RETENTION=30
BACKUP_ROOT="${BACKUP_ROOT:-/var/backups/openalgo}"
RETENTION="${RETENTION:-14}"
CRON_FILE="/etc/cron.d/openalgo-backup"

TIMESTAMP=$(date +%Y%m%d_%H%M%S)

log_message() {
    local message="$1" color="$2"
    echo -e "${color}${message}${NC}"
}

# Discover deployments as (name|path) pairs, one per line. Simple layout first,
# then legacy /var/python/openalgo-flask/<deploy>/openalgo.
discover_deployments() {
    local simple="/var/python/openalgo"
    local base="/var/python/openalgo-flask"
    if [ -d "$simple/.git" ] && [ -f "$simple/.env" ]; then
        echo "openalgo|$simple"
        return
    fi
    if [ -d "$base" ]; then
        for dir in "$base"/*/; do
            if [ -f "${dir}openalgo/.env" ]; then
                echo "$(basename "$dir")|${dir}openalgo"
            fi
        done
    fi
}

# Back up one deployment. Args: name, path. Returns non-zero on failure.
backup_one() {
    local name="$1" path="$2"
    local dest_dir="$BACKUP_ROOT/$name"
    local archive="$dest_dir/${name}-${TIMESTAMP}.tar.gz"
    local staging
    staging=$(mktemp -d "/tmp/openalgo-backup-${name}-XXXXXX") || return 1

    log_message "Backing up $name ($path)..." "$BLUE"
    mkdir -p "$dest_dir"

    # .env
    if [ -f "$path/.env" ]; then
        cp "$path/.env" "$staging/.env"
    fi

    # SQLite databases: use the online .backup API when sqlite3 is available, so
    # a copy taken while the service runs is consistent (handles WAL). Fall back
    # to a plain file copy otherwise.
    if [ -d "$path/db" ]; then
        mkdir -p "$staging/db"
        for db in "$path"/db/*.db; do
            [ -f "$db" ] || continue
            if command -v sqlite3 >/dev/null 2>&1; then
                sqlite3 "$db" ".backup '$staging/db/$(basename "$db")'" 2>/dev/null \
                    || cp "$db" "$staging/db/$(basename "$db")"
            else
                cp "$db" "$staging/db/$(basename "$db")"
            fi
        done
        # DuckDB historical store (broker-agnostic; can be large).
        for duck in "$path"/db/*.duckdb; do
            [ -f "$duck" ] && cp "$duck" "$staging/db/$(basename "$duck")"
        done
    fi

    if ! tar -czf "$archive" -C "$staging" . 2>/dev/null; then
        log_message "  Failed to write $archive" "$RED"
        rm -rf "$staging"
        return 1
    fi
    chmod 600 "$archive"
    rm -rf "$staging"
    local size
    size=$(du -h "$archive" | cut -f1)
    log_message "  Wrote $archive ($size)" "$GREEN"

    # Prune: keep the newest RETENTION archives for this deployment.
    local old
    old=$(ls -1t "$dest_dir"/${name}-*.tar.gz 2>/dev/null | tail -n +$((RETENTION + 1)))
    if [ -n "$old" ]; then
        echo "$old" | while IFS= read -r f; do
            rm -f "$f" && log_message "  Pruned old backup $(basename "$f")" "$YELLOW"
        done
    fi
    return 0
}

do_backup() {
    local deployments
    deployments=$(discover_deployments)
    if [ -z "$deployments" ]; then
        log_message "No OpenAlgo deployment found to back up." "$RED"
        return 1
    fi
    local failures=0
    while IFS='|' read -r name path; do
        [ -n "$name" ] || continue
        backup_one "$name" "$path" || failures=$((failures + 1))
    done <<< "$deployments"
    if [ "$failures" -ne 0 ]; then
        log_message "Backup finished with $failures failure(s)." "$RED"
        return 1
    fi
    log_message "Backup complete. Location: $BACKUP_ROOT (keeping $RETENTION per deployment)." "$GREEN"
    return 0
}

do_list() {
    if [ ! -d "$BACKUP_ROOT" ]; then
        log_message "No backups yet under $BACKUP_ROOT" "$YELLOW"
        return 0
    fi
    log_message "Backups under $BACKUP_ROOT:" "$BLUE"
    for dir in "$BACKUP_ROOT"/*/; do
        [ -d "$dir" ] || continue
        log_message "  $(basename "$dir"):" "$BLUE"
        ls -1t "$dir"/*.tar.gz 2>/dev/null | while IFS= read -r f; do
            echo "    $(basename "$f")  ($(du -h "$f" | cut -f1))"
        done
    done
}

do_install_cron() {
    local at="${1:-02:30}"
    if [[ ! "$at" =~ ^([01][0-9]|2[0-3]):[0-5][0-9]$ ]]; then
        log_message "Time must be HH:MM (24-hour), for example 02:30" "$RED"
        return 1
    fi
    local hh="${at%%:*}" mm="${at##*:}"
    # Strip leading zeros so cron does not read them as octal is unnecessary for
    # cron, but keep them readable as written.
    cat > "$CRON_FILE" <<EOF
# OpenAlgo nightly backup. Installed by install/backup.sh --install-cron.
# Override destination/retention here if needed.
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
${mm} ${hh} * * * root BACKUP_ROOT=${BACKUP_ROOT} RETENTION=${RETENTION} ${SCRIPT_DIR}/backup.sh >> /var/log/openalgo-backup.log 2>&1
EOF
    chmod 644 "$CRON_FILE"
    log_message "Installed nightly backup at ${at} -> $CRON_FILE" "$GREEN"
    log_message "Logs: /var/log/openalgo-backup.log  Destination: $BACKUP_ROOT (keep $RETENTION)" "$BLUE"
}

case "${1:-}" in
    --list) do_list ;;
    --install-cron) do_install_cron "$2" ;;
    "" ) do_backup ;;
    -h|--help)
        echo "Usage: sudo ./backup.sh [--list | --install-cron [HH:MM]]"
        echo "Env:   BACKUP_ROOT (default /var/backups/openalgo), RETENTION (default 14)"
        ;;
    *)
        log_message "Unknown option: $1" "$RED"
        echo "Usage: sudo ./backup.sh [--list | --install-cron [HH:MM]]"
        exit 1
        ;;
esac
