#!/usr/bin/env bash
# ==============================================================================
# LifeLink 2.0 - Raspberry Pi Zero W Camera & IR LED Setup Script
# Configures USB Gadget Ethernet (192.168.55.2/24), GPIO18 IR LED controller,
# Picamera2 / libcamera drivers, and registers the systemd daemon.
# Idempotent and preserves existing operating system configurations with backups.
# ==============================================================================

set -euo pipefail

INSTALL_DIR="/opt/lifelink-camera"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "================================================================="
echo " LifeLink 2.0: Pi Zero W Camera Client Installation"
echo " Target: Raspberry Pi Zero W (ARMv6/ARMv7, Raspberry Pi OS)"
echo "================================================================="

# 1. Verify root execution
if [ "$EUID" -ne 0 ]; then
    echo "[-] Error: Please run this installation script as root (e.g., sudo bash install.sh)"
    exit 1
fi

# 2. Check architecture & OS
echo "[1/7] Inspecting hardware and operating system..."
ARCH="$(uname -m)"
echo "[+] Detected Architecture: $ARCH"
if [[ "$ARCH" != "armv6l" ]] && [[ "$ARCH" != "armv7l" ]] && [[ "$ARCH" != "aarch64" ]]; then
    echo "[!] Warning: Host architecture ($ARCH) is not a Raspberry Pi ARM architecture."
    echo "    Continuing installation in simulation/test mode."
fi

# 3. Install required system packages
echo "[2/7] Installing system packages via apt..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    python3-venv \
    python3-gpiozero \
    python3-picamera2 \
    python3-opencv \
    python3-numpy \
    python3-flask \
    libcamera-apps \
    gpiod \
    curl

# 4. Safely configure USB Gadget Ethernet (dwc2 & g_ether)
echo "[3/7] Configuring USB Gadget Ethernet (dwc2 / g_ether)..."

# Locate config.txt (Debian Bookworm uses /boot/firmware/config.txt; Bullseye uses /boot/config.txt)
BOOT_CONFIG="/boot/firmware/config.txt"
if [ ! -f "$BOOT_CONFIG" ]; then
    BOOT_CONFIG="/boot/config.txt"
fi

if [ -f "$BOOT_CONFIG" ]; then
    if ! grep -q "dtoverlay=dwc2" "$BOOT_CONFIG"; then
        echo "[+] Backing up $BOOT_CONFIG to ${BOOT_CONFIG}.bak..."
        cp "$BOOT_CONFIG" "${BOOT_CONFIG}.bak"
        echo "dtoverlay=dwc2" >> "$BOOT_CONFIG"
        echo "[+] Added dtoverlay=dwc2 to $BOOT_CONFIG"
    else
        echo "[+] dtoverlay=dwc2 already present in $BOOT_CONFIG"
    fi
else
    echo "[!] Warning: No boot config.txt found. Skipping kernel overlay edit."
fi

# Add g_ether to /etc/modules idempotently
MODULES_FILE="/etc/modules"
if [ -f "$MODULES_FILE" ]; then
    if ! grep -q "^g_ether" "$MODULES_FILE"; then
        cp "$MODULES_FILE" "${MODULES_FILE}.bak"
        echo "g_ether" >> "$MODULES_FILE"
        echo "[+] Added g_ether to $MODULES_FILE"
    else
        echo "[+] g_ether already present in $MODULES_FILE"
    fi
fi

# Configure static IP 192.168.55.2 on usb0 interface
echo "[4/7] Configuring usb0 static IP (192.168.55.2/24)..."
INTERFACES_D="/etc/network/interfaces.d"
mkdir -p "$INTERFACES_D"
cat << 'EOF' > "$INTERFACES_D/usb0"
# LifeLink 2.0 Wired USB Gadget Ethernet Link
allow-hotplug usb0
iface usb0 inet static
    address 192.168.55.2
    netmask 255.255.255.0
    gateway 192.168.55.1
EOF

# 5. Deploy application files to /opt/lifelink-camera
echo "[5/7] Deploying camera application to $INSTALL_DIR..."
mkdir -p "$INSTALL_DIR"

# Copy python source files and requirements
cp "$SCRIPT_DIR"/*.py "$INSTALL_DIR/"
cp "$SCRIPT_DIR/requirements.txt" "$INSTALL_DIR/"

# Create user pi if it does not exist (for non-standard Debian builds)
if ! id "pi" &>/dev/null; then
    useradd -m -s /bin/bash pi || true
fi

# Configure permissions for video, gpio, and i2c groups
usermod -a -G video,gpio,dialout pi || true
chown -R pi:video "$INSTALL_DIR"
chmod 755 "$INSTALL_DIR"

# 6. Install and enable systemd daemon
echo "[6/7] Installing lifelink-camera.service unit..."
cp "$SCRIPT_DIR/systemd/lifelink-camera.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable lifelink-camera.service

# 7. Safe GPIO18 state verification (guarantee LED is OFF)
echo "[7/7] Ensuring GPIO18 850nm IR LED default state is OFF..."
if command -v pinctrl &>/dev/null; then
    pinctrl set 18 op dl || true
    echo "[+] GPIO18 set to OUTPUT LOW (OFF) via pinctrl"
elif command -v raspi-gpio &>/dev/null; then
    raspi-gpio set 18 op dl || true
    echo "[+] GPIO18 set to OUTPUT LOW (OFF) via raspi-gpio"
fi

echo "================================================================="
echo " LifeLink 2.0: Camera Subsystem Installation Complete!"
echo " Service is registered: sudo systemctl start lifelink-camera"
echo " Diagnostic check:       python3 verify_camera.py"
echo " Health check:           curl http://192.168.55.2:5001/health"
echo "================================================================="
