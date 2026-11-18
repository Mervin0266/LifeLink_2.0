# LifeLink 2.0 — Raspberry Pi Zero W USB Gadget Ethernet Configuration

**Document:** `docs/pi-zero-usb-gadget.md`  
**Author:** Lead Embedded Systems Engineer, LifeLink 2.0  
**Target Hardware:** Raspberry Pi Zero W / Zero 2 W linked to Raspberry Pi 5 Host  
**Status:** Validated Configuration Runbook  

---

## 1. Overview and Rationale

LifeLink 2.0 strictly eliminates wireless networking for peripheral links. Instead of connecting the Pi Zero W camera module over Wi-Fi, the Pi Zero W connects to the Pi 5 via a single USB data cable configured as a **USB Ethernet Gadget** (`dwc2` + `g_ether`).

### Key Advantages:
1. **Deterministic Latency & High Bandwidth:** Dedicated 480 Mbps USB 2.0 OTG link without wireless congestion or interference.
2. **Single-Cable Power and Data:** The Pi Zero W is powered directly from the Pi 5 USB 3.0 bus port (supplying up to 1.5A) while transmitting camera streams.
3. **Complete RF Silence:** Wi-Fi and Bluetooth chips on both boards can be disabled (`dtoverlay=disable-wifi`, `dtoverlay=disable-bt`), eliminating clinical RF emission concerns and network attack surfaces.

---

## 2. Pi Zero W Configuration (Client Device)

Mount the Pi Zero W MicroSD card on your setup workstation or configure directly via terminal.

### Step 2.1: Enable the DWC2 USB Controller Overlay
Edit `/boot/firmware/config.txt` (or `/boot/config.txt` on older Raspberry Pi OS versions):

```ini
# LifeLink 2.0: Enable USB OTG Controller
dtoverlay=dwc2

# LifeLink 2.0: Disable unused wireless radios for security and power saving
dtoverlay=disable-wifi
dtoverlay=disable-bt

# Enable Camera Subsystem
camera_auto_detect=1
```

### Step 2.2: Load Kernel Gadget Modules at Boot
Edit `/boot/firmware/cmdline.txt`. Append `modules-load=dwc2,g_ether` immediately after `rootwait`:

```text
console=serial0,115200 console=tty1 root=PARTUUID=... rootfstype=ext4 fsck.repair=yes rootwait modules-load=dwc2,g_ether quiet
```

> [!CAUTION]
> `cmdline.txt` MUST remain a single contiguous line. Do not introduce line breaks or multiple lines.

### Step 2.3: Configure Static Link-Local IP Address on Pi Zero W
Create or edit `/etc/network/interfaces.d/usb0` (or `/etc/systemd/network/10-usb0.network` if using systemd-networkd):

```ini
# /etc/network/interfaces.d/usb0
allow-hotplug usb0
iface usb0 inet static
    address 192.168.55.2
    netmask 255.255.255.0
```

Alternatively, with `systemd-networkd`:
```ini
# /etc/systemd/network/10-usb0.network
[Match]
Name=usb0

[Network]
Address=192.168.55.2/24
```

---

## 3. Raspberry Pi 5 Configuration (Host Terminal)

When the Pi Zero W is plugged into the Pi 5 USB Type-A port, the Linux kernel detects a new USB Ethernet device (typically named `usb0` or `eth1` depending on predictable network interface names).

### Step 3.1: Configure Static Host IP Address
Create `/etc/systemd/network/10-kiosk-usb0.network` on the Pi 5:

```ini
[Match]
Driver=cdc_ether* rndis_host*
Name=usb* eth*

[Network]
Address=192.168.55.1/24
```

Restart systemd-networkd:
```bash
sudo systemctl restart systemd-networkd
```

### Step 3.2: Verify Wired Link Connectivity
Verify link state and latency from the Pi 5 terminal:

```bash
# Ping the Pi Zero W camera daemon
ping -c 4 192.168.55.2
```
Expected output:
```text
64 bytes from 192.168.55.2: icmp_seq=1 ttl=64 time=0.482 ms
64 bytes from 192.168.55.2: icmp_seq=2 ttl=64 time=0.415 ms
```

---

## 4. Deploying the Camera Daemon Service on Pi Zero W

Copy `iris-module/camera-client/` to the Pi Zero W directory `/opt/lifelink-camera/`.

### Step 4.1: Install Python Dependencies
```bash
sudo apt update
sudo apt install -y python3-picamera2 python3-opencv python3-flask python3-numpy python3-gpiozero rpi-lgpio
```

### Step 4.2: Enable Systemd Auto-Start
Copy `deploy/systemd/lifelink-camera.service` to `/etc/systemd/system/`:

```bash
sudo cp deploy/systemd/lifelink-camera.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now lifelink-camera.service
sudo systemctl status lifelink-camera.service
```

### Step 4.3: Health Check & IR LED Status from Pi 5
Query the camera service health endpoint:
```bash
curl -s http://192.168.55.2:5001/api/v1/camera/health | jq .
```
Expected response:
```json
{
  "camera_state": "IDLE",
  "device": "PiZeroW-CameraModule3-NoIR",
  "ir_led": {
    "active_high": true,
    "active_seconds": 0.0,
    "driver": "gpiozero",
    "enabled": true,
    "is_on": false,
    "max_on_time": 15.0,
    "pin": 18,
    "settle_time": 0.3
  },
  "service": "LifeLink-Camera-Daemon-v2",
  "status": "ready",
  "transport": "USB-Gadget-Ethernet"
}
```

Verify IR LED status directly:
```bash
curl -s http://192.168.55.2:5001/api/v1/camera/led/status | jq .
```

---

## 5. Physical Hardware Verification & Test Runbook

Follow this empirical test procedure on the physical Raspberry Pi Zero W:

### Step 5.1: Digital Multimeter / Oscilloscope Probe
1. Connect multimeter black probe to GND (Pin 6 or Pin 14).
2. Connect red probe to GPIO18 (Physical Pin 12).
3. **Verify Idle Voltage:** Must read **0.00 V** (LOW).
4. Initiate iris capture from Pi 5:
   ```bash
   curl -X POST http://192.168.55.2:5001/api/v1/camera/iris/capture -H "Content-Type: application/json" -d '{"eye_side": "OD"}'
   ```
5. **Verify Active Voltage:** Must rise to **3.30 V ± 0.15 V** (HIGH) during capture settling and multi-frame acquisition.
6. **Verify Return to Idle:** Must immediately drop back to **0.00 V** upon scan completion.

### Step 5.2: Optical IR LED Verification
- Since 850 nm is largely invisible to human eyes, view the IR LED module through a smartphone camera or IR sensor card during capture.
- The LED will appear as a bright purplish-white or faint red glow strictly while active.
- Verify that ordinary patient portrait capture (`/api/v1/camera/photo/capture`) leaves the IR LED completely **DARK / OFF**.

### Step 5.3: Emergency Cancellation & Watchdog Safety Test
1. Call `/api/v1/camera/cancel`:
   ```bash
   curl -X POST http://192.168.55.2:5001/api/v1/camera/cancel
   ```
2. Verify GPIO18 drops to 0.00 V and status reports `"is_on": false`.
3. Stop the service (`sudo systemctl stop lifelink-camera`) and verify GPIO18 remains 0.00 V without floating high.
