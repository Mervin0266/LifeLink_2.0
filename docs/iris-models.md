# Iris Recognition Models — Installation, Behaviour and Limits

**Applies to:** `iris-module/engine/`, `backend/biometrics/service.py`, `backend/config.py`
**Introduced by:** LL-001 fix (synthetic fallback removed, fail-closed model loading)

## 1. What is (and is not) in this repository

The iris pipeline needs two trained checkpoints **and** the upstream model source code.
**None of them are committed to this repository** (the checkpoints are 17 MB and 453 MB;
`models/*.pt`, `models/*.pth`, `models/LightIrisNet/` and `models/Vis-IrisFormer/` are
git-ignored). Without them the iris engine refuses to run; it never substitutes a
geometric segmentation or a random embedding.

| Component | Purpose | Required file / tree | Verified fingerprint |
|---|---|---|---|
| LightIrisNet (MobileNetV3 DeepLabv3+) | Iris + pupil segmentation | `best_mobilenetv3.pt` | SHA-256 `71119c33a8a95a83ff6315260cda62eed5a26ad97c7b3934630d7579a32e27f1`, 17,198,226 bytes, keys `epoch/state_dict/val`, 420 tensors |
| LightIrisNet source | Defines `irisseg._train_impl.IrisNetDeepLab`, `irisseg._test_impl` post-processing | directory containing `irisseg/` (upstream `LightIrisNet/src`), MIT licence | — |
| Vis-IrisFormer (MAE ViT, RoPE2D) | 128 × 768 patch embeddings | `sota.pth` | SHA-256 `6b6f710cfce20f7180e4d5e909e1ff9321748485172f23ce0fe708f2cd7c98db`, 453,409,206 bytes, keys `epoch (161)/mae_model/sota_acc` |
| Vis-IrisFormer source | Defines `model.Transformers.VIT.mae.MAEVisionTransformers` | upstream repository root (contains `model/`) | — |

Python dependencies (in `requirements.txt`): `torch>=2.5`, `torchvision`, `tqdm`
(imported by LightIrisNet) and `timm` (imported by Vis-IrisFormer).

Provenance: obtain the checkpoints from the upstream authors' releases
(LightIrisNet: https://github.com/naveengv7/LightIrisNet ; Vis-IrisFormer: the release
linked from its README) or from your organisation's controlled model store, and verify
the SHA-256 values above before use. Do not use an unverified or differently trained
checkpoint: the loader checks architecture compatibility, not training provenance.

## 2. Configuration

All settings are read once at backend start-up (`backend/config.py`). Relative values are
resolved against the repository root; absolute paths and `~` are accepted.

| Variable | Default | Meaning |
|---|---|---|
| `IRIS_MODEL_DIR` | `models` | Base directory for the defaults below |
| `LIGHTIRISNET_WEIGHTS` | `$IRIS_MODEL_DIR/best_mobilenetv3.pt` | Segmentation checkpoint |
| `VIS_IRISFORMER_WEIGHTS` | `$IRIS_MODEL_DIR/sota.pth` | Recognition checkpoint |
| `LIGHTIRISNET_SRC` | `$IRIS_MODEL_DIR/LightIrisNet/src` | Directory that contains `irisseg/` |
| `VIS_IRISFORMER_SRC` | `$IRIS_MODEL_DIR/Vis-IrisFormer` | Directory that contains `model/` |
| `IRIS_INFERENCE_DEVICE` | *(auto: cuda if available, else cpu)* | Torch device |

Default layout:

```
models/
├── best_mobilenetv3.pt
├── sota.pth
├── LightIrisNet/src/irisseg/...
└── Vis-IrisFormer/model/Transformers/VIT/mae.py ...
```

Check the installation with `python scripts/bootstrap.py` (step 3 lists every missing
item and, when all are present, actually loads both models). After installing or fixing
models, **restart the backend**: the loaded pipeline and any load error are cached per
process.

## 3. Loading behaviour (fail-closed)

| Condition | Error type | HTTP |
|---|---|---|
| Checkpoint file missing, source tree missing, torch/timm/tqdm not importable | `MODEL_UNAVAILABLE` | 503 |
| Checkpoint unreadable/corrupt, not a state dict, or key mismatch with the architecture | `MODEL_LOAD_FAILED` | 503 |
| Forward pass raises or returns non-finite values | `MODEL_INFERENCE_FAILED` | 500 |
| Probe is not a decodable JPEG/PNG, empty, uniform, < 64 px, wrong channels | `INVALID_IRIS_IMAGE` | 400 (`/identify`, `/verify`), 422 retry (capture) |
| No plausible iris/pupil boundary found, degenerate normalized strip | `SEGMENTATION_FAILED` | 422 |
| Embedding wrong shape, NaN/Inf, or zero-norm patch | `EMBEDDING_INVALID` | 500 |
| Valid probe, no enrolled template scores ≥ threshold | `NO_MATCH` (outcome) | 200 |

* Checkpoints are loaded with `torch.load(weights_only=True)`; only the numpy scalar types
  stored in `sota.pth` metadata are allow-listed. A checkpoint cannot execute code.
* LightIrisNet loads with `strict=True`. Vis-IrisFormer loads every tensor except the
  fine-tuning classifier head (`ft_head.*`), which upstream also discards; any other
  missing or unexpected key is `MODEL_LOAD_FAILED`.
* Error responses use the existing API shape
  `{"status": "error", "error_type": ..., "message": ..., "components": [...]}`. Messages
  name the affected model but never include filesystem paths; the detailed cause is
  logged server-side (`LifeLink.Biometrics`, `LifeLink.DevicesRoute`). Every failed
  `/identify` and `/verify` iris attempt is audited with its error type.
* `GET /api/v1/devices/health` reports `iris_engine.state` = `not_loaded` | `ready` |
  `unavailable` (with `error_type`) without triggering a model load.
* The kiosk stops its automatic rescan loop on `MODEL_*`/`EMBEDDING_INVALID` errors and
  shows "Iris recognition unavailable" instead of "no match".
* `MOCK_MODE` only replaces the camera; it does **not** enable any synthetic recognition.

## 4. Pipeline contract (derived from the upstream code)

1. Decode JPEG/PNG with OpenCV, convert **BGR → RGB**.
2. LightIrisNet (mirrors `irisseg._test_impl.predict` and the README inference flags):
   RGB / 255, ImageNet mean/std, native resolution (edge-padded to a multiple of 32,
   output cropped back), sigmoid > 0.5, soft pupil containment (inside 0.85, keep 0.90),
   largest connected component, ellipse refit (≥ 20 contour points). Geometric sanity
   gates (iris ≥ 2 % of frame, pupil ≥ 0.3 %, pupil/iris area 0.05–0.80, pupil ≥ 85 %
   inside iris) reject frames with no plausible eye — they are not calibrated quality metrics.
3. Daugman rubber-sheet normalization to a 64 × 512 grey strip (`normalizer.py`).
4. Vis-IrisFormer (mirrors upstream `test.py`, `ft_pool="map"`): strip / 255 replicated to
   3 channels, `Encoder.autoencoder(x, train=False, mask_index=None)[0]` → (128, 768).
5. Similarity: mean over the 128 patches of the per-patch cosine similarity
   (identical to upstream evaluation), range −1…1.

Stored iris data remains the **encrypted enrollment JPEG**; embeddings are recomputed
with the same pipeline for probe and gallery at match time, so enrollment and
identification always use the same model version. A gallery entry that is not a
decodable image (for example the fake 393,216-byte "embeddings" written by
`scripts/seed_demo.py`) or in which no iris is found is skipped with a warning; a
model/system failure aborts the whole identification.

## 5. Known limitations (read before any clinical use)

1. **The decision threshold is not calibrated for this model.** `IRIS_VERIFY_THRESHOLD`
   is 0.80. Measured with the real checkpoints on non-iris inputs, unrelated random-noise
   strips score ≈ 0.89 and unrelated synthetic iris-like textures score 0.93–0.96 against
   each other — i.e. *above* 0.80. The mean patch-cosine of this model has a high
   baseline, so 0.80 is very likely to accept impostors once real eyes are enrolled.
   Upstream reports a validation EER of 0.0657 for the checkpoint (`sota_acc`) on its
   own protocol; no genuine/impostor distribution for LifeLink's camera exists. A
   threshold (and the INCONCLUSIVE margin) must be calibrated on consented captures from
   the deployed camera before iris identification is relied upon.
2. **Spectral domain mismatch.** Both models were trained on visible-light datasets
   (UBIRIS.v2, MICHE). The LifeLink camera is an IMX708 NoIR with 850 nm illumination.
   Segmentation and recognition accuracy on NIR captures is unverified.
3. **No real-eye validation has been performed.** The repository contains no consented
   iris images; the mock camera's synthetic eye is (correctly) rejected by the trained
   segmenter, so the full enroll → identify path with genuine models has not been run.
4. **Cost.** Every identification re-runs segmentation + recognition for every enrolled
   iris image (~0.1 s recognition + segmentation per entry on x86 CPU; slower on a Pi 5).

## 6. Tests

```bash
# Model-independent tests (always run): path resolution, fail-closed loading,
# no-synthetic-fallback guards, image validation, similarity, API mapping.
pytest tests/unit/test_iris_engine.py -v

# With genuine models: set the variables from section 2, then the same command also
# runs the real-model tests (load, key coverage, upstream preprocessing equivalence,
# continuity, non-eye rejection, corrupt/incompatible/malicious checkpoint handling).

# With consented eye images (rank-1 check, no threshold claim):
LIFELINK_IRIS_EVAL_DIR=/path/to/<subject>/<capture>.jpg pytest tests/unit/test_iris_engine.py -k test_g -v
```

Skipped tests report `BLOCKED: …` with the missing prerequisite. Tests requiring physical
hardware (camera node, IR LED) are in `iris-module/camera-client/tests` and
`lifelink_hardware_diagnostic.py`; they do not exercise recognition accuracy.
