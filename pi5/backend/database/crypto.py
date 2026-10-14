"""
LifeLink 2.0 - Biometric Template Encryption
Implements authenticated AES-256-GCM encryption for fingerprint and iris templates at rest.
"""

import os
from typing import Tuple
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from backend.config import Config


class TemplateCrypto:
    """Handles symmetric encryption and decryption of biometric template byte arrays."""

    def __init__(self, key: bytes = None):
        self.key = key or Config.TEMPLATE_ENCRYPTION_KEY
        if len(self.key) != 32:
            raise ValueError(f"AES-256 requires exactly 32-byte key, got {len(self.key)}")
        self.aesgcm = AESGCM(self.key)

    def encrypt(self, plaintext_bytes: bytes, associated_data: bytes = None) -> bytes:
        """
        Encrypts plaintext bytes using AES-256-GCM.
        Returns: Nonce (12 bytes) + Ciphertext with GCM auth tag (N + 16 bytes).
        """
        if not plaintext_bytes:
            raise ValueError("Cannot encrypt empty template bytes")
        nonce = os.urandom(12)  # Standard 96-bit nonce for AES-GCM
        ciphertext = self.aesgcm.encrypt(nonce, plaintext_bytes, associated_data)
        return nonce + ciphertext

    def decrypt(self, encrypted_bytes: bytes, associated_data: bytes = None) -> bytes:
        """
        Decrypts an AES-256-GCM blob.
        Extracts 12-byte nonce and verifies the GCM authentication tag.
        """
        if not encrypted_bytes or len(encrypted_bytes) < 28:
            raise ValueError("Invalid encrypted template: payload too short")
        nonce = encrypted_bytes[:12]
        ciphertext = encrypted_bytes[12:]
        return self.aesgcm.decrypt(nonce, ciphertext, associated_data)
