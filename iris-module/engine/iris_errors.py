"""
LifeLink 2.0 - Iris Engine Error Types
Explicit, typed failures for the iris recognition pipeline. The engine never
substitutes synthetic segmentation or embeddings: every stage either produces
a genuine model output or raises one of these errors.

This module has no third-party imports so the backend can import it (and map
errors to HTTP responses) even when PyTorch itself is missing.

`str(error)` carries the internal detail (may include filesystem paths) and is
for server logs only. `public_message` is safe to return to API clients.
"""

from typing import Any, Dict, Optional, Sequence


class IrisEngineError(Exception):
    """Base class for all iris engine failures."""

    code = "IRIS_ENGINE_ERROR"
    http_status = 500
    public_message = "Iris recognition failed."

    def __init__(self, detail: str, components: Optional[Sequence[str]] = None):
        super().__init__(detail)
        self.components = list(components or [])

    def public_dict(self) -> Dict[str, Any]:
        """Client-safe description: error code, message and affected model names only."""
        message = self.public_message
        if self.components:
            message = f"{message} Affected: {', '.join(self.components)}."
        return {"error_type": self.code, "message": message, "components": self.components}


class IrisModelUnavailableError(IrisEngineError):
    """A required checkpoint, model source tree or dependency is not installed."""

    code = "MODEL_UNAVAILABLE"
    http_status = 503
    public_message = (
        "Iris recognition is unavailable because the required model weights "
        "could not be loaded."
    )


class IrisModelLoadError(IrisEngineError):
    """A checkpoint exists but is corrupt or incompatible with the architecture."""

    code = "MODEL_LOAD_FAILED"
    http_status = 503
    public_message = (
        "Iris recognition is unavailable because a model checkpoint failed to load "
        "or is incompatible."
    )


class IrisInferenceError(IrisEngineError):
    """The model raised during a forward pass."""

    code = "MODEL_INFERENCE_FAILED"
    http_status = 500
    public_message = "Iris model inference failed."


class InvalidIrisImageError(IrisEngineError):
    """The supplied data is not a usable eye image (undecodable, empty, wrong shape)."""

    code = "INVALID_IRIS_IMAGE"
    http_status = 400
    public_message = "The supplied iris image is invalid or could not be decoded."


class IrisSegmentationError(IrisEngineError):
    """Segmentation ran but did not find a plausible iris/pupil (capture a new frame)."""

    code = "SEGMENTATION_FAILED"
    http_status = 422
    public_message = "Iris and pupil boundaries could not be located in the image."


class IrisEmbeddingError(IrisEngineError):
    """An embedding has the wrong shape or contains non-finite or zero vectors."""

    code = "EMBEDDING_INVALID"
    http_status = 500
    public_message = "The iris feature embedding was invalid."


# Errors that describe a system condition (not the specific image). When one of
# these occurs, identification must abort instead of skipping a gallery entry.
SYSTEM_ERRORS = (IrisModelUnavailableError, IrisModelLoadError, IrisInferenceError)

# Errors caused by the captured frame itself; the camera may retry with a new frame.
RETRYABLE_CAPTURE_ERRORS = (InvalidIrisImageError, IrisSegmentationError)
