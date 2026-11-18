# LifeLink 2.0 — Unresolved Issues & Embedded Deployment Advisories

**Honest Engineering Gate:** In strict adherence to workspace invariants, Level A (synthetic) and Level B (contract driver) verification passes must NEVER be falsely reported as physical Level C embedded hardware proofs.

This document identifies all hardware prerequisites, physical bench tests, and clinical edge cases that must be verified when physical target hardware is provisioned.

---

## 1. Physical Hardware Deployment Gates (Level C Prerequisites)

The following items are completely verified in software emulation (Level A) and wired client protocols (Level B), but require physical bench testing upon Raspberry Pi 5 assembly:

| Item ID | Component | Level A/B Status | Level C Bench Verification Prerequisite |
| :--- | :--- | :--- | :--- |
| **DEP-01** | **GT-521F32 Optical Sensor** | Fully verified via synthetic 498-byte templates and serial framing. | Requires connecting physical sensor to ESP32 UART2 (GPIO16/17) and verifying optical latency and dry-finger capture. |
| **DEP-02** | **850 nm IR LED Illumination** | Fully verified in daemon lifecycle, watchdog timers, and mock GPIO. | Requires physical oscilloscope measurement of GPIO18 gate voltage and photodiode verification of 850 nm optical output. |
| **DEP-03** | **IMX708 NoIR Auto-Focus** | Verified via synthetic image generation and burst coordinator. | Requires tuning Picamera2 lens voice-coil motor (VCM) for close-range ocular focus (8–12 cm). |
| **DEP-04** | **Waveshare 7" Touchscreen** | Verified via 1024x600 responsive Chromium layout and 48px touch targets. | Requires physical calibration of capacitive touch digitizer under surgical nitrile gloves. |

---

## 2. Clinical Operational Advisories & Edge Cases

1. **Ocular Pathology & Cataracts:** Severe corneal opacity or dense mature cataracts can reduce unconstrained iris recognition confidence. In such cases, the system cleanly prompts the clinician to use the secondary modality (GT-521F32 fingerprint sensor) to achieve biometric identification.
2. **Severe Resuscitation Bay Ambient Lighting:** Overhead surgical spotlights (halogen / high-intensity LED surgical booms) emit broad-spectrum near-infrared noise that can cause specular reflections. The 850nm narrowband bandpass optical filter attached to the IMX708 NoIR lens is designed to mitigate this, and must be aligned during physical deployment.
3. **Power Isolation & USB Brownout Prevention:** The Raspberry Pi 5 requires a dedicated 27W (5.1V / 5.0A) USB-C power supply. Powering the Pi Zero W and ESP32 DevKit directly from the Pi 5 USB ports draws ~1.2A combined during simultaneous IR LED and optical backlight activation. Ensure host power budget complies with official Pi 5 specifications.
