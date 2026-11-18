"""
LifeLink 2.0 - Biometric Service & Fusion Engine
Implements:
  - 1:1 Fingerprint verification against enrolled patient templates.
  - 1:1 Iris verification against enrolled patient templates.
  - 1:N Candidate identification search with explicit calibrated ambiguity handling:
    MATCH, INCONCLUSIVE, NO_MATCH, or CAPTURE_FAILED.
  - Cross-modal fusion: Uses second biometric or record verification for candidate confirmation.
"""

import base64
import logging
import sys
import threading
import time
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from backend.config import Config
from backend.database.connection import Database
from backend.database.crypto import TemplateCrypto
from backend.devices.manager import DeviceManager


def _ensure_engine_path() -> None:
    """Puts iris-module/engine (bare-name modules) on sys.path."""
    candidates = [
        Config.BASE_DIR / "iris-module" / "engine",
        Config.BASE_DIR / "iris-engine",
        Path("/opt/lifelink/iris-engine"),
        Path(__file__).resolve().parent.parent.parent / "iris-module" / "engine",
        Path(__file__).resolve().parent.parent / "iris-engine",
    ]
    for c in candidates:
        if c.exists() and str(c) not in sys.path:
            sys.path.insert(0, str(c))


_ensure_engine_path()
# iris_errors has no third-party imports, so error mapping works even without torch.
from iris_errors import (  # type: ignore  # noqa: E402
    IrisEngineError,
    IrisModelUnavailableError,
    InvalidIrisImageError,
    SYSTEM_ERRORS,
)

logger = logging.getLogger("LifeLink.Biometrics")
crypto = TemplateCrypto()


class BiometricService:
    """Orchestrates fingerprint and iris comparison, candidate search, and fusion."""

    # Baseline operating thresholds (subject to empirical calibration)
    FINGERPRINT_VERIFY_THRESHOLD = 0.50
    IRIS_VERIFY_THRESHOLD = 0.80  # Baseline cosine threshold
    IRIS_AMBIGUITY_MARGIN = 0.05   # Score difference required to avoid INCONCLUSIVE state

    # One trained iris pipeline per process (loading both checkpoints is expensive).
    # A load failure is cached too: install or fix the models, then restart the backend.
    _iris_pipeline = None
    _iris_pipeline_error: Optional[IrisEngineError] = None
    _iris_pipeline_lock = threading.Lock()

    @classmethod
    def verify_fingerprint_1_to_1(cls, patient_id: str, probe_template_b64: str) -> Dict[str, Any]:
        """
        Verifies a live fingerprint scan against a known patient's enrolled fingers.
        Decrypts stored templates and executes on-sensor / mock 1:1 comparison.
        """
        probe_bytes = base64.b64decode(probe_template_b64)
        manager = DeviceManager()

        query = "SELECT finger_position, encrypted_template FROM fingerprint_templates WHERE patient_id = ?;"
        enrolled_fingers = Database.execute_query(query, (patient_id,))

        if not enrolled_fingers:
            return {
                "matched": False,
                "confidence": 0.0,
                "best_finger": None,
                "status": "NO_ENROLLED_TEMPLATES",
                "message": f"Patient {patient_id} has no enrolled fingerprints."
            }

        best_score = 0.0
        best_finger = None
        matched = False

        for row in enrolled_fingers:
            enc_bytes = row["encrypted_template"]
            raw_enrolled = crypto.decrypt(enc_bytes)
            # Run 1:1 comparison
            is_match, score = manager.fingerprint.verify_1_to_1("synthetic_probe", raw_enrolled)
            if score > best_score:
                best_score = score
                best_finger = row["finger_position"]
            if is_match or score >= cls.FINGERPRINT_VERIFY_THRESHOLD:
                matched = True

        return {
            "matched": matched,
            "confidence": round(best_score, 4),
            "best_finger": best_finger,
            "status": "MATCH" if matched else "NO_MATCH",
            "message": "Fingerprint verified" if matched else "Fingerprint does not match patient record"
        }

    @classmethod
    def verify_iris_1_to_1(cls, patient_id: str, probe_embedding_b64: str, eye_side: str = "OD") -> Dict[str, Any]:
        """
        Verifies a live iris scan against a known patient's enrolled iris templates.
        """
        probe_bytes = base64.b64decode(probe_embedding_b64)
        query = "SELECT eye_side, encrypted_template FROM iris_templates WHERE patient_id = ?;"
        enrolled_irises = Database.execute_query(query, (patient_id,))

        if not enrolled_irises:
            return {
                "matched": False,
                "confidence": 0.0,
                "eye_side": eye_side,
                "status": "NO_ENROLLED_TEMPLATES",
                "message": f"Patient {patient_id} has no enrolled iris templates."
            }

        best_score = 0.0
        best_eye = None

        # Raises IrisEngineError (model unavailable, invalid probe, ...): never a silent NO_MATCH.
        probe_embedding = cls._resolve_iris_embedding(probe_bytes)
        for row in enrolled_irises:
            enrolled_embedding = cls._enrolled_iris_embedding(
                crypto.decrypt(row["encrypted_template"]), patient_id, row["eye_side"]
            )
            if enrolled_embedding is None:
                continue
            sim = cls._iris_similarity(probe_embedding, enrolled_embedding)
            if sim > best_score:
                best_score = sim
                best_eye = row["eye_side"]

        matched = best_score >= cls.IRIS_VERIFY_THRESHOLD
        return {
            "matched": matched,
            "confidence": round(best_score, 4),
            "best_eye": best_eye,
            "status": "MATCH" if matched else "NO_MATCH",
            "message": "Iris pattern verified" if matched else "Iris pattern does not match patient record"
        }

    @classmethod
    def identify_1_to_n(cls, biometric_type: str, probe_b64: str) -> Dict[str, Any]:
        """
        Executes 1:N identification search against all enrolled patient records in the database.
        Returns top candidates with honest confidence ratings and ambiguity detection.
        """
        probe_bytes = base64.b64decode(probe_b64)
        candidates: List[Dict[str, Any]] = []

        if biometric_type == "fingerprint":
            query = """
            SELECT f.patient_id, f.finger_position, f.encrypted_template, p.lifelink_id, p.full_name, p.dob, p.status
            FROM fingerprint_templates f
            JOIN patients_cache p ON f.patient_id = p.id
            WHERE p.status = 'active';
            """
            rows = Database.execute_query(query)
            manager = DeviceManager()
            for r in rows:
                raw_enrolled = crypto.decrypt(r["encrypted_template"])
                _, score = manager.fingerprint.verify_1_to_1(probe_bytes, raw_enrolled)
                if score >= 0.30:  # Candidate shortlist threshold
                    candidates.append({
                        "patient_id": r["patient_id"],
                        "lifelink_id": r["lifelink_id"],
                        "full_name": r["full_name"],
                        "dob": r["dob"],
                        "match_type": "fingerprint",
                        "feature_position": r["finger_position"],
                        "score": round(score, 4)
                    })

        elif biometric_type == "iris":
            query = """
            SELECT i.patient_id, i.eye_side, i.encrypted_template, p.lifelink_id, p.full_name, p.dob, p.status
            FROM iris_templates i
            JOIN patients_cache p ON i.patient_id = p.id
            WHERE p.status = 'active';
            """
            rows = Database.execute_query(query)
            # Raises IrisEngineError (model unavailable, invalid probe, ...): never a silent NO_MATCH.
            probe_embedding = cls._resolve_iris_embedding(probe_bytes)
            for r in rows:
                enrolled_embedding = cls._enrolled_iris_embedding(
                    crypto.decrypt(r["encrypted_template"]), r["patient_id"], r["eye_side"]
                )
                if enrolled_embedding is None:
                    continue
                score = cls._iris_similarity(probe_embedding, enrolled_embedding)
                if score >= 0.50:  # Candidate shortlist threshold
                    candidates.append({
                        "patient_id": r["patient_id"],
                        "lifelink_id": r["lifelink_id"],
                        "full_name": r["full_name"],
                        "dob": r["dob"],
                        "match_type": "iris",
                        "feature_position": r["eye_side"],
                        "score": round(score, 4)
                    })

        # Sort candidates descending by score
        candidates.sort(key=lambda x: x["score"], reverse=True)

        if not candidates:
            return {
                "outcome": "NO_MATCH",
                "message": "No matching patient candidate found in local database",
                "candidates": []
            }

        top_candidate = candidates[0]
        # Ambiguity check: if top 2 candidates are very close in score
        if len(candidates) > 1:
            margin = top_candidate["score"] - candidates[1]["score"]
            if margin < cls.IRIS_AMBIGUITY_MARGIN and top_candidate["score"] >= cls.IRIS_VERIFY_THRESHOLD:
                return {
                    "outcome": "INCONCLUSIVE",
                    "message": "Multiple patient candidates identified with similar confidence scores. Secondary confirmation required.",
                    "candidates": candidates[:3]
                }

        threshold = cls.FINGERPRINT_VERIFY_THRESHOLD if biometric_type == "fingerprint" else cls.IRIS_VERIFY_THRESHOLD
        if top_candidate["score"] >= threshold:
            return {
                "outcome": "MATCH",
                "message": f"Candidate identified: {top_candidate['full_name']} ({top_candidate['lifelink_id']})",
                "candidates": [top_candidate]
            }
        else:
            return {
                "outcome": "NO_MATCH",
                "message": "Nearest candidate confidence below decision threshold",
                "candidates": candidates[:3]
            }

    @classmethod
    def _get_iris_pipeline(cls):
        """Returns the process-wide trained IrisPipelineService, or raises IrisEngineError."""
        if cls._iris_pipeline is not None:
            return cls._iris_pipeline
        with cls._iris_pipeline_lock:
            if cls._iris_pipeline is not None:
                return cls._iris_pipeline
            if cls._iris_pipeline_error is not None:
                raise cls._iris_pipeline_error
            try:
                try:
                    from service import IrisPipelineService  # type: ignore
                except ImportError as exc:
                    raise IrisModelUnavailableError(
                        f"Iris engine dependencies could not be imported: {exc}", ["iris-engine"]
                    ) from exc
                cls._iris_pipeline = IrisPipelineService()
                logger.info("[IRIS ENGINE] Models loaded: %s", cls._iris_pipeline.model_version)
            except IrisEngineError as exc:
                logger.error("[IRIS ENGINE] %s: %s", exc.code, exc)
                cls._iris_pipeline_error = exc
                raise
            return cls._iris_pipeline

    @classmethod
    def _reset_iris_pipeline(cls) -> None:
        """Drops the cached pipeline and cached load error (tests / operator reload)."""
        with cls._iris_pipeline_lock:
            cls._iris_pipeline = None
            cls._iris_pipeline_error = None

    @classmethod
    def iris_engine_status(cls) -> Dict[str, Any]:
        """Non-loading status snapshot for health reporting (no filesystem paths)."""
        if cls._iris_pipeline is not None:
            return {"state": "ready", "model_version": cls._iris_pipeline.model_version}
        if cls._iris_pipeline_error is not None:
            return {"state": "unavailable", **cls._iris_pipeline_error.public_dict()}
        return {"state": "not_loaded"}

    @classmethod
    def iris_model_version(cls) -> str:
        return cls._get_iris_pipeline().model_version

    @classmethod
    def _compare_iris_templates(cls, probe_bytes: bytes, enrolled_bytes: bytes) -> float:
        """
        Compares two encoded eye images (JPEG/PNG) with the trained iris pipeline.
        Raises IrisEngineError if either image cannot be processed or the models are unavailable.
        """
        return cls._iris_similarity(
            cls._resolve_iris_embedding(probe_bytes), cls._resolve_iris_embedding(enrolled_bytes)
        )

    @classmethod
    def _iris_similarity(cls, emb_a, emb_b) -> float:
        from recognizer import IrisRecognizer  # type: ignore
        return IrisRecognizer.compare(emb_a, emb_b)

    @classmethod
    def _enrolled_iris_embedding(cls, raw_enrolled: bytes, patient_id: str, eye_side: str):
        """
        Embedding for one gallery entry. Per-image failures (undecodable data, no iris found)
        skip that entry with a warning; system failures (models unavailable, inference error)
        propagate so identification aborts instead of returning a misleading NO_MATCH.
        """
        try:
            return cls._resolve_iris_embedding(raw_enrolled)
        except SYSTEM_ERRORS:
            raise
        except IrisEngineError as exc:
            logger.warning(
                "[IRIS MATCH] Skipping enrolled iris (patient=%s, eye=%s): %s %s",
                patient_id, eye_side, exc.code, exc,
            )
            return None

    @classmethod
    def _resolve_iris_embedding(cls, data_bytes: bytes):
        """
        Decodes an encoded eye image (JPEG/PNG) and runs the trained pipeline.
        Returns a validated (128, 768) float32 embedding. Raises IrisEngineError on any failure.
        Raw embedding buffers are not accepted: every template must come from model inference.
        """
        if not data_bytes:
            raise InvalidIrisImageError("Empty iris image data")
        if not (data_bytes.startswith(b"\xff\xd8") or data_bytes.startswith(b"\x89PNG")):
            raise InvalidIrisImageError("Iris data is not a JPEG or PNG image")
        import cv2
        import numpy as np
        img = cv2.imdecode(np.frombuffer(data_bytes, np.uint8), cv2.IMREAD_COLOR)
        if img is None or img.size == 0:
            raise InvalidIrisImageError("Iris image could not be decoded")
        pipeline = cls._get_iris_pipeline()
        # OpenCV decodes BGR; the pipeline (LightIrisNet was trained on RGB) expects RGB.
        res = pipeline.process_eye_image(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
        return res["embedding"]
