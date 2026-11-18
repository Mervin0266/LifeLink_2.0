"""
LifeLink 2.0 - Iris Model Loading Helpers
Shared, fail-closed checkpoint and source-tree loading for the LightIrisNet
segmenter and the Vis-IrisFormer recognizer.

Checkpoints are loaded with `torch.load(weights_only=True)`, so a checkpoint
cannot execute arbitrary code during unpickling. Only the numpy scalar types
that the upstream Vis-IrisFormer checkpoint stores in its metadata
(`sota_acc`) are allow-listed.
"""

import logging
import sys
from pathlib import Path
from typing import Any, Iterable, Optional

from iris_errors import IrisModelLoadError, IrisModelUnavailableError

logger = logging.getLogger("LifeLink.IrisEngine")


def require_file(path: Path, component: str, what: str) -> Path:
    """Returns the resolved path if it is an existing regular file, else raises MODEL_UNAVAILABLE."""
    path = Path(path)
    if not path.is_file():
        raise IrisModelUnavailableError(f"{component} {what} not found at {path}", [component])
    return path


def add_source_path(source_dir: Path, component: str, package: str) -> None:
    """Appends an upstream model source tree to sys.path after checking it contains `package`.

    The tree is appended (not prepended) so it cannot shadow LifeLink or stdlib modules.
    """
    source_dir = Path(source_dir)
    if not (source_dir / package).is_dir():
        raise IrisModelUnavailableError(
            f"{component} source package '{package}' not found under {source_dir}", [component]
        )
    if str(source_dir) not in sys.path:
        sys.path.append(str(source_dir))


def resolve_device(device: Optional[str]) -> Any:
    import torch

    if device:
        return torch.device(device)
    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


def _numpy_safe_globals() -> list:
    import numpy as np

    allowed = [np.dtype]
    try:
        allowed.append(np._core.multiarray.scalar)  # numpy >= 2
    except AttributeError:  # pragma: no cover - numpy 1.x
        allowed.append(np.core.multiarray.scalar)
    allowed.extend(type(np.dtype(t)) for t in ("float64", "float32", "int64"))
    return allowed


def safe_torch_load(path: Path, component: str) -> Any:
    """Loads a checkpoint with weights_only=True. Any failure is MODEL_LOAD_FAILED."""
    import torch

    safe_globals_ctx = getattr(torch.serialization, "safe_globals", None)
    if safe_globals_ctx is None:
        raise IrisModelLoadError(
            f"{component}: torch {torch.__version__} lacks torch.serialization.safe_globals; "
            "torch>=2.5 is required for safe checkpoint loading",
            [component],
        )
    try:
        with safe_globals_ctx(_numpy_safe_globals()):
            return torch.load(str(path), map_location="cpu", weights_only=True)
    except Exception as exc:
        raise IrisModelLoadError(f"{component} checkpoint at {path} could not be read: {exc}", [component]) from exc


def extract_state_dict(ckpt: Any, keys: Iterable[str], component: str) -> dict:
    """Returns the first nested state dict found under `keys`, or the checkpoint itself."""
    if not isinstance(ckpt, dict):
        raise IrisModelLoadError(f"{component} checkpoint is not a state-dict container", [component])
    for key in keys:
        if isinstance(ckpt.get(key), dict):
            return ckpt[key]
    return ckpt
