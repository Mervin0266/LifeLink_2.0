# LifeLink 2.0 — Hardware Wiring, Electrical Specifications & Pinouts

**Document:** `docs/wiring.md`  
**Author:** Lead Hardware & Systems Engineer, LifeLink 2.0  
**Target:** Raspberry Pi 5 Touchscreen Kiosk Terminal  
**Status:** Approved Engineering Specification  

---

## 1. System Topology Overview

LifeLink 2.0 eliminates all runtime wireless dependencies (Wi-Fi, Bluetooth, BLE) in favor of **100% deterministic wired connections**. All peripherals are either USB-bus powered or directly integrated via dedicated high-speed display/camera ribbons.

```text
               +--------------------------------------------------------+
               |              Raspberry Pi 5 (8GB ARM64)                |
               |                                                        |
               |  Official 27W USB-C PD Power Supply (5.1V / 5.0A)      |
               +-------+--------------------+--------------------+------+
                       |                    |                    |
        DSI Ribbon /   |     USB Type-A     |     USB Type-A     | USB Type-A
        HDMI + Touch   |     Data Cable     |     Data Cable     | (Hospital LAN)
                       |                    |                    |
                       v                    v                    v
             +-----------------+   +------------------+   +--------------+
             | 7-10" Kiosk     |   | ESP32 Host Node  |   | Pi Zero W    |
             | Capacitive DSI  |   | (CP2102 USB UART)|   | (USB Gadget  |
             | Touchscreen     |   +--------+---------+   |  Ethernet)   |
             +-----------------+            |             +------+-------+
                                        UART| 3.3V TTL           | CSI Ribbon
                                            v                    v
                                   +------------------+   +--------------+
                                   | ADH-Tech         |   | Raspberry Pi |
                                   | GT-521F32 Optical|   | Camera Mod 3 |
                                   | Fingerprint Mod  |   | Wide NoIR    |
                                   +------------------+   +--------------+
```

---

## 2. Component Pinout Specifications

### 2.1 ADH-Tech GT-521F32 to ESP32 NodeMCU / DevKit

The GT-521F32 optical fingerprint sensor uses a 4-pin JST-SH connector. It communicates via 3.3V TTL UART at 9600 to 115200 baud (default: 9600 during boot, negotiated to 115200 for template streaming).

| GT-521F32 Pin | Wire Color (Standard) | ESP32 Pin | Function / Notes |
|:---:|:---:|:---:|:---|
| **Pin 1 (GND)** | Black | **GND** | Common ground reference |
| **Pin 2 (VCC)** | Red | **VIN (5V) or 3V3** | Power supply (3.3V to 6.0V DC; 130mA peak during LED flash) |
| **Pin 3 (RX)** | Yellow | **GPIO 17 (TX2)** | 3.3V TTL UART input to sensor. ESP32 UART2 TX |
| **Pin 4 (TX)** | Green | **GPIO 16 (RX2)** | 3.3V TTL UART output from sensor. ESP32 UART2 RX |

> [!IMPORTANT]
> The GT-521F32 I/O pins operate at 3.3V TTL logic. ESP32 GPIOs operate natively at 3.3V, so **no bidirectional logic level converter is required**. Never connect GT-521F32 RX/TX to a 5V Arduino without level shifting.

---

### 2.2 ESP32 to Raspberry Pi 5 USB Host

The ESP32 communicates with the Pi 5 over a standard Micro-USB/USB-C data cable connected to one of the Pi 5 USB 3.0 (blue) or USB 2.0 (black) Type-A ports.

- **Interface:** Silicon Labs CP2102 / CH340 USB-to-UART bridge controller.
- **Pi 5 Device Path:** `/dev/serial/by-id/usb-Silicon_Labs_CP2102_USB_to_UART_Bridge_Controller-if00-port0` (udev symlink).
- **Framing Protocol:** LifeLink Framed Binary Protocol (`LLFP`, CRC32, request-reply semantics).
- **Baud Rate:** 115200 baud, 8 data bits, no parity, 1 stop bit (8N1).

---

### 2.3 Camera Substation Interconnect

#### 2.3.1 Raspberry Pi 3B+ to Pi 5 via Dedicated Wired Ethernet (Primary)
The primary camera substation utilizes a Raspberry Pi 3 Model B+ connected directly to the Raspberry Pi 5 via standard RJ45 Ethernet.
- **Physical Link:** Cat5e or Cat6 UTP patch cable directly between Pi 3B+ and Pi 5 Ethernet jacks (or via an isolated medical switch).
- **Controller:** Pi 3B+ onboard Microchip LAN7515 Gigabit Ethernet over USB 2.0 (~300 Mbps bandwidth).
- **Subnet:** Dedicated link-local network `192.168.50.0/24`.
  - Pi 5 Host: `192.168.50.1` (`eth0`)
  - Pi 3B+ Camera Substation: `192.168.50.2` (`eth0`, listening on port `5000`)
- **Camera Interface:** 15-pin 1.0mm pitch standard CSI ribbon cable connecting Camera Module 3 NoIR to the Pi 3B+ CSI port (silver pins face HDMI port).
- **IR Illumination:** BCM GPIO18 (Physical Pin 12, PWM0 capable) drives the 850nm NIR LED MOSFET switch, identical to the Pi Zero pinout.

#### 2.3.2 Raspberry Pi Zero W to Pi 5 USB Gadget Ethernet (Legacy Alternative)
For legacy compact installations, the Pi Zero W acts as a specialized USB Gadget device providing USB Ethernet emulation (`g_ether` / `cdc_ether`) over a single USB cable.

- **Pi Zero W Port:** **Middle Micro-USB port** labeled **USB** (NOT the PWR IN port).
- **Pi 5 Port:** USB 3.0 Type-A port.
- **Power & Data:** Both 5V DC power and full-duplex Ethernet emulation are carried across this single physical cable.
- **Subnet:** Isolated link-local network `192.168.55.0/24`.
  - Pi 5 USB host: `192.168.55.1` (`usb0` / `ethX`)
  - Pi Zero W device: `192.168.55.2` (`usb0`, port `5001`)

---

### 2.4 Raspberry Pi Camera Module 3 NoIR to Pi Zero W

- **Interface:** 15-pin to 22-pin flexible flat cable (FFC) CSI ribbon cable.
- **Connector on Pi Zero W:** 22-pin 0.5mm pitch CSI connector (silver contacts face toward PCB board).
- **Optics:** Visible + Near-Infrared (NoIR), wide angle (120° FOV) with autofocus (Sony IMX708 sensor without IR cut filter).

---

### 2.4.1 850 nm Infrared (NIR) LED Illumination Module & MOSFET Driver

Automatic iris illumination is controlled synchronously by the Pi Zero W camera service via **GPIO18** (BCM 18 / Physical Pin 12).

| Component / Function | Raspberry Pi Zero W Pin | Physical Header Pin | Electrical Characteristics |
|:---|:---:|:---:|:---|
| **IR LED Control Signal (GATE)** | **GPIO 18** (PWM0 / GPIO) | **Pin 12** | 3.3V Logic Output (Active High: HIGH=ON, LOW=OFF) |
| **Logic Ground Reference** | **GND** | **Pin 6, 9, 14, 20, 25, 30, 34, 39** | Common system ground return |
| **Illumination Power Supply (+V_LED)** | External 5V or 12V Supply | N/A (Isolated Rail) | Powers high-current 850 nm LED array |

> [!CAUTION]
> **Electrical Safety Invariant:** GPIO18 is strictly a **logic-level control signal** (max 16 mA drive limit). High-current 850 nm IR LED arrays must **NEVER** be powered directly from the Raspberry Pi GPIO pins or 3.3V regulator rail. Always use an appropriately rated N-channel logic-level MOSFET (e.g., IRLZ44N, 2N7000, AO3400) or dedicated constant-current LED driver module.

#### Recommended MOSFET Switching Circuit

```text
               +V_LED (5V / 12V DC External Supply)
                   |
                   +-------+
                           |
                        [ 850nm IR LED Array ]
                           |
                           +-------+
                                   | (Drain)
                                 |---
   Pi Zero W GPIO18 ----[100R]---|    N-Channel Logic MOSFET (IRLZ44N / AO3400)
    (Physical Pin 12)    Gate    |--->
                                   | (Source)
                                   +-------+
                                   |       |
                                [10k]      |
                              Pull-Down    |
                                   |       |
   Common GND ---------------------+-------+------- Power GND (Negative Rail)
```

1. **Gate Resistor (100Ω - 220Ω):** Suppresses high-frequency ringing and limits gate charging inrush current.
2. **Gate Pull-Down Resistor (10kΩ):** Tied between Gate and Source/GND. **Guarantees the IR LED defaults to OFF** during Pi Zero boot, kernel transitions, floating GPIO states, or power-off.
3. **Common Ground:** Connect the negative terminal of the external LED power supply directly to the Raspberry Pi Zero GND plane to maintain a uniform gate-to-source reference voltage ($V_{GS}$).

#### Photobiological Eye Safety Considerations (850 nm NIR)
- 850 nm near-infrared radiation is nearly invisible to the human eye (only a faint, deep red glow may be visible at close proximity).
- Because 850 nm does not trigger the natural human blink reflex (aversion response), excessive optical power or prolonged exposure can pose retinal and corneal thermal hazards.
- **Safety Standard:** Compliance with **IEC 62471:2006** (Photobiological Safety of Lamps and Lamp Systems) is mandatory. The LifeLink camera client enforces a **15.0-second hardware watchdog timeout** (`MAX_SCAN_TIMEOUT_SECONDS`) that automatically forces GPIO18 LOW if the scanning session does not cleanly terminate.
- **Clinical Distance:** Patient eye distance must be maintained between 20 cm and 40 cm. Never place high-intensity illuminators closer than 15 cm.

#### Computer Vision & NIR Recognition Compatibility Analysis
- **Visible vs. Near-Infrared Spectrum Differences:** LifeLink 2.0 uses **LightIrisNet** (MobileNetV3 backbone) for segmentation and **VIS-IrisFormer** for feature extraction. These architectures were primarily pretrained on visible-spectrum iris benchmarks (e.g., UBIRIS.v2, VISOB).
- Under 850 nm NIR illumination:
  1. Melanin absorption in darker irises drops significantly, revealing intricate stromal and crypt fiber patterns invisible in standard RGB light.
  2. Specular corneal glares are more concentrated due to point-source NIR LEDs.
  3. Pupil-to-iris contrast is heightened, facilitating circular Hough / contour segmentation.
- **Deployment Recommendation:** For physical deployment with 850 nm illumination, verify segmentation masks with the onboard ISO quality evaluator. If segmentation accuracy drops on NIR captures, adapt model weights using NIR iris datasets (e.g., CASIA-Iris-Thousand, ND-CrossSensor-2013) rather than fabricating accuracy metrics.

---

### 2.5 Raspberry Pi Touchscreen to Pi 5

- **Video & Touch Interface:** 22-pin to 15-pin DSI ribbon cable to Pi 5 CAM/DISP0 or CAM/DISP1 port.
- **Alternative:** HDMI Micro-to-Standard Cable for display + USB-A to USB-C cable for capacitive touch digitizer.

---

## 3. Power Budget & Thermal Architecture

The entire kiosk terminal is powered from a single wall plug via the **official Raspberry Pi 27W USB-C Power Delivery (PD) power supply** (5.1V / 5.0A).

### Power Consumption Breakdown

| Subsystem | Idle Power | Peak Operational Power | Current @ 5.1V (Peak) |
|---|:---:|:---:|:---:|
| **Raspberry Pi 5 (8GB)** | 2.8 W | 11.5 W | 2.25 A |
| **Pi 5 Active Cooler Fan** | 0.1 W | 0.6 W | 0.12 A |
| **7" Touchscreen Display (100% Backlight)** | 2.2 W | 3.2 W | 0.63 A |
| **ESP32 + GT-521F32 (Sensor LED Active)** | 0.4 W | 0.8 W | 0.16 A |
| **Pi Zero W + Camera Module 3 (Capturing)**| 0.8 W | 1.8 W | 0.35 A |
| **USB Gadget Transmission Peak** | 0.1 W | 0.3 W | 0.06 A |
| **Total System Power** | **6.4 W** | **18.2 W** | **3.57 A** |

> [!TIP]
> **Safety Margin:** Peak system draw is **18.2 W (3.57 A)** against the **27 W (5.0 A)** rated PSU, leaving a **32% power headroom margin**. This completely prevents brownouts and undervoltage throttles (`vcgencmd get_throttled = 0x0`).

---

## 4. Grounding and Signal Integrity Best Practices

1. **Star Grounding:** All peripheral ground signals (`GND`) are referenced back to the Pi 5 USB host ground planes through the shielded USB braided cable shields.
2. **Ferrite Beads:** Snap-on ferrite beads are placed on the USB cables leading to the ESP32 and Pi Zero W to suppress radiated EMI from the kiosk power converter.
3. **Cable Length Limits:**
   - ESP32 USB cable: Maximum 1.0 meter (shielded 28AWG/24AWG).
   - Pi Zero W USB cable: Maximum 0.5 meter (high-speed data verified).
   - CSI Camera ribbon: Maximum 150mm to minimize capacitive signal degradation on high-speed MIPI-CSI lanes.
