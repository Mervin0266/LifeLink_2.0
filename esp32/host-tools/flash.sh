#!/usr/bin/env bash
# ==============================================================================
# LifeLink 2.0 - ESP32 MicroPython Firmware Flashing & Verification Tool
# Uploads boot.py, framing.py, fplibMicro.py, and main.py to ESP32 via mpremote.
# Runs diagnostic handshake against GT-521F32 UART driver over USB serial.
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FIRMWARE_DIR="$(cd "$SCRIPT_DIR/../firmware" && pwd)"

echo "================================================================="
echo " LifeLink 2.0: ESP32 Fingerprint Firmware Deployment Tool"
echo "================================================================="

# 1. Check Python and dependencies
if ! command -v python3 &>/dev/null && ! command -v python &>/dev/null; then
    echo "[-] Error: Python is required on host to run mpremote and esptool."
    exit 1
fi
PYTHON_BIN="$(command -v python3 || command -v python)"

if ! "$PYTHON_BIN" -c "import mpremote" &>/dev/null; then
    echo "[*] Installing required host tools: mpremote, pyserial, esptool..."
    "$PYTHON_BIN" -m pip install -q -r "$SCRIPT_DIR/../requirements.txt"
fi

# 2. Identify Serial Port
PORT="${1:-}"
if [ -z "$PORT" ]; then
    echo "[*] Auto-detecting ESP32 serial port..."
    # Check Linux /dev/serial/by-id or ttyUSB*/ttyACM*
    for candidate in /dev/serial/by-id/*CP210* /dev/serial/by-id/*CH340* /dev/serial/by-id/*FTDI* /dev/ttyUSB0 /dev/ttyACM0; do
        if [ -e "$candidate" ]; then
            PORT="$candidate"
            break
        fi
    done
fi

if [ -z "$PORT" ] || [ ! -e "$PORT" ]; then
    echo "[-] Could not auto-detect ESP32 serial port."
    echo "    Usage: $0 [SERIAL_PORT] [--erase]"
    echo "    Example: $0 /dev/ttyUSB0"
    exit 1
fi

echo "[+] Target Serial Port: $PORT"

# Optional erase flag check
if [[ "${2:-}" == "--erase" ]] || [[ "${1:-}" == "--erase" ]]; then
    echo "[!] WARNING: Full flash erase requested. Erasing ESP32 flash..."
    "$PYTHON_BIN" -m esptool --port "$PORT" erase_flash
    echo "[+] Erase complete. Please reflash MicroPython v1.20+ firmware before uploading scripts."
    exit 0
fi

# 3. Verify files to upload
echo "[*] Checking firmware files in $FIRMWARE_DIR..."
REQUIRED_FILES=("boot.py" "framing.py" "fplibMicro.py" "main.py")
for f in "${REQUIRED_FILES[@]}"; do
    if [ ! -f "$FIRMWARE_DIR/$f" ]; then
        echo "[-] Missing critical firmware file: $FIRMWARE_DIR/$f"
        exit 1
    fi
    echo "  [OK] $f"
done

# 4. Upload files via mpremote
echo "[*] Connecting to ESP32 on $PORT via mpremote..."
"$PYTHON_BIN" -m mpremote connect "$PORT" fs ls || {
    echo "[-] Failed to contact MicroPython REPL. Is MicroPython installed on the ESP32?"
    exit 1
}

echo "[*] Uploading LifeLink 2.0 firmware files..."
for f in "${REQUIRED_FILES[@]}"; do
    echo "  -> Copying $f to ESP32 root filesystem..."
    "$PYTHON_BIN" -m mpremote connect "$PORT" fs cp "$FIRMWARE_DIR/$f" ":$f"
done

echo "[*] Soft-resetting ESP32 to start main.py service loop..."
"$PYTHON_BIN" -m mpremote connect "$PORT" reset

# 5. Run test handshake
echo "[*] Waiting 2 seconds for firmware initialization..."
sleep 2

echo "[*] Executing test_handshake.py..."
"$PYTHON_BIN" "$SCRIPT_DIR/test_handshake.py" --port "$PORT"

echo "================================================================="
echo " LifeLink 2.0: ESP32 Firmware successfully flashed and verified!"
echo " The device is in SAFE IDLE state (LED OFF, scan idle)."
echo "================================================================="
