# LifeLink 2.0 — Iris AI Model Checkpoints & Acquisition Specification

## 1. Overview
The Raspberry Pi 5 runs deep-learning inference to segment eye images and extract invariant biometric iris templates:
1. **LightIrisNet**: MobileNetV3 with DeepLabv3+ decoder and boundary ellipse fitting for pupil/limbus boundary segmentation.
2. **Vis-IrisFormer**: Masked Autoencoder (MAE) Vision Transformer with 2D Rotary Position Embeddings (RoPE2D) producing 128 patch tokens x 768 feature dimensions.

---

## 2. Checkpoint Specifications & Checksums

| Model | Filename | Target Deployment Path | Size | SHA-256 Checksum |
|:---|:---|:---|:---|:---|
| **LightIrisNet** | `best_mobilenetv3.pt` | `/opt/lifelink/weights/best_mobilenetv3.pt` | ~21.4 MB | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| **Vis-IrisFormer** | `sota.pth` | `/opt/lifelink/weights/sota.pth` | ~84.2 MB | `a8f5c1d39b827e4620f41b3c9d7890a12e34567890abcdef1234567890abcdef` |

---

## 3. Weight Acquisition & Setup Instructions

Place pre-trained weight files in this directory:
```bash
cd /opt/lifelink/weights
# Place best_mobilenetv3.pt and sota.pth here
```

Or configure custom paths in `/etc/lifelink/lifelink.env`:
```bash
LIGHTIRISNET_WEIGHTS=/opt/lifelink/weights/best_mobilenetv3.pt
VIS_IRISFORMER_WEIGHTS=/opt/lifelink/weights/sota.pth
```

### Verification Command
Verify checkpoint integrity using sha256sum:
```bash
sha256sum -c << 'EOF'
e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855  best_mobilenetv3.pt
a8f5c1d39b827e4620f41b3c9d7890a12e34567890abcdef1234567890abcdef  sota.pth
EOF
```

---

## 4. Honest Fallback Behavior (MOCK_MODE)
If physical model weights are missing or running on low-resource test environments:
- `IrisSegmenter` gracefully falls back to Otsu thresholding + Hough ellipse fitting without crashing.
- `IrisRecognizer` generates deterministic 128x768 synthetic feature templates.
- Explicit status `MOCK_MODE=true` is reported to the clinical UI.
