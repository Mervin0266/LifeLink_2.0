#!/usr/bin/env bash
# ==============================================================================
# LifeLink 2.0 - Raspberry Pi 5 Central Terminal Installation Script
# Target: Raspberry Pi 5 (Debian 12 Bookworm ARM64)
# Configures system packages, virtualenv, udev rules, local database,
# systemd services, and Chromium touchscreen kiosk launcher.
# ==============================================================================

set -euo pipefail

INSTALL_DIR="/opt/lifelink"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "================================================================="
echo " LifeLink 2.0: Raspberry Pi 5 Terminal Deployment"
echo "================================================================="

# 1. Require root privileges
if [ "$EUID" -ne 0 ]; then
    echo "[-] Error: Please run this installer as root (e.g. sudo bash install.sh)"
    exit 1
fi

# 2. Check architecture
echo "[1/8] Verifying hardware platform..."
ARCH="$(uname -m)"
echo "[+] Detected Architecture: $ARCH"
if [[ "$ARCH" != "aarch64" ]]; then
    echo "[!] Warning: Target is expected to be ARM64 (aarch64) Raspberry Pi 5."
    echo "    Proceeding in cross-platform installation mode."
fi

# 3. Install system dependencies via APT
echo "[2/8] Installing system dependencies via APT..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    python3-venv \
    python3-dev \
    libpq-dev \
    build-essential \
    curl \
    unclutter \
    x11-xserver-utils \
    chromium-browser \
    sqlite3

# Optional PostgreSQL package installation
if [ "${INSTALL_POSTGRES:-false}" = "true" ]; then
    echo "[*] Installing PostgreSQL server..."
    apt-get install -y postgresql postgresql-contrib
    systemctl enable postgresql
    systemctl start postgresql
fi

# 4. Deploy application files to /opt/lifelink
echo "[3/8] Deploying application tree to $INSTALL_DIR..."
mkdir -p "$INSTALL_DIR"
cp -r "$SCRIPT_DIR/backend" "$INSTALL_DIR/"
cp -r "$SCRIPT_DIR/frontend" "$INSTALL_DIR/"
cp -r "$SCRIPT_DIR/iris-engine" "$INSTALL_DIR/"
cp -r "$SCRIPT_DIR/protocol" "$INSTALL_DIR/"
cp -r "$SCRIPT_DIR/sync" "$INSTALL_DIR/"
cp -r "$SCRIPT_DIR/database" "$INSTALL_DIR/"
cp -r "$SCRIPT_DIR/kiosk" "$INSTALL_DIR/"
cp -r "$SCRIPT_DIR/weights" "$INSTALL_DIR/"
cp "$SCRIPT_DIR/requirements.txt" "$INSTALL_DIR/"

# Setup environment file if not present
mkdir -p /etc/lifelink
if [ ! -f /etc/lifelink/lifelink.env ]; then
    cp "$SCRIPT_DIR/.env.example" /etc/lifelink/lifelink.env
    echo "[+] Created /etc/lifelink/lifelink.env"
fi

# Ensure user pi exists and set permissions
if ! id "pi" &>/dev/null; then
    useradd -m -s /bin/bash pi || true
fi
usermod -a -G dialout,video,audio pi || true
chown -R pi:pi "$INSTALL_DIR"
chmod -R 755 "$INSTALL_DIR"
chmod +x "$INSTALL_DIR/kiosk/kiosk.sh"

# 5. Create Python Virtual Environment
echo "[4/8] Creating Python virtual environment in $INSTALL_DIR/venv..."
if [ ! -d "$INSTALL_DIR/venv" ]; then
    python3 -m venv "$INSTALL_DIR/venv"
fi
"$INSTALL_DIR/venv/bin/pip" install --upgrade pip setuptools wheel
echo "[*] Installing Python dependencies from requirements.txt..."
"$INSTALL_DIR/venv/bin/pip" install -r "$INSTALL_DIR/requirements.txt"

# 6. Install udev rules for ESP32 fingerprint serial host
echo "[5/8] Installing udev rules (99-lifelink.rules)..."
cp "$SCRIPT_DIR/udev/99-lifelink.rules" /etc/udev/rules.d/
udevadm control --reload-rules || true
udevadm trigger || true

# 7. Initialize Database and Seed Default Staff Accounts
echo "[6/8] Initializing local database tables and initial staff seeds..."
sudo -u pi "$INSTALL_DIR/venv/bin/python" "$INSTALL_DIR/database/init_db.py"

# 8. Configure and Enable Systemd Services
echo "[7/8] Registering systemd service units..."
cp "$SCRIPT_DIR/systemd/lifelink-backend.service" /etc/systemd/system/
cp "$SCRIPT_DIR/systemd/lifelink-kiosk.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable lifelink-backend.service
systemctl enable lifelink-kiosk.service

# 9. Verify Installation
echo "[8/8] Executing installation validation script..."
sudo -u pi "$INSTALL_DIR/venv/bin/python" "$SCRIPT_DIR/verify_installation.py"

echo "================================================================="
echo " LifeLink 2.0: Raspberry Pi 5 Terminal successfully installed!"
echo " Start backend service:  sudo systemctl start lifelink-backend"
echo " Check service health:   curl http://127.0.0.1:5000/api/v1/health"
echo " Kiosk auto-starts on:   graphical login"
echo "================================================================="
