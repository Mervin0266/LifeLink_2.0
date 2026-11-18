# LifeLink 2.0 — Iris Repository Integration Plan

**Document:** `docs/iris-repository-integration.md`  
**Author:** Lead Development Engineer, LifeLink 2.0  
**Date:** 2026-10-13  
**Status:** Architecture and Adapter Specification  

---

## 1. Overview

LifeLink 2.0 integrates the computer vision and machine learning components from three research repositories:
1. **LightIrisNet** for visible-light iris and pupil segmentation.
2. **Daugman Polar Unwrapping** for annular iris texture normalization.
3. **Vis-IrisFormer** for Vision Transformer patch token extraction and cosine matching.
4. **IrisQualityCapture** (algorithmic concepts) for ISO/IEC 29794-6 capture quality filtering.

This document specifies the exact classes, weights, input/output tensors, ARM64 optimization strategies, and adapter boundaries.

---

## 2. Component Pipeline Architecture

```text
Live Camera Frame (Pi Zero W / RAM)
        │
        ▼
ISO/IEC Quality Filter (Sharpness, Exposure, Glare, Min Iris Size)
        │ Accepted RGB ROI Crop
        ▼
LightIrisNet Segmenter (MobileNetV3 DeepLabv3+ Encoder-Decoder)
        │
        ├──> Binary Iris Mask (H x W)
        ├──> Binary Pupil Mask (H x W)
        ├──> Fitted Iris Ellipse (center, axes, angle)
        └──> Fitted Pupil Ellipse (center, axes, angle)
        │
        ▼
Daugman Rubber-Sheet Normalizer (Polar Coordinate Transform)
        │
        ▼
Normalized Grayscale Iris Strip (64 x 512, uint8/float32)
        │
        ▼
Vis-IrisFormer Recognizer (MAE + RoPE2D Transformer Encoder)
        │
        ▼
Iris Template: 128 Patch Embeddings x 768 Float32 (~393 KB uncompressed)
        │
        ├──> Storage: Local PostgreSQL (pgcrypto AES-256 encrypted)
        └──> Verification / Candidate Search: Patch-wise Cosine Similarity
```

---

## 3. LightIrisNet Integration

### 3.1 Model Architecture & Selected Code
- **Model:** `MobileNetV3Large_DeepLabV3Plus`
- **Source Files in Upstream:** `LightIrisNet/src/irisseg/_test_impl.py`, `irisseg/models.py`
- **Adapter in LifeLink 3.0:** `iris-module/engine/segmenter.py` (`LightIrisNetSegmenter`)
- **Input:** Eye crop image $(H \times W \times 3)$ in RGB format, resized to $224 \times 224$ or $256 \times 256$ with ImageNet normalization.
- **Output:**
  - `iris_mask`: $(H \times W)$ boolean numpy array where iris pixels are 1.
  - `pupil_mask`: $(H \times W)$ boolean numpy array where pupil pixels are 1.
  - `iris_ellipse`: `((cx, cy), (major, minor), angle)`
  - `pupil_ellipse`: `((cx, cy), (major, minor), angle)`
- **Checkpoint:** `LightIrisNet/model/best_mobilenetv3.pt` (17.2 MB).

### 3.2 ARM64 Optimization & Execution
- In evaluation mode (`model.eval()`) with `torch.inference_mode()`.
- Thread count pinned via `torch.set_num_threads(4)` on Pi 5 (quad-core Cortex-A76).
- Peak memory footprint: $\approx 180$ MB RAM during forward pass.
- Latency on Pi 5: $\sim 180$ ms.

---

## 4. Normalization: Daugman Rubber-Sheet Transform

### 4.1 Algorithm Description
- Unwraps the annular ring between the pupil boundary $(r_{\text{pupil}}(\theta))$ and limbic boundary $(r_{\text{iris}}(\theta))$ into a rectangular polar matrix.
- Transformation mapping:
  $$I(x(r, \theta), y(r, \theta)) \longrightarrow I_{\text{norm}}(r, \theta)$$
  where $r \in [0, 1]$, $\theta \in [0, 2\pi)$.
- **Target Matrix Dimensions:** 64 radial samples (height) $\times$ 512 angular samples (width).
- Grayscale conversion: luminance calculation $0.299R + 0.587G + 0.114B$.
- **Adapter in LifeLink 3.0:** `iris-module/engine/normalizer.py` (`IrisNormalizer`).

---

## 5. Vis-IrisFormer Integration

### 5.1 Model Architecture & Selected Code
- **Model:** `MAEVisionTransformers` with 2D Relative Positional Encoding (`rope2d`) and mean/map feature pooling.
- **Source Files in Upstream:** `Vis-IrisFormer/model/Transformers/VIT/mae.py`
- **Adapter in LifeLink 3.0:** `iris-module/engine/recognizer.py` (`VISIrisFormerRecognizer`)
- **Input:** Normalized grayscale strip $(1, 1, 64, 512)$ or replicated 3-channel $(1, 3, 64, 512)$.
- **Patch Embedding:** Non-overlapping patches of $16 \times 16$:
  $$\text{Number of patches} = \left(\frac{64}{16}\right) \times \left(\frac{512}{16}\right) = 4 \times 32 = 128 \text{ patches}$$
  Each patch is projected to embedding dimension $D = 768$.
- **Transformer Encoder Stack:** 12 layers, 12 attention heads, hidden dim 768.
- **Output Template:** Tensor of shape $(128, 768)$ in float32.
- **Checkpoint:** `LifeLink/models/vis_irisformer/sota.pth` (453.4 MB).

### 5.2 Pairwise Matching Algorithm
- Given probe template $A \in \mathbb{R}^{128 \times 768}$ and gallery template $B \in \mathbb{R}^{128 \times 768}$:
  $$\text{Similarity}(A, B) = \frac{1}{128} \sum_{i=1}^{128} \frac{A_i \cdot B_i}{\|A_i\| \|B_i\|}$$
- Returns scalar cosine score $S \in [-1.0, 1.0]$.
- Initial operational threshold: $S \ge 0.84$ triggers a candidate match (subject to empirical calibration).

---

## 6. Iris Quality Filtering (Ported from IrisQualityCapture)

Implemented in `iris-module/camera-client/quality.py` for Pi Zero W and Pi 5 ingestion:

| Dimension | Method | Target / Rejection Criterion |
|---|---|---|
| **Sharpness** | Variance of Laplacian on grayscale eye crop: $\sigma^2(\nabla^2 I)$ | $\ge 70.0$ (blur rejection if below) |
| **Illumination** | Mean pixel intensity $\mu$ across ROI | $40 \le \mu \le 215$ (underexposed/overexposed) |
| **Glare / Specular Reflection** | Count of saturated pixels ($I(x,y) \ge 245$) in iris ROI | $\le 4\%$ of total iris mask area |
| **Iris Diameter** | Bounding circle diameter $D_{\text{iris}}$ | $\ge 100$ pixels |
| **Gaze / Aspect Ratio** | Ratio of major to minor ellipse axes $a / b$ | $0.80 \le a/b \le 1.25$ (off-axis gaze rejection) |

---

## 7. Storage Format for Iris Templates

In the local PostgreSQL database, iris templates are serialized as binary blobs and encrypted:
- Header: Version (1 byte), Eye Side (1 byte: `0=OD/Right`, `1=OS/Left`), Model ID (2 bytes: `0x0001` for VIS-IrisFormer), Feature Dim (2 bytes: 768), Patch Count (2 bytes: 128).
- Payload: $128 \times 768 \times 4$ bytes = $393,216$ bytes (raw float32).
- Encrypted with AES-256-GCM using `TEMPLATE_ENCRYPTION_KEY`.
- Stored in table `iris_templates`.

---

## 8. Unresolved Blockers and Mitigations

1. **Hardware Macro Limit on Camera Module 3 NoIR:**
   - *Risk:* Wide-angle lens may require being within 5–8 cm of the eye to obtain a 100-pixel iris diameter, causing focus or lighting issues.
   - *Mitigation:* Explicit mock mode simulates valid captures; hardware test script `scripts/test_camera_optics.py` measures actual resolution and iris diameter before any clinical validation claim.
2. **Threshold Calibration:**
   - *Risk:* 0.84 threshold is a literature baseline, not verified on target hardware.
   - *Mitigation:* System flags all match results with confidence score and marks candidate matching as requiring secondary operator verification.
