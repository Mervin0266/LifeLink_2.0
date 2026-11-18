#!/bin/bash
# ==============================================================================
# LifeLink 2.0 - Raspberry Pi Zero W Camera & IR LED Setup Script
# Configures USB Gadget Ethernet (192.168.55.2), GPIO18 IR LED controller,
# Picamera2 system libraries, and registers systemd daemon service.
# ==============================================================================

set -e

echo "=== LifeLink 2.0: Starting Pi Zero W Camera Client Installation ==="

# Check root privileges
if [ "$EUID" -ne 0 ]; then
  echo "Error: Please run as root (sudo bash install_pizero.sh)"
  exit 1
fi

# 1. Update APT and install system dependencies
echo "[1/6] Installing APT packages..."
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
    gpiod

# 2. Configure USB Gadget Ethernet in /boot/firmware/cmdline.txt & config.txt
echo "[2/6] Verifying USB Gadget Ethernet configuration..."
BOOT_CONFIG="/boot/firmware/config.txt"
if [ ! -f "$BOOT_CONFIG" ]; then
    BOOT_CONFIG="/boot/config.txt"
fi

if ! grep -q "dtoverlay=dwc2" "$BOOT_CONFIG"; then
    echo "dtoverlay=dwc2" >> "$BOOT_CONFIG"
    echo "Added dtoverlay=dwc2 to $BOOT_CONFIG"
fi

if ! grep -q "g_ether" /etc/modules; then
    echo "g_ether" >> /etc/modules
    echo "Added g_ether to /etc/modules"
fi

# 3. Configure Static IP on usb0 interface (192.168.55.2/24)
echo "[3/6] Configuring static IP (192.168.55.2) on usb0..."
cat << 'EOF' > /etc/network/interfaces.d/usb0
allow-hotplug usb0
iface usb0 inet static
    address 192.168.55.2
    netmask 255.255.255.0
    gateway 192.168.55.1
EOF

# 4. Deploy Camera Service files to /opt/lifelink-camera
echo "[4/6] Deploying application files to /opt/lifelink-camera..."
INSTALL_DIR="/opt/lifelink-camera"
mkdir -p "$INSTALL_DIR"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cp "$SCRIPT_DIR"/*.py "$INSTALL_DIR/"
cp "$SCRIPT_DIR"/requirements.txt "$INSTALL_DIR/"

# Create pi service user if not present
if id "pi" &>/dev/null; then
    usermod -a -G video,gpio pi || true
    chown -R pi:video "$INSTALL_DIR"
fi

# 5. Install systemd service unit
echo "[5/6] Registering systemd service..."
cat << 'EOF' > /etc/systemd/system/lifelink-camera.service
[Unit]
Description=LifeLink 2.0 Wired Iris Camera & IR LED Service (Pi Zero W)
After=network.target

[Service]
Type=simple
User=pi
Group=video
WorkingDirectory=/opt/lifelink-camera
Environment=PYTHONUNBUFFERED=1
Environment=PORT=5001
Environment=HOST=192.168.55.2
Environment=IR_LED_GPIO_PIN=18
Environment=IR_LED_ACTIVE_HIGH=true
Environment=IR_LED_ENABLED=true
ExecStart=/usr/bin/python3 -m camera_service
Restart=always
RestartSec=3
StandardOutput=journal
StandardError=journal
SyslogIdentifier=lifelink-camera

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable lifelink-camera.service

# 6. Quick GPIO18 sanity check
echo "[6/6] Verifying GPIO18 status..."
if command -v pinctrl &>/dev/null; then
    pinctrl set 18 op dl || true
    echo "GPIO18 set to OUTPUT LOW (default OFF)"
elif command -v raspi-gpio &>/dev/null; then
    raspi-gpio set 18 op dl || true
    echo "GPIO18 set to OUTPUT LOW (default OFF)"
fi

echo "=== LifeLink 2.0: Camera & IR LED Service installed successfully! ==="
echo "Run 'sudo systemctl start lifelink-camera' to start daemon."
echo "Verify status: 'curl http://192.168.55.2:5001/api/v1/camera/led/status'"
