# LifeLink 2.0 — Source Audit

**Document:** `docs/source-audit.md`  
**Author:** Lead Development Engineer, LifeLink 2.0  
**Date:** 2026-10-13  
**Status:** Complete baseline audit  

---

## 1. Executive Summary

This audit establishes the baseline facts, proposed architectural adaptations, and unresolved assumptions across the LifeLink 3.0 codebase, historical LifeLink 2.0 assets (`PROJECT_DOCUMENTATION.md`, `PROJECT_MEMORY.md`), hardware drivers (`fplibMicro.py`), and the four referenced visible-spectrum iris recognition repositories (`VISIrisHub`, `LightIrisNet`, `Vis-IrisFormer`, and `IrisQualityCapture`).

---

## 2. Source-Derived Facts vs. Proposed Adaptations vs. Blocked Assumptions

| Domain | Source-Derived Facts (Verified in Code/Docs) | Proposed 3.0 Adaptations | Blocked / Unverified Assumptions |
|---|---|---|---|
| **System Architecture** | LifeLink 2.0 used a private Wi-Fi AP for ESP32 and Pi Zero W HTTP endpoints. When Wi-Fi fluctuated, device communication failed completely. | LifeLink 3.0 mandates **100% wired peripheral links**: ESP32 over USB Serial, Pi Zero W over USB Ethernet gadget (`dwc2`/`g_ether`). Touchscreen on DSI/HDMI+USB. | Physical USB Ethernet gadget throughput, latency, and power budget on Pi Zero W + Pi 5 host need runtime verification on physical hardware. |
| **Authentication & RBAC** | LifeLink 2.0 had no staff authentication; the UI booted directly to a standby/home screen with shared access. | Three distinct role-based login portals: **Clinical Login**, **Hospital Login**, **Admin Login**. Individual staff credentials, hashed with Argon2id/bcrypt, scoped RBAC tokens. | Offline authentication strategy when Supabase is unreachable requires local credential cache with secure verifiers. |
| **Fingerprint Hardware** | Sensor is GT-521F32 / GT-521F52 (optical). Pinout: TX=GPIO16, RX=GPIO17, GND, VCC=3V3. MicroPython UART RX buffer default (256B) caused silent template truncation (needs $\ge 2048$B). Sensor firmware `20171018`: `EnrollStart(-1)` fails; requires enrolling to scratch slot 199, calling `GetTemplate(199)`, then `DeleteID(199)`. Backlight must be ON for `IsPressFinger`. | ESP32 runs dedicated USB Serial framing daemon. Host Pi 5 service exclusively owns serial port (`/dev/serial/by-id/*`). Binary framing: `LLFP` magic, version, request ID, command, payload length, payload, CRC32. | Sensor-level `Identify1_N` has a known high false-match rate. Database-wide 1:N fingerprint search requires loading reference templates into scratch slots and running native 1:1, or relying on Iris 1:N candidate search. |
| **Fingerprint Templates** | GT-521F32 produces proprietary **498-byte** templates. | Stored encrypted in local PostgreSQL using symmetric AES/pgcrypto. Temporary slots wiped immediately after transfer. | Proprietary templates cannot be directly matched by generic OpenCV/minutiae libraries without reverse-engineering or vendor SDK. |
| **Iris Camera Hardware** | Raspberry Pi Camera Module 3 Wide NoIR on Pi Zero W CSI ribbon. | Pi Zero W runs lightweight Python capture service in RAM; communicates with Pi 5 over USB gadget Ethernet (`192.168.55.0/24`). Quality checks before transmission. | Camera Module 3 Wide lens has fixed/autofocus macro limits at typical eye distances (10–20 cm). Visual resolution and iris pixel diameter ($\ge 100$ px) must be empirically measured. |
| **Iris Quality Evaluation** | `IrisQualityCapture` is Android-specific (Camera2 + MediaPipe Face Mesh + OpenCV Java + MITRE BIQT server). | Port ISO/IEC 29794-6 quality checks to Python/OpenCV for Pi Zero W: Sharpness (Laplacian variance), Exposure (histogram), Glare (specular reflection mask), Iris diameter ($\ge 100$ px), Off-angle gaze (pupil/iris concentricity). | MITRE BIQT server is an external Java/C++ dependency; standalone Python quality filtering replaces it on-device. |
| **Iris Segmentation** | `LightIrisNet` provides MobileNetV3-Large DeepLabv3+ segmentation model (<10M params). Checkpoint `model/best_mobilenetv3.pt` (17.2 MB) exists and is verified. | Pi 5 runs segmentation service: produces binary iris mask, pupil mask, and fitted ellipses. | Model requires RGB eye crop; runs on ARM64 CPU in $\sim 150\text{--}300$ ms. Numerical stability on PyTorch CPU verified. |
| **Iris Normalization** | Daugman Rubber-Sheet model unwraps annular iris between pupil and limbus boundaries into polar coordinates. | 64 rows $\times$ 512 columns polar matrix unwrapped using bilinear interpolation. | Occlusion masking (eyelids/eyelashes) needs careful weighting during feature comparison. |
| **Iris Feature Extraction** | `Vis-IrisFormer` (Vision Transformer MAE + RoPE2D) takes $64 \times 512$ normalized grayscale iris. Checkpoint `sota.pth` (453.4 MB) exists in workspace. Produces 128 patch embeddings of dimension 768. | Pi 5 extracts $128 \times 768$ patch tokens. Compares templates using patch-wise cosine similarity. | Upstream README claims nominal threshold 0.84, but actual FAR/FRR threshold must be experimentally validated with genuine/impostor distribution curves. |
| **Data Persistence** | LifeLink 2.0 stored clinical records in Supabase and biometrics in local PostgreSQL. If Wi-Fi was down, writes failed. | **Hybrid Local-First Persistence**: Pi 5 local PostgreSQL is the operational primary for biometrics, local cache, device jobs, audit logs, and transactional outbox. Supabase Cloud receives approved clinical records over wired hospital Ethernet/internet. Biometric templates NEVER upload to Supabase by default. | Network segmentation and hospital firewall rules for Supabase HTTPS access must be verified on deployment. |
| **Patient Deletion** | LifeLink 2.0 had no deletion management. | **Multi-stage Deletion Request Workflow**: Request submitted by Records Admin with documented reason $\rightarrow$ automated legal-hold / retention check $\rightarrow$ required secondary administrative approval $\rightarrow$ coordinated local + Supabase tombstone recording and audit logging. No raw browser-side `DELETE`. | Regulatory retention obligations (e.g., 7-year medical record retention) require soft-deletion/archival rather than physical erasure in clinical settings. |

---

## 3. Audited Repositories Breakdown

### 3.1 VISIrisHub
- **Path:** `LifeLink/VISIrisHub`
- **License:** MIT License (Copyright 2025 Naveenkumar GV)
- **Role:** Parent index repository and documentation reference for CUVIRIS dataset and pipeline components.

### 3.2 LightIrisNet
- **Path:** `LifeLink/LightIrisNet`
- **License:** MIT License (Copyright 2025 Naveenkumar GV)
- **Verified Files:** `model/best_mobilenetv3.pt` (17,198,226 bytes), `src/irisseg/_test_impl.py`, `src/irisseg/_train_impl.py`.
- **Adaptation Plan:** Extract the inference forward pass into `iris-module/engine/segmenter.py` with standalone PyTorch model definitions, avoiding training dependencies.

### 3.3 Vis-IrisFormer
- **Path:** `LifeLink/Vis-IrisFormer`
- **License:** Research code extending IrisFormer (Sun et al., IEEE SPL 2024).
- **Verified Files:** `models/vis_irisformer/sota.pth` (453,409,206 bytes), `model/Transformers/VIT/mae.py`.
- **Adaptation Plan:** Integrate patch token extractor into `iris-module/engine/recognizer.py`. Input format: normalized grayscale image $64 \times 512 \rightarrow$ 128 patch embeddings of size 768. Matching via patch-wise cosine similarity.

### 3.4 IrisQualityCapture
- **Path:** `LifeLink/IrisQualityCapture`
- **License:** MIT License (Copyright 2024 Naveenkumar GV)
- **Verified Files:** Android Java/Kotlin source, MediaPipe face mesh, Camera2.
- **Adaptation Plan:** Port image quality algorithms to Python OpenCV for Pi Zero W:
  1. Sharpness: Tenengrad gradient / Laplacian variance.
  2. Illumination / dynamic range: Mean grayscale intensity $[40, 215]$, saturation clip $< 5\%$.
  3. Specular reflection / glare: Masking bright spots ($> 245$).
  4. Pupil/iris geometry: Bounding box size ($\ge 100$ px diameter) and concentricity.

---

## 4. Operational Modes Definition

To ensure testability and safety across all development and deployment phases, three runtime modes are strictly defined:

1. **`MOCK_MODE=true` (Default Development/CI Mode):**
   - Emulates ESP32 USB serial with deterministic, controllable GT-521F32 command responses and mock 498-byte templates.
   - Emulates Pi Zero W camera service with synthetic eye crops (pass, fail, glare, blur, mismatch test vectors).
   - Local database runs on PostgreSQL (or SQLite mock fallback for rapid dev/test).
   - Cloud sync runs against mock Supabase worker or test project.
   - No physical hardware required; 100% testable on workstation and CI.

2. **`HARDWARE_MODE=true` (Physical Device Mode):**
   - Connects to physical ESP32 via `/dev/serial/by-id/*` at 115200 baud.
   - Connects to physical Pi Zero W camera service over USB gadget Ethernet (`192.168.55.2:5001`).
   - Requires actual GT-521F32 sensor and Camera Module 3 NoIR.
   - Graceful fallback to degraded / exception states if peripherals disconnect.

3. **`VALIDATION_MODE=true` (Biometric Benchmark Mode):**
   - Runs genuine/impostor pair evaluation over pinned datasets.
   - Measures False Match Rate (FMR), False Non-Match Rate (FNMR), Equal Error Rate (EER), and latency.
   - Prevents unvalidated threshold assertions in clinical records.
