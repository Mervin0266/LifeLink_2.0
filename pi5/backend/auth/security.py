"""
LifeLink 2.0 - Auth Security & Password Hashing
Provides secure password hashing (PBKDF2-HMAC-SHA256 with 200,000 rounds)
and HMAC-SHA256 authenticated session token issuance and validation.
"""

import os
import hmac
import hashlib
import base64
import json
import time
from typing import Dict, Any, Optional
from backend.config import Config


class SecurityUtils:
    """Utilities for cryptographic password hashing and token management."""

    @staticmethod
    def hash_password(password: str) -> str:
        """Hashes a password with a fresh random 16-byte salt using PBKDF2-HMAC-SHA256."""
        salt = os.urandom(16)
        key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 200000)
        return f"pbkdf2:sha256:200000${base64.b64encode(salt).decode('utf-8')}${base64.b64encode(key).decode('utf-8')}"

    @staticmethod
    def verify_password(password: str, hashed: str) -> bool:
        """Verifies a plaintext password against a stored PBKDF2 hash."""
        try:
            parts = hashed.split("$")
            if len(parts) != 3:
                return False
            salt = base64.b64decode(parts[1])
            expected_key = base64.b64decode(parts[2])
            candidate_key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 200000)
            return hmac.compare_digest(candidate_key, expected_key)
        except Exception:
            return False

    @staticmethod
    def create_token(payload: Dict[str, Any], expires_in_hours: int = None) -> str:
        """Creates an HMAC-SHA256 signed session token."""
        duration = expires_in_hours or Config.TOKEN_EXPIRATION_HOURS
        exp = int(time.time()) + (duration * 3600)
        data = {**payload, "exp": exp}
        
        header = base64.urlsafe_b64encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode()).decode().rstrip("=")
        body = base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=")
        unsigned = f"{header}.{body}"
        
        sig = hmac.new(
            Config.JWT_SECRET_KEY.encode(),
            unsigned.encode(),
            hashlib.sha256
        ).digest()
        sig_b64 = base64.urlsafe_b64encode(sig).decode().rstrip("=")
        return f"{unsigned}.{sig_b64}"

    @staticmethod
    def verify_token(token: str) -> Optional[Dict[str, Any]]:
        """Verifies signature and expiration of an HMAC-SHA256 session token."""
        try:
            parts = token.split(".")
            if len(parts) != 3:
                return None
            header_b64, body_b64, sig_b64 = parts
            unsigned = f"{header_b64}.{body_b64}"
            
            # Recompute signature
            expected_sig = hmac.new(
                Config.JWT_SECRET_KEY.encode(),
                unsigned.encode(),
                hashlib.sha256
            ).digest()
            expected_sig_b64 = base64.urlsafe_b64encode(expected_sig).decode().rstrip("=")
            
            if not hmac.compare_digest(sig_b64, expected_sig_b64):
                return None
                
            # Decode body
            padded_body = body_b64 + "=" * (-len(body_b64) % 4)
            data = json.loads(base64.urlsafe_b64decode(padded_body.encode()).decode())
            
            # Check expiration
            if data.get("exp", 0) < int(time.time()):
                return None
                
            return data
        except Exception:
            return None
