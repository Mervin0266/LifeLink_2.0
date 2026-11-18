# LifeLink 2.0 — Hardware Bill of Materials (BOM)

**Document:** `docs/hardware-bom.md`  
**Author:** Lead Hardware & Systems Engineer, LifeLink 2.0  
**Target:** Raspberry Pi 5 Touchscreen Kiosk Terminal  
**Status:** Approved Component Sourcing Specification  

---

## 1. Overview

This document specifies the complete bill of materials for building a production LifeLink 2.0 emergency medical identification kiosk terminal. All components are commercially available off-the-shelf (COTS) parts selected for durability, clinical kiosk ergonomics, and ARM64 compatibility.

---

## 2. Master Bill of Materials

| Item # | Component Category | Component Description | Exact Part Number / Model | Recommended Vendor | Est. Unit Cost (USD) | Tested Alternative |
|:---:|---|---|---|---|:---:|---|
| **1** | Host Compute | Raspberry Pi 5 Single Board Computer (8GB RAM) | SC1112 | Raspberry Pi Approved Reseller / Digikey | $80.00 | Raspberry Pi 5 (4GB) |
| **2** | Host Cooling | Raspberry Pi 5 Active Cooler (Heatsink + PWM Fan) | SC1148 | Raspberry Pi Reseller / Pimoroni | $5.00 | Argon THRML 60mm active cooler |
| **3** | Host Storage | SanDisk Extreme Pro 128GB MicroSD A2 / NVMe M.2 256GB | SDSQXCY-128G-GN6MA | Western Digital / Amazon | $22.00 | Geekworm X1001 M.2 PCIe HAT + NVMe SSD |
| **4** | Power Supply | Official Raspberry Pi 27W USB-C PD Power Supply (5.1V 5A) | SC1154 | Raspberry Pi Reseller | $12.00 | Anker 30W USB-C PD with 5A cable |
| **5** | Display & Touch | 7-inch Capacitive Touchscreen (1024x600 or 1280x800 DSI/HDMI) | Waveshare 7inch DSI LCD (C) | Waveshare / Amazon | $55.00 | Official Raspberry Pi 7" Touch Display 2 |
| **6** | Fingerprint Controller | ESP32-WROOM-32D Development Board (CP2102 USB UART) | ESP32-DevKitC-32D | Espressif / Digikey | $6.50 | NodeMCU ESP32-S |
| **7** | Fingerprint Sensor | ADH-Tech GT-521F32 Optical Fingerprint Sensor (498B Template) | SEN-14585 / GT-521F32 | SparkFun / Adafruit / RobotShop | $49.95 | ADH-Tech GT-521F52 (3000 template capacity) |
| **8** | Camera Compute Node | Raspberry Pi Zero 2 W or Raspberry Pi Zero W | SC0510 | Raspberry Pi Reseller / Adafruit | $15.00 | Raspberry Pi Zero 2 W (quad-core ARM64 recommended) |
| **9** | Camera Storage | SanDisk Ultra 32GB MicroSD Card Class 10 A1 | SDSQUNR-032G-GN6MN | Amazon / Newegg | $8.00 | Kingston Canvas Select Plus 32GB |
| **10** | Camera Sensor | Raspberry Pi Camera Module 3 NoIR Wide (12MP autofocus) | SC0874 | Raspberry Pi Reseller / Digikey | $35.00 | Pi Camera Module 3 Standard NoIR |
| **11** | Camera Ribbon Cable | 15-pin to 22-pin CSI FFC Ribbon Cable (150mm length) | CAB-CSI-150MM | Adafruit / Waveshare | $3.50 | 200mm shielded FFC |
| **12** | USB Interconnect 1 | Shielded Micro-USB to USB-A High-Speed Data Cable (1.0m) | UUSBHAUB1M | StarTech / Amazon | $5.00 | CableCreation 24+28AWG USB cable |
| **13** | USB Interconnect 2 | Heavy-Duty Micro-USB to USB-A Data & Power Cable (0.5m) | UUSBHAUB50CM | StarTech / Amazon | $4.50 | Anker PowerLine Micro-USB |
| **14** | Sensor Jumper Wires | 4-Pin JST-SH 1.0mm Pitch to Dupont 2.54mm Female Leads | JST-SH-4P-DUP | SparkFun / Adafruit | $2.50 | Pre-crimped silicone test leads |
| **15** | Kiosk Enclosure | 3D Printed / Laser-Cut Clinical Kiosk Enclosure (ABS/PETG) | LL2-KIOSK-ENC-V2 | Custom Fabrication / Local Hub | $35.00 | SmartiPi Touch Pro enclosure |
| **TOTAL** | | **Complete Kiosk Hardware Assembly** | | | **~$333.95** | |

---

## 3. Tooling and Assembly Consumables

1. **Hex Stand-offs and Screws:** M2.5 nylon/brass standoff kit for Pi 5 and display mounting.
2. **Thermal Interface:** Pre-applied thermal pads on Pi 5 Active Cooler.
3. **ESD Protection:** ESD grounding wrist strap during sensor and ribbon handling.
4. **Firmware Flashing Cable:** Standard USB-C or Micro-USB cable for initial ESP32 MicroPython flash via `esptool.py`.
