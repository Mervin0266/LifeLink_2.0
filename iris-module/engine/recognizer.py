"""
LifeLink 2.0 - Vis-IrisFormer Recognizer Wrapper
Extracts 128 patch token embeddings x 768 dimensions from normalized 64x512 iris strips
using the VIS-IrisFormer Vision Transformer (MAE + RoPE2D).
Computes patch-wise cosine similarity for template matching.

Fail-closed: a missing checkpoint, source tree or dependency raises
IrisModelUnavailableError; an incompatible checkpoint raises IrisModelLoadError.
No synthetic embedding is ever produced.

Preprocessing, feature selection and similarity follow upstream Vis-IrisFormer
`test.py` with ft_pool="map": the 64x512 strip scaled to [0, 1] as 3 identical
channels, `Encoder.autoencoder(x, train=False, mask_index=None)[0]` as the
(128, 768) patch sequence, and the mean over patches of the per-patch cosine
similarity as the score.
"""

from pathlib import Path
from typing import Optional

import numpy as np

from backend.config import Config
from iris_errors import IrisEmbeddingError, IrisInferenceError, InvalidIrisImageError, IrisModelLoadError, IrisModelUnavailableError
from iris_model_loading import add_source_path, extract_state_dict, require_file, resolve_device, safe_torch_load

COMPONENT = "Vis-IrisFormer"
EMBEDDING_SHAPE = (128, 768)
STRIP_SHAPE = (64, 512)
_MIN_PATCH_NORM = 1e-6


def validate_embedding(embedding: np.ndarray, label: str = "embedding") -> np.ndarray:
    """Returns the embedding as float32 (128, 768) or raises IrisEmbeddingError."""
    if not isinstance(embedding, np.ndarray):
        raise IrisEmbeddingError(f"{label} is not a numpy array ({type(embedding).__name__})")
    if embedding.shape != EMBEDDING_SHAPE:
        raise IrisEmbeddingError(f"{label} has shape {embedding.shape}, expected {EMBEDDING_SHAPE}")
    emb = embedding.astype(np.float32, copy=False)
    if not np.isfinite(emb).all():
        raise IrisEmbeddingError(f"{label} contains NaN or infinite values")
    if (np.linalg.norm(emb, axis=1) < _MIN_PATCH_NORM).any():
        raise IrisEmbeddingError(f"{label} contains zero-norm patch vectors")
    return emb


class IrisRecognizer:
    """Wrapper for the trained Vis-IrisFormer feature extractor and matcher."""

    MODEL_NAME = "Vis-IrisFormer"

    def __init__(self, checkpoint_path: Optional[str] = None, device: Optional[str] = None,
                 source_dir: Optional[str] = None):
        self.checkpoint_path = Path(checkpoint_path or Config.VIS_IRISFORMER_WEIGHTS)
        self.source_dir = Path(source_dir or Config.VIS_IRISFORMER_SRC)
        self.model = None
        self.checkpoint_epoch = None
        self._load_model(device or Config.IRIS_INFERENCE_DEVICE)

    @property
    def model_version(self) -> str:
        epoch = f"-epoch{self.checkpoint_epoch}" if self.checkpoint_epoch is not None else ""
        return f"{self.MODEL_NAME}:{self.checkpoint_path.name}{epoch}"

    def _load_model(self, device: Optional[str]) -> None:
        require_file(self.checkpoint_path, COMPONENT, "checkpoint")
        add_source_path(self.source_dir, COMPONENT, "model")
        try:
            import torch  # noqa: F401
            from model.Transformers.VIT.mae import MAEVisionTransformers as MAE  # type: ignore
        except ImportError as exc:
            raise IrisModelUnavailableError(f"{COMPONENT} model code could not be imported: {exc}", [COMPONENT]) from exc

        self.device = resolve_device(device)
        # Hyper-parameters must mirror the configuration sota.pth was trained with.
        model = MAE(
            img_size=STRIP_SHAPE,
            patch_size=(16, 16),
            encoder_dim=768,
            encoder_depth=12,
            encoder_heads=12,
            decoder_dim=512,
            decoder_depth=8,
            decoder_heads=16,
            mask_ratio=0.75,
            num_classes=1,
            ft_pool="map",
            pos_embed="rope2d",
            bottleneck=False,
            bottleneck_dim=512,
        )
        ckpt = safe_torch_load(self.checkpoint_path, COMPONENT)
        state_dict = extract_state_dict(ckpt, ("mae_model", "model"), COMPONENT)
        if isinstance(ckpt, dict):
            self.checkpoint_epoch = ckpt.get("epoch")

        # Upstream drops the fine-tuning classifier head ('ft_*'), which is not
        # used for embeddings. Everything else must load exactly.
        filtered = {k: v for k, v in state_dict.items() if "ft" not in k}
        try:
            result = model.load_state_dict(filtered, strict=False)
        except Exception as exc:
            raise IrisModelLoadError(f"{COMPONENT} checkpoint is incompatible: {exc}", [COMPONENT]) from exc
        unexpected = list(result.unexpected_keys)
        missing = [k for k in result.missing_keys if not k.startswith("ft_")]
        if unexpected or missing:
            raise IrisModelLoadError(
                f"{COMPONENT} checkpoint key mismatch: missing={missing[:5]} "
                f"({len(missing)}), unexpected={unexpected[:5]} ({len(unexpected)})",
                [COMPONENT],
            )
        model.to(self.device)
        model.eval()
        self.model = model

    def extract_features(self, normalized_iris: np.ndarray) -> np.ndarray:
        """
        Extracts 128 patch token embeddings x 768 dimensions from a (64, 512) uint8 strip.
        Returns a validated numpy array of shape (128, 768) float32. Raises on failure.
        """
        import torch

        if not isinstance(normalized_iris, np.ndarray) or normalized_iris.shape != STRIP_SHAPE:
            shape = getattr(normalized_iris, "shape", None)
            raise InvalidIrisImageError(f"Normalized iris strip has shape {shape}, expected {STRIP_SHAPE}")
        if normalized_iris.dtype != np.uint8:
            raise InvalidIrisImageError(f"Normalized iris strip dtype {normalized_iris.dtype}, expected uint8")

        img = normalized_iris.astype(np.float32) / 255.0
        img = np.stack([img, img, img], axis=0)
        tensor = torch.from_numpy(img).unsqueeze(0).to(self.device)
        try:
            with torch.inference_mode():
                norm_embedding, _, _, _, _ = self.model.Encoder.autoencoder(tensor, train=False, mask_index=None)
                feature = norm_embedding[0].float().cpu().numpy()
        except Exception as exc:
            raise IrisInferenceError(f"{COMPONENT} forward pass failed: {exc}", [COMPONENT]) from exc
        return validate_embedding(feature, f"{COMPONENT} output")

    @staticmethod
    def compare(template_a: np.ndarray, template_b: np.ndarray) -> float:
        """
        Computes patch-wise cosine similarity between two validated (128, 768) templates.
        Returns the mean over patches, in [-1.0, 1.0], rounded to 4 dp.
        Raises IrisEmbeddingError for malformed, non-finite or zero-vector input.
        """
        a = validate_embedding(template_a, "probe embedding").astype(np.float64)
        b = validate_embedding(template_b, "enrolled embedding").astype(np.float64)
        cos = np.sum(a * b, axis=1) / (np.linalg.norm(a, axis=1) * np.linalg.norm(b, axis=1))
        score = float(np.clip(np.mean(cos), -1.0, 1.0))
        return round(score, 4)
