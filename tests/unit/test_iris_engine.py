"""
Unit and regression tests for the LifeLink 2.0 iris recognition pipeline (LL-001).

Sections follow the LL-001 fix plan:
  A  model path resolution          E  image processing / validation
  B  missing model weights          F  similarity (controlled vectors)
  C  genuine model loading          G  enrollment/identification with real eye images
  D  no synthetic embeddings        H  backend API behaviour

Tests that need the genuine checkpoints and upstream model code are skipped with
a "BLOCKED" reason unless they are configured (see docs/iris-models.md). Section G
additionally needs consented eye images in LIFELINK_IRIS_EVAL_DIR. Nothing here
substitutes random weights or synthetic embeddings for the real models.

Test doubles (stub pipelines/models) are used only to exercise error handling and
decision logic; they are local to the test that uses them.
"""

import base64
import hashlib
import json
import os
import sys
import uuid
import datetime
from pathlib import Path

import cv2
import numpy as np
import pytest

_ENGINE_DIR = Path(__file__).resolve().parent.parent.parent / "iris-module" / "engine"
if str(_ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(_ENGINE_DIR))

from backend.config import Config, BASE_DIR, _resolve_path_setting  # noqa: E402
from iris_errors import (  # noqa: E402
    IrisEmbeddingError,
    IrisInferenceError,
    IrisModelLoadError,
    IrisModelUnavailableError,
    IrisSegmentationError,
    InvalidIrisImageError,
)
from normalizer import IrisNormalizer  # noqa: E402
from recognizer import IrisRecognizer, validate_embedding  # noqa: E402
from segmenter import IrisSegmenter  # noqa: E402
from service import IrisPipelineService, validate_eye_image  # noqa: E402

try:
    import torch as _torch_probe  # noqa: F401
    HAS_TORCH = True
except ImportError:  # pragma: no cover - environment dependent
    HAS_TORCH = False

HAS_SOURCES = (Config.LIGHTIRISNET_SRC / "irisseg").is_dir() and (Config.VIS_IRISFORMER_SRC / "model").is_dir()
HAS_WEIGHTS = Config.LIGHTIRISNET_WEIGHTS.is_file() and Config.VIS_IRISFORMER_WEIGHTS.is_file()

requires_torch = pytest.mark.skipif(not HAS_TORCH, reason="BLOCKED: PyTorch not installed")
requires_sources = pytest.mark.skipif(
    not (HAS_TORCH and HAS_SOURCES),
    reason="BLOCKED: upstream LightIrisNet / Vis-IrisFormer source trees not configured (docs/iris-models.md)",
)
requires_models = pytest.mark.skipif(
    not (HAS_TORCH and HAS_SOURCES and HAS_WEIGHTS),
    reason="BLOCKED: genuine iris model checkpoints not configured (docs/iris-models.md)",
)

ENGINE_FILES = ["segmenter.py", "recognizer.py", "service.py", "normalizer.py", "iris_model_loading.py"]


@pytest.fixture
def missing_models(tmp_path, monkeypatch):
    """Points both checkpoints at non-existent files and clears the cached pipeline."""
    from backend.biometrics.service import BiometricService
    monkeypatch.setattr(Config, "LIGHTIRISNET_WEIGHTS", tmp_path / "missing_best_mobilenetv3.pt")
    monkeypatch.setattr(Config, "VIS_IRISFORMER_WEIGHTS", tmp_path / "missing_sota.pth")
    BiometricService._reset_iris_pipeline()
    yield
    BiometricService._reset_iris_pipeline()


def _png(rgb: np.ndarray) -> bytes:
    return cv2.imencode(".png", cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))[1].tobytes()


def _pattern(seed: int, h: int = 240, w: int = 320) -> np.ndarray:
    return np.random.RandomState(seed).randint(0, 256, (h, w, 3), dtype=np.uint8)


def _unit_patches(seed: int) -> np.ndarray:
    v = np.random.RandomState(seed).randn(128, 768).astype(np.float32)
    return v / np.linalg.norm(v, axis=1, keepdims=True)


# ---------------------------------------------------------------------------
# A. Model path resolution
# ---------------------------------------------------------------------------
def test_a_relative_env_path_resolves_against_repo_root(monkeypatch):
    monkeypatch.setenv("LL_TEST_IRIS_PATH", "models/custom.pt")
    assert _resolve_path_setting("LL_TEST_IRIS_PATH", Path("/unused")) == (BASE_DIR / "models" / "custom.pt").resolve()


def test_a_absolute_env_path_is_used_verbatim(monkeypatch, tmp_path):
    target = tmp_path / "weights" / "sota.pth"
    monkeypatch.setenv("LL_TEST_IRIS_PATH", str(target))
    assert _resolve_path_setting("LL_TEST_IRIS_PATH", Path("/unused")) == target.resolve()


def test_a_unset_or_blank_env_uses_repo_relative_default(monkeypatch):
    monkeypatch.delenv("LL_TEST_IRIS_PATH", raising=False)
    assert _resolve_path_setting("LL_TEST_IRIS_PATH", Path("models/x.pt")) == (BASE_DIR / "models" / "x.pt").resolve()
    monkeypatch.setenv("LL_TEST_IRIS_PATH", "   ")
    assert _resolve_path_setting("LL_TEST_IRIS_PATH", BASE_DIR / "models" / "x.pt") == (BASE_DIR / "models" / "x.pt").resolve()


def test_a_home_relative_env_path_is_expanded(monkeypatch):
    monkeypatch.setenv("LL_TEST_IRIS_PATH", "~/lifelink-models/sota.pth")
    assert _resolve_path_setting("LL_TEST_IRIS_PATH", Path("/unused")) == (Path.home() / "lifelink-models" / "sota.pth").resolve()


def test_a_config_has_no_machine_specific_model_paths():
    source = (BASE_DIR / "backend" / "config.py").read_text()
    assert "/home/" not in source
    assert "BASE_DIR.parent.parent" not in source
    for attr in ("IRIS_MODEL_DIR", "LIGHTIRISNET_WEIGHTS", "VIS_IRISFORMER_WEIGHTS", "LIGHTIRISNET_SRC", "VIS_IRISFORMER_SRC"):
        assert getattr(Config, attr).is_absolute(), attr


def test_a_missing_path_error_is_actionable(tmp_path):
    missing = tmp_path / "nope.pt"
    with pytest.raises(IrisModelUnavailableError) as exc:
        IrisSegmenter(checkpoint_path=str(missing))
    assert str(missing) in str(exc.value)            # internal log detail names the path
    assert str(missing) not in json.dumps(exc.value.public_dict())  # client payload does not


# ---------------------------------------------------------------------------
# B. Missing model weights / sources
# ---------------------------------------------------------------------------
def test_b_missing_lightirisnet_weights_fail_explicitly(tmp_path):
    with pytest.raises(IrisModelUnavailableError) as exc:
        IrisSegmenter(checkpoint_path=str(tmp_path / "missing.pt"))
    assert exc.value.code == "MODEL_UNAVAILABLE"
    assert exc.value.components == ["LightIrisNet"]


def test_b_missing_visirisformer_weights_fail_explicitly(tmp_path):
    with pytest.raises(IrisModelUnavailableError) as exc:
        IrisRecognizer(checkpoint_path=str(tmp_path / "missing.pth"))
    assert exc.value.code == "MODEL_UNAVAILABLE"
    assert exc.value.components == ["Vis-IrisFormer"]


def test_b_missing_model_source_tree_fails_explicitly(tmp_path):
    ckpt = tmp_path / "present.pt"
    ckpt.write_bytes(b"not used")
    with pytest.raises(IrisModelUnavailableError, match="source package 'irisseg'"):
        IrisSegmenter(checkpoint_path=str(ckpt), source_dir=str(tmp_path / "no_src"))
    with pytest.raises(IrisModelUnavailableError, match="source package 'model'"):
        IrisRecognizer(checkpoint_path=str(ckpt), source_dir=str(tmp_path / "no_src"))


def test_b_pipeline_reports_every_missing_model(missing_models):
    with pytest.raises(IrisModelUnavailableError) as exc:
        IrisPipelineService()
    assert exc.value.components == ["LightIrisNet", "Vis-IrisFormer"]


def test_b_pipeline_refuses_to_run_with_only_one_model(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "LIGHTIRISNET_WEIGHTS", tmp_path / "missing.pt")
    with pytest.raises(IrisModelUnavailableError) as exc:
        IrisPipelineService()
    assert "LightIrisNet" in exc.value.components


@requires_sources
def test_b_corrupt_lightirisnet_checkpoint_is_load_failure(tmp_path):
    bad = tmp_path / "corrupt.pt"
    bad.write_bytes(os.urandom(4096))
    with pytest.raises(IrisModelLoadError) as exc:
        IrisSegmenter(checkpoint_path=str(bad))
    assert exc.value.code == "MODEL_LOAD_FAILED"


@requires_sources
def test_b_incompatible_lightirisnet_checkpoint_is_load_failure(tmp_path):
    import torch
    bad = tmp_path / "incompatible.pt"
    torch.save({"state_dict": {"not_a_layer.weight": torch.zeros(3)}}, str(bad))
    with pytest.raises(IrisModelLoadError, match="incompatible"):
        IrisSegmenter(checkpoint_path=str(bad))


@requires_sources
def test_b_corrupt_and_incompatible_visirisformer_checkpoints_are_load_failures(tmp_path):
    import torch
    bad = tmp_path / "corrupt.pth"
    bad.write_bytes(os.urandom(4096))
    with pytest.raises(IrisModelLoadError):
        IrisRecognizer(checkpoint_path=str(bad))
    partial = tmp_path / "partial.pth"
    torch.save({"mae_model": {"Encoder.cls_token": torch.zeros(1, 1, 768)}}, str(partial))
    with pytest.raises(IrisModelLoadError, match="key mismatch"):
        IrisRecognizer(checkpoint_path=str(partial))


@requires_sources
def test_b_checkpoint_with_executable_pickle_is_rejected(tmp_path):
    """weights_only loading: a checkpoint cannot run code during unpickling."""
    import torch

    class Payload:
        def __reduce__(self):
            return (os.system, ("echo should-not-run",))

    bad = tmp_path / "malicious.pt"
    torch.save({"state_dict": Payload()}, str(bad))
    with pytest.raises(IrisModelLoadError):
        IrisSegmenter(checkpoint_path=str(bad))


# ---------------------------------------------------------------------------
# C. Genuine model loading and inference (requires real checkpoints)
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def real_pipeline():
    return IrisPipelineService()


@requires_models
def test_c_real_models_load_with_full_key_coverage(real_pipeline):
    assert real_pipeline.segmenter.model is not None
    assert real_pipeline.recognizer.model is not None
    assert real_pipeline.model_version.startswith("LightIrisNet-MobileNetV3+Vis-IrisFormer:")


@requires_models
def test_c_real_recognizer_output_shape_finite_and_deterministic(real_pipeline):
    strip = np.random.RandomState(0).randint(0, 256, (64, 512), dtype=np.uint8)
    emb = real_pipeline.recognizer.extract_features(strip)
    assert emb.shape == (128, 768) and emb.dtype == np.float32
    assert np.isfinite(emb).all()
    assert IrisRecognizer.compare(emb, real_pipeline.recognizer.extract_features(strip.copy())) == 1.0


@requires_models
def test_c_real_embeddings_are_continuous_under_small_perturbation(real_pipeline):
    """Regression for LL-001: the old seeded-random fallback scored ~0 for a 1-level change."""
    rng = np.random.RandomState(1)
    strip = cv2.GaussianBlur(rng.randint(0, 256, (64, 512), dtype=np.uint8), (0, 0), 2)
    noisy = np.clip(strip + rng.normal(0, 1, strip.shape), 0, 255).astype(np.uint8)
    rec = real_pipeline.recognizer
    assert IrisRecognizer.compare(rec.extract_features(strip), rec.extract_features(noisy)) >= 0.95


@requires_models
def test_c_segmenter_preprocessing_matches_upstream_predict(real_pipeline):
    """The tensor fed to LightIrisNet equals upstream irisseg._test_impl.predict's input."""
    import torch
    from irisseg._test_impl import predict  # type: ignore

    seg = real_pipeline.segmenter
    rgb = _pattern(5, 256, 320)
    captured = []
    handle = seg.model.register_forward_pre_hook(lambda m, inp: captured.append(inp[0].detach().clone()))
    try:
        with pytest.raises(IrisSegmentationError):
            seg.segment(rgb)
        predict(seg.model, rgb.astype(np.float32) / 255.0, device=torch.device("cpu"))
    finally:
        handle.remove()
    assert len(captured) == 2
    assert torch.allclose(captured[0].contiguous(), captured[1].contiguous(), atol=1e-6)


@requires_models
def test_c_real_segmenter_rejects_non_eye_images(real_pipeline):
    with pytest.raises(IrisSegmentationError):
        real_pipeline.process_eye_image(_pattern(11, 480, 640))


# ---------------------------------------------------------------------------
# D. No synthetic embeddings, no silent fallbacks
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("filename", ENGINE_FILES)
def test_d_engine_contains_no_synthetic_fallbacks(filename):
    source = (_ENGINE_DIR / filename).read_text()
    for forbidden in ("np.random", "GEOMETRIC_FALLBACK", "randn(", "synthetic_embedding"):
        assert forbidden not in source, f"{filename} contains {forbidden!r}"


def test_d_biometric_service_has_no_byte_similarity_fallback():
    from backend.biometrics.service import BiometricService
    assert not hasattr(BiometricService, "_mock_cosine_similarity")
    source = (BASE_DIR / "backend" / "biometrics" / "service.py").read_text()
    assert "except Exception:\n            pass" not in source


def test_d_missing_models_never_yield_an_embedding(missing_models):
    from backend.biometrics.service import BiometricService
    image = _png(_pattern(1))
    with pytest.raises(IrisModelUnavailableError):
        BiometricService._resolve_iris_embedding(image)
    # Identical bytes used to short-circuit to 0.99 without any model.
    with pytest.raises(IrisModelUnavailableError):
        BiometricService._compare_iris_templates(image, image)


def test_d_raw_embedding_buffers_are_not_accepted_as_templates():
    """Pre-made 128x768 buffers (e.g. seeded fakes) cannot bypass model inference."""
    from backend.biometrics.service import BiometricService
    fake = _unit_patches(3).tobytes()
    assert len(fake) == 393216
    with pytest.raises(InvalidIrisImageError):
        BiometricService._resolve_iris_embedding(fake)


class _FakeEncoder:
    def __init__(self, fn):
        self.autoencoder = fn


class _FakeModel:
    def __init__(self, fn):
        self.Encoder = _FakeEncoder(fn)


def _recognizer_with(fn):
    rec = IrisRecognizer.__new__(IrisRecognizer)
    import torch
    rec.device = torch.device("cpu")
    rec.model = _FakeModel(fn)
    return rec


@requires_torch
def test_d_failed_inference_raises_instead_of_returning_an_embedding():
    def boom(*args, **kwargs):
        raise RuntimeError("simulated forward failure")
    with pytest.raises(IrisInferenceError):
        _recognizer_with(boom).extract_features(np.full((64, 512), 100, np.uint8))


@requires_torch
@pytest.mark.parametrize("bad", ["nan", "zeros", "shape"])
def test_d_invalid_model_output_is_rejected(bad):
    import torch

    def out(*args, **kwargs):
        if bad == "nan":
            t = torch.full((1, 128, 768), float("nan"))
        elif bad == "zeros":
            t = torch.zeros((1, 128, 768))
        else:
            t = torch.ones((1, 64, 768))
        return t, None, None, None, None
    with pytest.raises(IrisEmbeddingError):
        _recognizer_with(out).extract_features(np.full((64, 512), 100, np.uint8))


# ---------------------------------------------------------------------------
# E. Image processing and validation
# ---------------------------------------------------------------------------
def test_e_valid_images_are_normalised_to_rgb_uint8():
    assert validate_eye_image(_pattern(1)).shape == (240, 320, 3)
    gray = _pattern(1)[:, :, 0]
    assert validate_eye_image(gray).shape == (240, 320, 3)
    rgba = np.dstack([_pattern(1), np.full((240, 320), 255, np.uint8)])
    assert validate_eye_image(rgba).shape == (240, 320, 3)


@pytest.mark.parametrize("image", [
    np.zeros((0, 0, 3), np.uint8),                       # empty
    np.zeros((32, 32, 3), np.uint8) + 7,                  # too small
    np.full((240, 320, 3), 128, np.uint8),                # uniform
    np.random.RandomState(0).rand(240, 320, 3),           # float, not uint8
    np.zeros((240, 320, 2), np.uint8) + 9,                # wrong channel count
    np.zeros((2, 240, 320, 3), np.uint8),                 # wrong rank
    "not an array",
])
def test_e_invalid_images_are_rejected(image):
    with pytest.raises(InvalidIrisImageError):
        validate_eye_image(image)


def test_e_corrupted_or_non_image_bytes_are_rejected():
    from backend.biometrics.service import BiometricService
    for data in (b"", b"\xff\xd8\xff\xe0garbage-not-a-jpeg", b"\x89PNG\r\n\x1a\nbroken", b"plain text"):
        with pytest.raises(InvalidIrisImageError):
            BiometricService._resolve_iris_embedding(data)


class _StubSegmenter:
    MODEL_NAME = "stub"

    def __init__(self, result=None, error=None):
        self.result, self.error = result, error

    def segment(self, rgb):
        if self.error:
            raise self.error
        return self.result


class _NeverCalledRecognizer:
    model_version = "stub"

    def extract_features(self, strip):
        raise AssertionError("recognizer must not run after a segmentation/normalization failure")


def _pipeline_with(segmenter):
    pipe = IrisPipelineService.__new__(IrisPipelineService)
    pipe.segmenter = segmenter
    pipe.recognizer = _NeverCalledRecognizer()
    pipe.normalizer = IrisNormalizer(64, 512)
    return pipe


def test_e_segmentation_failure_propagates_and_skips_recognition():
    pipe = _pipeline_with(_StubSegmenter(error=IrisSegmentationError("no iris")))
    with pytest.raises(IrisSegmentationError):
        pipe.process_eye_image(_pattern(2))


def test_e_degenerate_normalization_is_rejected():
    img = _pattern(3)
    img[60:180, 100:220] = 90  # uniform region where the "iris" is placed
    iris = np.zeros((240, 320), np.uint8)
    pupil = np.zeros((240, 320), np.uint8)
    cv2.circle(iris, (160, 120), 50, 1, -1)
    cv2.circle(pupil, (160, 120), 15, 1, -1)
    seg = {"iris_mask": iris, "pupil_mask": pupil, "iris_ellipse": ((160.0, 120.0), (100.0, 100.0), 0.0),
           "pupil_ellipse": ((160.0, 120.0), (30.0, 30.0), 0.0), "diagnostics": {}, "mode": "ML_INFERENCE"}
    with pytest.raises(IrisSegmentationError, match="degenerate"):
        _pipeline_with(_StubSegmenter(result=seg)).process_eye_image(img)


def test_e_normalizer_dimensions():
    """Daugman rubber-sheet unwrapping creates exactly a 64x512 matrix."""
    normalizer = IrisNormalizer(target_height=64, target_width=512)
    iris_mask = np.zeros((300, 400), dtype=np.uint8)
    pupil_mask = np.zeros((300, 400), dtype=np.uint8)
    cv2.circle(iris_mask, (200, 150), 80, 1, -1)
    cv2.circle(pupil_mask, (200, 150), 25, 1, -1)
    res = normalizer.normalize(_pattern(4, 300, 400), iris_mask, pupil_mask)
    assert res["normalized_iris"].shape == (64, 512)


# ---------------------------------------------------------------------------
# F. Similarity with controlled feature vectors
# ---------------------------------------------------------------------------
def test_f_identical_vectors_score_maximum():
    e = _unit_patches(1)
    assert IrisRecognizer.compare(e, e.copy()) == 1.0


def test_f_orthogonal_vectors_score_zero_and_opposite_minus_one():
    a = np.zeros((128, 768), np.float32)
    b = np.zeros((128, 768), np.float32)
    a[:, 0] = 1.0
    b[:, 1] = 1.0
    assert IrisRecognizer.compare(a, b) == 0.0
    assert IrisRecognizer.compare(a, -a) == -1.0


def test_f_similarity_is_mean_of_patchwise_cosines():
    a, b = _unit_patches(1), _unit_patches(2)
    b[:64] = a[:64]  # half the patches identical, half ~orthogonal
    expected = float(np.mean(np.sum(a * b, axis=1)))
    assert IrisRecognizer.compare(a, b) == pytest.approx(expected, abs=1e-4)
    assert 0.45 < IrisRecognizer.compare(a, b) < 0.55


@pytest.mark.parametrize("bad", [
    np.ones((64, 768), np.float32),
    np.ones((128, 512), np.float32),
    np.ones((1, 128, 768), np.float32),
    np.full((128, 768), np.nan, np.float32),
    np.full((128, 768), np.inf, np.float32),
    np.zeros((128, 768), np.float32),
    [[1.0] * 768] * 128,
])
def test_f_invalid_embeddings_are_rejected(bad):
    with pytest.raises(IrisEmbeddingError):
        IrisRecognizer.compare(_unit_patches(1), bad)
    with pytest.raises(IrisEmbeddingError):
        IrisRecognizer.compare(bad, _unit_patches(1))


def test_f_single_zero_patch_is_rejected():
    e = _unit_patches(1)
    e[17] = 0.0
    with pytest.raises(IrisEmbeddingError, match="zero-norm"):
        validate_embedding(e)


# ---------------------------------------------------------------------------
# G. Enrollment / identification compatibility with genuine eye images
# ---------------------------------------------------------------------------
EVAL_DIR = os.getenv("LIFELINK_IRIS_EVAL_DIR", "").strip()


@requires_models
@pytest.mark.skipif(not EVAL_DIR, reason="BLOCKED: no consented iris images (set LIFELINK_IRIS_EVAL_DIR=<dir>/<subject>/<capture>.jpg)")
def test_g_repeat_captures_rank_their_own_subject_first(real_pipeline):
    """Rank-1 check on consented data: capture 1 of each subject is the gallery, others are probes.
    Reports scores; makes no claim that any fixed threshold is calibrated."""
    from backend.biometrics.service import BiometricService
    subjects = {}
    for d in sorted(Path(EVAL_DIR).iterdir()):
        files = sorted(p for p in d.glob("*") if p.suffix.lower() in (".jpg", ".jpeg", ".png"))
        if d.is_dir() and len(files) >= 2:
            subjects[d.name] = [BiometricService._resolve_iris_embedding(p.read_bytes()) for p in files]
    assert len(subjects) >= 2, "need at least two subjects with two captures each"
    gallery = {s: embs[0] for s, embs in subjects.items()}
    for subject, embs in subjects.items():
        for probe in embs[1:]:
            scores = {g: IrisRecognizer.compare(probe, e) for g, e in gallery.items()}
            assert max(scores, key=scores.get) == subject, scores


# ---------------------------------------------------------------------------
# H. Backend API behaviour
# ---------------------------------------------------------------------------
@pytest.fixture
def client():
    from backend.app import create_app
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def _token(role, staff_id, username):
    from backend.auth.security import SecurityUtils
    return SecurityUtils.create_token({"staff_id": staff_id, "username": username, "role": role,
                                       "portal": "clinical" if role == "clinician" else "hospital"})


@pytest.fixture
def clinician_headers():
    from backend.auth.rbac import Roles
    return {"Authorization": f"Bearer {_token(Roles.CLINICIAN, 'staff-clinician-001', 'clinician')}"}


@pytest.fixture
def registrar_headers():
    from backend.auth.rbac import Roles
    return {"Authorization": f"Bearer {_token(Roles.REGISTRATION_STAFF, 'staff-hospital-002', 'registrar')}"}


class _TableStubPipeline:
    """Test double: maps exact decoded images to pre-defined embeddings; anything else
    'fails segmentation'. Used only to exercise decision logic without model weights."""

    model_version = "TEST-STUB"

    def __init__(self, table):
        self.table = table

    def process_eye_image(self, rgb, eye_side="OD"):
        key = hashlib.sha256(np.ascontiguousarray(rgb).tobytes()).hexdigest()
        if key not in self.table:
            raise IrisSegmentationError("stub: unknown image")
        return {"embedding": self.table[key]}


def _key(rgb):
    return hashlib.sha256(np.ascontiguousarray(rgb).tobytes()).hexdigest()


@pytest.fixture
def stub_gallery(monkeypatch):
    """Two enrolled patients with iris images, plus one unenrolled image."""
    from backend.biometrics.service import BiometricService
    from backend.database.connection import Database
    from backend.database.crypto import TemplateCrypto

    crypto = TemplateCrypto()
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    images = {name: _pattern(seed) for name, seed in (("A", 101), ("B", 102), ("UNKNOWN", 103))}
    table = {_key(img): _unit_patches(seed) for img, seed in zip(images.values(), (201, 202, 203))}
    monkeypatch.setattr(BiometricService, "_get_iris_pipeline", classmethod(lambda cls: _TableStubPipeline(table)))

    patients = {}
    for name in ("A", "B"):
        pid = f"ll001-test-{name}-{uuid.uuid4().hex[:8]}"
        patients[name] = pid
        Database.execute_commit(
            "INSERT INTO patients_cache (id, lifelink_id, full_name, dob, gender, blood_type, status, version, created_at, updated_at) "
            "VALUES (?, ?, ?, '1990-01-01', 'O', 'O+', 'active', 1, ?, ?);",
            (pid, f"LL-T-{pid[-8:]}", f"LL001 Test {name}", now, now))
        Database.execute_commit(
            "INSERT INTO medical_records (id, patient_id, allergies, chronic_conditions, current_medications, implanted_devices, updated_at) "
            "VALUES (?, ?, ?, '[]', '[]', '[]', ?);",
            (str(uuid.uuid4()), pid, json.dumps([f"allergy-{name}"]), now))
        Database.execute_commit(
            "INSERT INTO iris_templates (id, patient_id, eye_side, encrypted_template, model_version, quality_score, created_at) "
            "VALUES (?, ?, 'OD', ?, 'TEST-STUB', 1.0, ?);",
            (str(uuid.uuid4()), pid, crypto.encrypt(_png(images[name])), now))
    yield {"images": images, "patients": patients}
    for pid in patients.values():
        for table_name in ("iris_templates", "medical_records", "patients_cache"):
            column = "id" if table_name == "patients_cache" else "patient_id"
            Database.execute_commit(f"DELETE FROM {table_name} WHERE {column} = ?;", (pid,))


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def test_h_missing_models_return_503_model_unavailable_not_no_match(client, clinician_headers, missing_models):
    from backend.database.connection import Database
    resp = client.post("/api/v1/identify", headers=clinician_headers,
                       json={"biometric_type": "iris", "probe_b64": _b64(_png(_pattern(1)))})
    assert resp.status_code == 503
    body = resp.get_json()
    assert body["status"] == "error"
    assert body["error_type"] == "MODEL_UNAVAILABLE"
    assert "identification" not in body and "candidates" not in body
    assert "/" not in body["message"]  # no filesystem paths leak to the client
    rows = Database.execute_query(
        "SELECT details_json FROM audit_events WHERE action = 'BIOMETRIC_IDENTIFY_IRIS' ORDER BY timestamp DESC LIMIT 1;")
    assert rows and "MODEL_UNAVAILABLE" in rows[0]["details_json"]


def test_h_verify_missing_models_without_stub_is_503(client, clinician_headers, missing_models):
    resp = client.post("/api/v1/verify", headers=clinician_headers, json={
        "patient_id": "pat-synthetic-001", "biometric_type": "iris",
        "probe_b64": _b64(_png(_pattern(1))), "feature_position": "OD"})
    if resp.status_code == 200:
        # Patient has no enrolled irises in this database: nothing to compare against.
        assert resp.get_json()["verification"]["status"] == "NO_ENROLLED_TEMPLATES"
    else:
        assert resp.status_code == 503
        assert resp.get_json()["error_type"] == "MODEL_UNAVAILABLE"


def test_h_invalid_probe_image_is_400(client, clinician_headers, stub_gallery):
    resp = client.post("/api/v1/identify", headers=clinician_headers,
                       json={"biometric_type": "iris", "probe_b64": _b64(b"definitely not an image")})
    assert resp.status_code == 400
    assert resp.get_json()["error_type"] == "INVALID_IRIS_IMAGE"


def test_h_successful_inference_reaches_matcher_and_retrieves_correct_patient(client, clinician_headers, stub_gallery):
    resp = client.post("/api/v1/identify", headers=clinician_headers,
                       json={"biometric_type": "iris", "probe_b64": _b64(_png(stub_gallery["images"]["A"]))})
    assert resp.status_code == 200
    ident = resp.get_json()["identification"]
    assert ident["outcome"] == "MATCH"
    assert ident["candidates"][0]["patient_id"] == stub_gallery["patients"]["A"]
    assert ident["candidates"][0]["score"] == 1.0
    # Emergency retrieval follows the matched identity only.
    summary = client.get(f"/api/v1/patients/{ident['candidates'][0]['patient_id']}/emergency-summary",
                         headers=clinician_headers).get_json()["emergency_summary"]
    assert summary["patient_id"] == stub_gallery["patients"]["A"]
    assert summary["critical_allergies"] == ["allergy-A"]


def test_h_genuine_no_match_remains_no_match(client, clinician_headers, stub_gallery):
    resp = client.post("/api/v1/identify", headers=clinician_headers,
                       json={"biometric_type": "iris", "probe_b64": _b64(_png(stub_gallery["images"]["UNKNOWN"]))})
    assert resp.status_code == 200
    ident = resp.get_json()["identification"]
    assert ident["outcome"] == "NO_MATCH"
    assert ident["candidates"] == []


def test_h_model_failure_during_gallery_scan_aborts_instead_of_no_match(client, clinician_headers, stub_gallery, monkeypatch):
    from backend.biometrics.service import BiometricService
    original = BiometricService._get_iris_pipeline.__func__
    calls = {"n": 0}

    def flaky(cls):
        calls["n"] += 1
        if calls["n"] > 1:  # probe succeeds, then the engine fails on the gallery
            raise IrisInferenceError("simulated runtime failure")
        return original(cls)
    monkeypatch.setattr(BiometricService, "_get_iris_pipeline", classmethod(flaky))
    resp = client.post("/api/v1/identify", headers=clinician_headers,
                       json={"biometric_type": "iris", "probe_b64": _b64(_png(stub_gallery["images"]["A"]))})
    assert resp.status_code == 500
    assert resp.get_json()["error_type"] == "MODEL_INFERENCE_FAILED"


def test_h_capture_with_missing_models_stops_with_503(client, registrar_headers, missing_models):
    resp = client.post("/api/v1/devices/camera/capture-iris", headers=registrar_headers, json={"eye_side": "OD"})
    assert resp.status_code == 503
    body = resp.get_json()
    assert body["error_type"] == "MODEL_UNAVAILABLE"
    assert body["template_extracted"] is False


def test_h_capture_segmentation_failure_is_retryable_422(client, registrar_headers, stub_gallery):
    # The mock camera frame is not in the stub table -> SEGMENTATION_FAILED.
    resp = client.post("/api/v1/devices/camera/capture-iris", headers=registrar_headers, json={"eye_side": "OD"})
    assert resp.status_code == 422
    body = resp.get_json()
    assert body["status"] == "retry"
    assert body["error_type"] == "SEGMENTATION_FAILED"
    assert body["template_extracted"] is False


def test_h_health_reports_iris_engine_state_without_paths(client, missing_models):
    from backend.biometrics.service import BiometricService
    with pytest.raises(IrisModelUnavailableError):
        BiometricService._get_iris_pipeline()
    status = client.get("/api/v1/devices/health").get_json()["iris_engine"]
    assert status["state"] == "unavailable"
    assert status["error_type"] == "MODEL_UNAVAILABLE"
    assert "/" not in json.dumps(status)
