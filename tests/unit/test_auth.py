"""
Unit tests for LifeLink 2.0 Authentication and RBAC.
"""

import pytest
from backend.app import create_app
from backend.auth.security import SecurityUtils
from backend.auth.rbac import Roles


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


def test_password_hashing():
    pw = "SuperSecure@2026!"
    hashed = SecurityUtils.hash_password(pw)
    assert SecurityUtils.verify_password(pw, hashed) is True
    assert SecurityUtils.verify_password("WrongPassword", hashed) is False


def test_token_creation_and_verification():
    payload = {"staff_id": "test-123", "role": "clinician"}
    token = SecurityUtils.create_token(payload, expires_in_hours=1)
    decoded = SecurityUtils.verify_token(token)
    assert decoded is not None
    assert decoded["staff_id"] == "test-123"
    assert decoded["role"] == "clinician"

    # Test tampering
    tampered = token[:-4] + "fake"
    assert SecurityUtils.verify_token(tampered) is None


def test_portal_login_success(client):
    """Verifies that clinician can log into the clinical portal."""
    resp = client.post("/api/v1/auth/login", json={
        "portal": "clinical",
        "username_or_email": "clinician",
        "password": "Clinical@123"
    })
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "success"
    assert "token" in data
    assert data["user"]["role"] == Roles.CLINICIAN


def test_portal_login_mismatch(client):
    """Verifies that hospital staff is rejected when attempting clinical portal login."""
    resp = client.post("/api/v1/auth/login", json={
        "portal": "clinical",
        "username_or_email": "registrar",
        "password": "Hospital@123"
    })
    assert resp.status_code == 403
    data = resp.get_json()
    assert data["status"] == "error"
    assert "not authorized" in data["message"].lower()


def test_admin_portal_login(client):
    """Verifies that records admin can log into the admin portal."""
    resp = client.post("/api/v1/auth/login", json={
        "portal": "admin",
        "username_or_email": "recordsadmin",
        "password": "Admin@123"
    })
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "success"
    assert data["user"]["role"] == Roles.RECORDS_ADMIN
