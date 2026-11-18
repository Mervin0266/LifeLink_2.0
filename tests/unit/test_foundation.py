"""
Unit tests for LifeLink 2.0 application foundation, configuration, and database crypto.
"""

import pytest
from backend.config import Config
from backend.app import create_app
from backend.database.crypto import TemplateCrypto
from backend.database.connection import Database


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


def test_health_endpoint(client):
    """Verifies that the /api/v1/health endpoint returns 200 OK and valid status."""
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "healthy"
    assert data["version"] == "2.0.0"
    assert data["mock_mode"] is True


def test_template_crypto():
    """Verifies AES-256-GCM encryption and decryption round-trip."""
    crypto = TemplateCrypto()
    sample = b"GT521F32_synthetic_498_bytes_biometric_template" * 10
    encrypted = crypto.encrypt(sample)
    assert encrypted != sample
    assert len(encrypted) > len(sample)

    decrypted = crypto.decrypt(encrypted)
    assert decrypted == sample


def test_database_connectivity():
    """Verifies database execution and basic query capabilities."""
    res = Database.execute_one("SELECT 42 as answer;")
    assert res is not None
    assert res["answer"] == 42


def test_frontend_serving(client):
    """Verifies that the kiosk root / serves index.html and static assets."""
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"LifeLink 2.0" in resp.data

    css_resp = client.get("/css/style.css")
    assert css_resp.status_code == 200
    assert b"kiosk-header" in css_resp.data

    js_resp = client.get("/js/app.js")
    assert js_resp.status_code == 200
    assert b"LifeLinkApp" in js_resp.data

