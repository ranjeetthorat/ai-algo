#!/bin/bash

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# OpenAlgo Broker Change Banner
echo -e "${BLUE}"
echo "  ██████╗ ██████╗ ███████╗███╗   ██╗ █████╗ ██╗      ██████╗  ██████╗ "
echo " ██╔═══██╗██╔══██╗██╔════╝████╗  ██║██╔══██╗██║     ██╔════╝ ██╔═══██╗"
echo " ██║   ██║██████╔╝███████╗██╔██╗ ██║███████║██║     ██║  ███╗██║   ██║"
echo " ██║   ██║██╔═══╝ ██╔══╝  ██║╚██╗██║██╔══██║██║     ██║   ██║██║   ██║"
echo " ╚██████╔╝██╗     ███████╗██║ ╚████║██║  ██║███████╗╚██████╔╝╚██████╔╝"
echo "  ╚═════╝ ╚═╝     ╚══════╝╚═╝  ╚═══╝╚═╝  ╚═╝╚══════╝ ╚═════╝  ╚═════╝ "
echo "                      BROKER  CHANGE  SCRIPT                             "
echo -e "${NC}"

# OpenAlgo Broker Change Script
# Switches an existing server deployment to a different broker, keeping the
# client's login and their own work (strategies, workflows, settings). It
# updates .env, clears the old broker's session, symbol master and trading
# history, and restarts the service. It does NOT touch the domain, Nginx or the
# SSL certificate - the deployment stays at the same address.

# Create logs directory if it doesn't exist
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
LOGS_DIR="$SCRIPT_DIR/logs"
mkdir -p "$LOGS_DIR"

# Generate unique log file name
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
LOG_FILE="$LOGS_DIR/change_broker_${TIMESTAMP}.log"

# Function to log messages to both console and log file
log_message() {
    local message="$1"
    local color="$2"
    echo -e "${color}${message}${NC}" | tee -a "$LOG_FILE"
}

# Function to check if command was successful
check_status() {
    if [ $? -ne 0 ]; then
        log_message "Error: $1" "$RED"
        exit 1
    fi
}

# Function to validate broker name (kept in step with install.sh)
validate_broker() {
    local broker=$1
    local valid_brokers="fivepaisa,fivepaisaxts,aliceblue,angel,arrow,compositedge,definedge,deltaexchange,dhan,dhan_sandbox,firstock,flattrade,fyers,groww,hdfcsecurities,hdfcsky,ibulls,iifl,iiflcapital,indmoney,jainamxts,kotak,motilal,mstock,nubra,paytm,pocketful,rmoney,samco,shoonya,tradejini,tradesmart,upstox,wisdom,zebu,zerodha"
    if [[ ",$valid_brokers," == *",$broker,"* ]]; then
        return 0
    else
        return 1
    fi
}

# Function to check if broker is XTS based (needs extra market-data credentials)
is_xts_broker() {
    local broker=$1
    local xts_brokers="fivepaisaxts,compositedge,ibulls,iifl,jainamxts,rmoney,wisdom"
    if [[ ",$xts_brokers," == *",$broker,"* ]]; then
        return 0
    else
        return 1
    fi
}

# Set one KEY = 'value' line in an env file (replace in place, or append if absent).
# & | and backslash in the value are escaped for the sed replacement.
set_env_var() {
    local key="$1" val="$2" file="$3"
    local esc
    esc=$(printf '%s' "$val" | sed -e 's/[\\&|]/\\&/g')
    if sudo grep -qE "^${key}[[:space:]]*=" "$file"; then
        sudo sed -i -E "s|^${key}[[:space:]]*=.*|${key} = '${esc}'|" "$file"
    else
        echo "${key} = '${val}'" | sudo tee -a "$file" >/dev/null
    fi
}

# Start logging
log_message "Starting OpenAlgo broker change log at: $LOG_FILE" "$BLUE"
log_message "----------------------------------------" "$BLUE"

# ============================================
# Step 1: Detect OS -> web user and Python
# ============================================
OS_TYPE=$(grep -w "ID" /etc/os-release | cut -d "=" -f 2 | tr -d '"')
case "$OS_TYPE" in
    "pop"|"linuxmint"|"zorin") OS_TYPE="ubuntu" ;;
    "manjaro"|"manjaro-arm"|"endeavouros"|"cachyos") OS_TYPE="arch" ;;
    "rocky"|"almalinux"|"ol") OS_TYPE="rhel" ;;
esac
case "$OS_TYPE" in
    ubuntu|debian|raspbian) WEB_USER="www-data"; WEB_GROUP="www-data" ;;
    centos|fedora|rhel|amzn) WEB_USER="nginx"; WEB_GROUP="nginx" ;;
    arch) WEB_USER="http"; WEB_GROUP="http" ;;
    *) log_message "Warning: Unrecognized OS ($OS_TYPE). Defaulting to www-data." "$YELLOW"
       WEB_USER="www-data"; WEB_GROUP="www-data" ;;
esac
log_message "Detected OS: $OS_TYPE (web user: $WEB_USER)" "$GREEN"

# ============================================
# Step 2: Discover existing deployment
# ============================================
# Try the simple single-install layout (current install.sh) first, then fall
# back to the legacy /var/python/openalgo-flask/<deploy>/ tree.
SIMPLE_PATH="/var/python/openalgo"
DEPLOY_BASE="/var/python/openalgo-flask"

if [ -d "$SIMPLE_PATH/.git" ] && [ -f "$SIMPLE_PATH/.env" ]; then
    SELECTED_DEPLOY="openalgo"
    OPENALGO_PATH="$SIMPLE_PATH"
    VENV_PATH="$SIMPLE_PATH/.venv"
    SERVICE_NAME="openalgo"
    ENV_FILE="$OPENALGO_PATH/.env"
    log_message "Found OpenAlgo install at $SIMPLE_PATH" "$GREEN"
else
    if [ ! -d "$DEPLOY_BASE" ]; then
        log_message "Error: No OpenAlgo deployment found." "$RED"
        log_message "Looked at $SIMPLE_PATH and $DEPLOY_BASE" "$YELLOW"
        log_message "This script is for server deployments installed via install.sh" "$YELLOW"
        exit 1
    fi
    DEPLOYMENTS=()
    for dir in "$DEPLOY_BASE"/*/; do
        if [ -d "${dir}openalgo" ] && [ -f "${dir}openalgo/.env" ]; then
            DEPLOYMENTS+=("$(basename "$dir")")
        fi
    done
    if [ ${#DEPLOYMENTS[@]} -eq 0 ]; then
        log_message "Error: No OpenAlgo deployments found in $SIMPLE_PATH or $DEPLOY_BASE" "$RED"
        exit 1
    fi
    log_message "Found ${#DEPLOYMENTS[@]} legacy deployment(s):" "$GREEN"
    for i in "${!DEPLOYMENTS[@]}"; do
        log_message "  $((i+1)). ${DEPLOYMENTS[$i]}" "$BLUE"
    done
    if [ ${#DEPLOYMENTS[@]} -eq 1 ]; then
        SELECTED_DEPLOY="${DEPLOYMENTS[0]}"
        log_message "\nAuto-selected: $SELECTED_DEPLOY" "$GREEN"
    else
        echo ""
        while true; do
            read -p "Select deployment to change broker for (1-${#DEPLOYMENTS[@]}): " choice
            if [[ "$choice" =~ ^[0-9]+$ ]] && [ "$choice" -ge 1 ] && [ "$choice" -le ${#DEPLOYMENTS[@]} ]; then
                SELECTED_DEPLOY="${DEPLOYMENTS[$((choice-1))]}"
                break
            else
                log_message "Invalid choice." "$RED"
            fi
        done
    fi
    OPENALGO_PATH="$DEPLOY_BASE/$SELECTED_DEPLOY/openalgo"
    VENV_PATH="$DEPLOY_BASE/$SELECTED_DEPLOY/venv"
    SERVICE_NAME="openalgo-$SELECTED_DEPLOY"
    ENV_FILE="$OPENALGO_PATH/.env"
fi

if [ ! -x "$VENV_PATH/bin/python" ]; then
    log_message "Error: No virtualenv found at $VENV_PATH" "$RED"
    log_message "Expected the deployment's .venv created by install.sh" "$YELLOW"
    exit 1
fi

# ============================================
# Step 3: Read current broker and address from .env
# ============================================
CURRENT_REDIRECT=$(sudo grep -oP "REDIRECT_URL\s*=\s*'\K[^']+" "$ENV_FILE" 2>/dev/null)
CURRENT_HOST=$(echo "$CURRENT_REDIRECT" | grep -oP 'https?://[^/]+')
CURRENT_BROKER=$(echo "$CURRENT_REDIRECT" | grep -oP 'https?://[^/]+/\K[^/]+')
CURRENT_VALID=$(sudo grep -oP "VALID_BROKERS\s*=\s*'\K[^']+" "$ENV_FILE" 2>/dev/null)

if [ -z "$CURRENT_HOST" ]; then
    # Fall back to HOST_SERVER if REDIRECT_URL is unreadable.
    CURRENT_HOST=$(sudo grep -oP "HOST_SERVER\s*=\s*'\K[^']+" "$ENV_FILE" 2>/dev/null)
fi
if [ -z "$CURRENT_HOST" ]; then
    log_message "Error: Could not read the deployment address from $ENV_FILE" "$RED"
    log_message "Expected REDIRECT_URL or HOST_SERVER to hold https://yourdomain/..." "$YELLOW"
    exit 1
fi

log_message "\nCurrent broker:  ${CURRENT_BROKER:-unknown}" "$BLUE"
log_message "Address:         $CURRENT_HOST" "$BLUE"

# ============================================
# Step 4: Collect the new broker and credentials
# ============================================
echo ""
while true; do
    log_message "Valid brokers: fivepaisa,fivepaisaxts,aliceblue,angel,arrow,compositedge,definedge,deltaexchange,dhan,dhan_sandbox,firstock,flattrade,fyers,groww,hdfcsecurities,hdfcsky,ibulls,iifl,iiflcapital,indmoney,jainamxts,kotak,motilal,mstock,nubra,paytm,pocketful,rmoney,samco,shoonya,tradejini,tradesmart,upstox,wisdom,zebu,zerodha" "$BLUE"
    read -p "Enter the NEW broker name: " BROKER_NAME
    BROKER_NAME=$(echo "$BROKER_NAME" | tr '[:upper:]' '[:lower:]' | xargs)
    if ! validate_broker "$BROKER_NAME"; then
        log_message "Invalid broker name. Please choose from the list above." "$RED"
        continue
    fi
    if [ "$BROKER_NAME" = "$CURRENT_BROKER" ]; then
        log_message "That is already the current broker. Choose a different one, or press Ctrl+C to cancel." "$YELLOW"
        continue
    fi
    break
done

NEW_REDIRECT="$CURRENT_HOST/$BROKER_NAME/callback"
log_message "\nRedirect URL for the broker developer portal:" "$YELLOW"
log_message "  $NEW_REDIRECT" "$GREEN"
log_message "Register this in the new broker's portal to generate API credentials." "$BLUE"
echo ""

read -p "Enter the new broker API key: " BROKER_API_KEY
read -p "Enter the new broker API secret: " BROKER_API_SECRET
if [ -z "$BROKER_API_KEY" ] || [ -z "$BROKER_API_SECRET" ]; then
    log_message "Error: Broker API credentials are required" "$RED"
    exit 1
fi

BROKER_API_KEY_MARKET=""
BROKER_API_SECRET_MARKET=""
if is_xts_broker "$BROKER_NAME"; then
    log_message "\n$BROKER_NAME is XTS API-based and needs separate market-data credentials." "$YELLOW"
    read -p "Enter the market data API key: " BROKER_API_KEY_MARKET
    read -p "Enter the market data API secret: " BROKER_API_SECRET_MARKET
    if [ -z "$BROKER_API_KEY_MARKET" ] || [ -z "$BROKER_API_SECRET_MARKET" ]; then
        log_message "Error: Market data credentials are required for this broker" "$RED"
        exit 1
    fi
fi

# ============================================
# Step 5: Show the plan, preview the data reset, and confirm
# ============================================
log_message "\n========================================" "$YELLOW"
log_message "  Planned Changes" "$YELLOW"
log_message "========================================" "$YELLOW"
log_message "Broker:        ${CURRENT_BROKER:-unknown}  -->  $BROKER_NAME" "$GREEN"
log_message "REDIRECT_URL:  $NEW_REDIRECT" "$BLUE"
log_message "VALID_BROKERS: ${CURRENT_VALID:-unknown}  -->  $BROKER_NAME (locked to one broker)" "$BLUE"
log_message "" ""
log_message "Kept:    login, API key, settings, strategies, workflows, watchlists, alerts." "$GREEN"
log_message "Cleared: broker session, symbol master, and trading history." "$YELLOW"
log_message "" ""

# Preview the row counts the reset would clear (read-only; safe while running).
log_message "Preview of data to be cleared:" "$BLUE"
sudo -u "$WEB_USER" bash -c "source $VENV_PATH/bin/activate && cd $OPENALGO_PATH && python scripts/reset_broker_data.py --dry-run" 2>&1 | tee -a "$LOG_FILE" || \
    log_message "  (could not preview; the reset will still run after you confirm)" "$YELLOW"

log_message "\nThe domain, Nginx and SSL certificate are NOT changed." "$BLUE"
log_message "========================================" "$YELLOW"
echo ""
read -p "Proceed with the broker change? (y/n): " confirm
if [[ ! $confirm =~ ^[Yy]$ ]]; then
    log_message "Broker change cancelled by user." "$YELLOW"
    exit 0
fi

# ============================================
# Step 6/1: Stop the service
# ============================================
log_message "\n[Step 1/5] Stopping service: $SERVICE_NAME..." "$BLUE"
if sudo systemctl is-active --quiet "$SERVICE_NAME" 2>/dev/null; then
    sudo systemctl stop "$SERVICE_NAME"
    check_status "Failed to stop $SERVICE_NAME"
    log_message "Service stopped successfully" "$GREEN"
else
    log_message "Service is not currently running" "$YELLOW"
fi

# ============================================
# Step 2/5: Back up .env and databases
# ============================================
log_message "\n[Step 2/5] Backing up .env and databases..." "$BLUE"
BACKUP_DIR="$OPENALGO_PATH/db/broker_change_backup_${TIMESTAMP}"
sudo mkdir -p "$BACKUP_DIR"
sudo cp "$ENV_FILE" "$BACKUP_DIR/.env.backup"
check_status "Failed to back up .env"
log_message "  Backed up: .env" "$GREEN"
if [ -d "$OPENALGO_PATH/db" ]; then
    for db_file in openalgo.db logs.db latency.db sandbox.db historify.duckdb; do
        if [ -f "$OPENALGO_PATH/db/$db_file" ]; then
            sudo cp "$OPENALGO_PATH/db/$db_file" "$BACKUP_DIR/$db_file"
            log_message "  Backed up: $db_file" "$GREEN"
        fi
    done
fi
log_message "Backup location: $BACKUP_DIR" "$GREEN"

# ============================================
# Step 3/5: Update .env with the new broker
# ============================================
log_message "\n[Step 3/5] Updating .env..." "$BLUE"
set_env_var "BROKER_API_KEY" "$BROKER_API_KEY" "$ENV_FILE"
set_env_var "BROKER_API_SECRET" "$BROKER_API_SECRET" "$ENV_FILE"
set_env_var "REDIRECT_URL" "$NEW_REDIRECT" "$ENV_FILE"
set_env_var "VALID_BROKERS" "$BROKER_NAME" "$ENV_FILE"
if is_xts_broker "$BROKER_NAME"; then
    set_env_var "BROKER_API_KEY_MARKET" "$BROKER_API_KEY_MARKET" "$ENV_FILE"
    set_env_var "BROKER_API_SECRET_MARKET" "$BROKER_API_SECRET_MARKET" "$ENV_FILE"
fi
sudo chmod 600 "$ENV_FILE"
sudo chown "$WEB_USER:$WEB_GROUP" "$ENV_FILE"
VERIFY_REDIRECT=$(sudo grep -oP "REDIRECT_URL\s*=\s*'\K[^']+" "$ENV_FILE")
VERIFY_VALID=$(sudo grep -oP "VALID_BROKERS\s*=\s*'\K[^']+" "$ENV_FILE")
log_message "  REDIRECT_URL:  $VERIFY_REDIRECT" "$GREEN"
log_message "  VALID_BROKERS: $VERIFY_VALID" "$GREEN"
log_message ".env updated successfully" "$GREEN"

# ============================================
# Step 4/5: Clear broker session, symbol master and trading history
# ============================================
log_message "\n[Step 4/5] Clearing broker data (keeping login and client work)..." "$BLUE"
sudo -u "$WEB_USER" bash -c "source $VENV_PATH/bin/activate && cd $OPENALGO_PATH && python scripts/reset_broker_data.py --yes" 2>&1 | tee -a "$LOG_FILE"
reset_status=${PIPESTATUS[0]}
if [ "$reset_status" -ne 0 ]; then
    log_message "Retrying with elevated permissions..." "$YELLOW"
    sudo bash -c "source $VENV_PATH/bin/activate && cd $OPENALGO_PATH && python scripts/reset_broker_data.py --yes" 2>&1 | tee -a "$LOG_FILE"
    reset_status=${PIPESTATUS[0]}
    if [ "$reset_status" -ne 0 ]; then
        log_message "Clearing broker data failed. Restoring databases from the backup..." "$RED"
        for db_file in openalgo.db logs.db latency.db sandbox.db historify.duckdb; do
            [ -f "$BACKUP_DIR/$db_file" ] && sudo cp "$BACKUP_DIR/$db_file" "$OPENALGO_PATH/db/$db_file"
        done
        sudo cp "$BACKUP_DIR/.env.backup" "$ENV_FILE"
        sudo chown -R "$WEB_USER:$WEB_GROUP" "$OPENALGO_PATH/db"
        sudo systemctl start "$SERVICE_NAME" 2>/dev/null
        log_message "Databases and .env restored from backup. The broker was not changed." "$GREEN"
        exit 1
    fi
fi
# The web user owns the database files; keep it that way after the reset.
sudo chown -R "$WEB_USER:$WEB_GROUP" "$OPENALGO_PATH/db"
log_message "Broker data cleared" "$GREEN"

# ============================================
# Step 5/5: Start the service
# ============================================
log_message "\n[Step 5/5] Starting service..." "$BLUE"
sudo systemctl start "$SERVICE_NAME"
check_status "Failed to start $SERVICE_NAME"
sleep 3
if sudo systemctl is-active --quiet "$SERVICE_NAME"; then
    log_message "Service $SERVICE_NAME is running" "$GREEN"
else
    log_message "Warning: Service $SERVICE_NAME may not have started correctly" "$RED"
    log_message "Check logs with: sudo journalctl -u $SERVICE_NAME -n 50" "$YELLOW"
fi

# ============================================
# Summary
# ============================================
log_message "\n========================================" "$GREEN"
log_message "  Broker Change Summary" "$GREEN"
log_message "========================================" "$GREEN"
log_message "Broker:   ${CURRENT_BROKER:-unknown}  -->  $BROKER_NAME" "$GREEN"
log_message "Address:  $CURRENT_HOST (unchanged)" "$BLUE"
log_message "Backup:   $BACKUP_DIR" "$BLUE"
log_message "Log:      $LOG_FILE" "$BLUE"
log_message "" ""
log_message "========================================" "$RED"
log_message "  ACTION REQUIRED: Register the redirect URL" "$RED"
log_message "========================================" "$RED"
log_message "In $BROKER_NAME's developer portal, set the redirect URL to:" "$YELLOW"
log_message "  $NEW_REDIRECT" "$GREEN"
log_message "Without this, broker login will fail." "$RED"
log_message "" ""
log_message "The client keeps their login. They log in again and connect $BROKER_NAME." "$GREEN"
log_message "Broker change completed successfully!" "$GREEN"
