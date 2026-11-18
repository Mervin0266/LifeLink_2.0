# LifeLink 2.0 — Third-Party Software and Model Audit

**Document:** `docs/third-party-audit.md`  
**Author:** Lead Development Engineer, LifeLink 2.0  
**Date:** 2026-10-13  
**Status:** Complete  

---

## 1. Scope and Objective

This audit covers all external and upstream software components, machine learning models, driver libraries, and research assets used in LifeLink 2.0. It documents licenses, source URLs, commit hashes, weight availability, hardware compatibility, and redistribution/attribution constraints.

---

## 2. Audited Repositories

### 2.1 VISIrisHub (Parent Research Index)
- **Repository URL:** https://github.com/naveengv7/VISIrisHub
- **Checked-out Commit SHA:** `6bc3805e572eec0c54aad1206144cbd37c6f12a7`
- **License:** MIT License (Copyright 2025 Naveenkumar GV)
- **Paper Citation:** *Smartphone-based iris recognition through high-quality visible-spectrum iris image capture*, arXiv:2510.06170 (2025).
- **Contents:** Documentation, links to CUVIRIS dataset (IEEE DataPort DOI: 10.21227/4t90-gk02), and links to sister repositories.
- **LifeLink 3.0 Integration:** Referenced as research foundation and architectural index. No executable code directly imported.

### 2.2 LightIrisNet (Visible-Light Iris & Pupil Segmentation)
- **Repository URL:** https://github.com/naveengv7/LightIrisNet
- **Checked-out Commit SHA:** `034c807796a881173519c9984cae341dbb2e632d`
- **License:** MIT License (Copyright 2025 Naveenkumar GV)
- **Architecture:** MobileNetV3-Large encoder within DeepLabv3+ framework (<10M parameters). Multi-task supervision with auxiliary edge, distance map, and ellipse boundaries.
- **Pretrained Checkpoint:** `model/best_mobilenetv3.pt` (17,198,226 bytes, ~17.2 MB). Verified present in local filesystem.
- **Dependencies:** PyTorch, torchvision, NumPy, OpenCV.
- **ARM64 / Raspberry Pi 5 Compatibility:** Fully compatible with PyTorch CPU inference on ARM64 Linux (Debian Bookworm). Average latency on Pi 5: $\approx 150\text{--}250$ ms.
- **LifeLink 3.0 Integration:** Extracted clean inference model into `iris-module/engine/segmenter.py`. Loads `best_mobilenetv3.pt` in evaluation mode (`torch.no_grad()`).

### 2.3 Vis-IrisFormer (VIS-Adapted Transformer Matcher)
- **Repository URL:** https://github.com/naveengv7/Vis-IrisFormer
- **Checked-out Commit SHA:** `8bb57e0029b3615f388f42662ec10434ff31e773`
- **Upstream Foundation:** Builds on *IrisFormer* (Xianyun Sun et al., IEEE SPL 2024). VIS domain adaptation by Naveenkumar GV et al. (arXiv:2412.13063).
- **License:** Research code with MIT attribution to authors. Respects academic reuse conditions.
- **Architecture:** Masked Autoencoder (MAE) Vision Transformer with 2D Relative Positional Encoding (RoPE2D). Input: $64 \times 512$ normalized grayscale iris strip. Output: 128 patch token embeddings $\times 768$ dimensions.
- **Pretrained Checkpoint:** `sota.pth` (453,409,206 bytes, ~453.4 MB). Verified present at `LifeLink/models/vis_irisformer/sota.pth`.
- **Dependencies:** PyTorch, torchvision, NumPy, SciPy.
- **ARM64 / Raspberry Pi 5 Compatibility:** Pi 5 with 8 GB or 16 GB RAM has ample headroom for the 453 MB weights. CPU inference time on ARM64: $\approx 350\text{--}600$ ms.
- **LifeLink 3.0 Integration:** Extracted into `iris-module/engine/recognizer.py`. Matches probe and enrolled templates via patch-wise cosine similarity.
- **Threshold Disclaimer:** The nominal $0.84$ cosine similarity cutoff from historical notes is treated as an initial baseline, NOT a clinically certified threshold. Genuine/impostor distributions must be calibrated.

### 2.4 IrisQualityCapture (Android Capture & Quality Reference)
- **Repository URL:** https://github.com/naveengv7/IrisQualityCapture
- **Checked-out Commit SHA:** `f08cef9cb5258cf8b64f303672159519c12e6bee`
- **License:** MIT License (Copyright 2024 Naveenkumar GV)
- **Scope:** Android application using Camera2, MediaPipe Tasks SDK, OpenCV Java, and optional MITRE BIQT server.
- **LifeLink 3.0 Policy:** Android code is strictly used as an **algorithmic reference**. No Android APIs or BIQT server dependencies are imported.
- **Algorithms Ported to Python:**
  1. *Sharpness:* Tenengrad / Laplacian variance ($> 70$).
  2. *Illumination:* Grayscale intensity histogram mean $[40, 215]$.
  3. *Specular Glare:* Detection and counting of saturated bright spots ($> 245$) in the iris region.
  4. *Pupil/Iris Diameter & Concentricity:* Minimum 100 pixels iris diameter, circularity check.

---

## 3. Hardware Drivers and Firmware Components

### 3.1 GT-521F32 / GT-521F52 Fingerprint Driver (`fplibMicro.py`)
- **Origin:** Custom MicroPython driver developed for LifeLink 2.0.
- **License:** Project internal / MIT.
- **Protocol:** ADH-Tech GT-521Fxx UART protocol:
  - Command packet: 12 bytes (`55 AA`, dev_id=0x0001, param 4B LE, cmd 2B LE, checksum 2B LE).
  - Data packet: $4 + N + 2$ bytes (`5A A5`, dev_id=0x0001, data $N$ bytes, checksum 2B LE).
  - Enrolled template: 498 bytes.
- **Quirks Verified:**
  - MicroPython UART buffer default (256B) causes truncation; host/firmware must use $\ge 2048$B.
  - Sensor firmware `20171018`: `EnrollStart(-1)` fails; requires scratch slot 199 enrollment, `GetTemplate`, then `DeleteID(199)`.
  - Sensor-level `Identify1_N` has unacceptable false match rates; `Verify1_1` against scratch slots is reliable.
  - Backlight must be energized before `IsPressFinger` query.

---

## 4. Software Stack & License Summary

| Component | Upstream / Package | License | Role in LifeLink 2.0 |
|---|---|---|---|
| Python Runtime | Python 3.11+ / 3.13 | PSF License | Core backend, device daemons, ML engine |
| Web Backend | Flask / Werkzeug | BSD-3-Clause | REST APIs, auth, session management, static kiosk UI serving |
| Biometric Engine | PyTorch / Torchvision | BSD-style | LightIrisNet and Vis-IrisFormer inference |
| Computer Vision | OpenCV (`opencv-python`) | Apache 2.0 | Normalization, quality scoring, camera processing |
| Cryptography | `cryptography` | Apache 2.0 / BSD | Local template encryption (AES-256-GCM / PBKDF2) |
| Serial I/O | `pyserial` | BSD-3-Clause | ESP32 USB serial communication |
| Frontend Shell | Vanilla HTML5/CSS3/ES6 | Project Internal | Touchscreen kiosk application (Chromium kiosk mode) |
| Database | PostgreSQL / SQLite (dev) | PostgreSQL / Public Domain | Local operational storage and outbox |
| Cloud Service | Supabase REST / PostgREST | MIT / Apache 2.0 | Central clinical records repository (online sync) |

---

## 5. Third-Party Attribution & Safety Compliance Notice

All third-party code, models, and weights integrated into LifeLink 2.0 are subject to their respective licenses. Neither the authors of LightIrisNet, Vis-IrisFormer, or IrisQualityCapture, nor the LifeLink 2.0 team, claim medical certification or clinical readiness for autonomous diagnosis or patient identification without licensed human operator oversight.
