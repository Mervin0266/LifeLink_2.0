"""
LifeLink 2.0 - Configuration Module
Manages application settings, hardware modes, database paths, and secrets.
"""

import os
import base64
from pathlib import Path
try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv(dotenv_path=None, **kwargs):
        if dotenv_path and os.path.exists(dotenv_path):
            try:
                with open(dotenv_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            k, v = line.split("=", 1)
                            os.environ.setdefault(k.strip(), v.strip().strip("'").strip('"'))
            except Exception:
                pass
        return True

# Base directory for the LifeLink application
BASE_DIR = Path(__file__).resolve().parent.parent

# Load .env file from known paths (project root, deployment path, systemd config)
_candidate_envs = [
    BASE_DIR / ".env",
    BASE_DIR.parent / ".env",
    Path("/etc/lifelink/lifelink.env"),
    Path("/opt/lifelink/.env"),
]
for env_path in _candidate_envs:
    if env_path.exists():
        load_dotenv(dotenv_path=env_path)


class Config:
    """Application configuration holder."""

    BASE_DIR: Path = BASE_DIR

    # Operational Modes
    _raw_mock = os.getenv("MOCK_MODE")
    _raw_hw = os.getenv("HARDWARE_MODE")

    if _raw_hw is not None and _raw_mock is not None:
        MOCK_MODE: bool = _raw_mock.lower() in ("true", "1", "yes")
        HARDWARE_MODE: bool = _raw_hw.lower() in ("true", "1", "yes")
    elif _raw_hw is not None:
        HARDWARE_MODE: bool = _raw_hw.lower() in ("true", "1", "yes")
        MOCK_MODE: bool = not HARDWARE_MODE
    elif _raw_mock is not None:
        MOCK_MODE: bool = _raw_mock.lower() in ("true", "1", "yes")
        HARDWARE_MODE: bool = not MOCK_MODE
    else:
        MOCK_MODE: bool = True
        HARDWARE_MODE: bool = False

    VALIDATION_MODE: bool = os.getenv("VALIDATION_MODE", "false").lower() in ("true", "1", "yes")
    SINGLE_IMPRESSION_ENROLL: bool = os.getenv("SINGLE_IMPRESSION_ENROLL", "false").lower() in ("true", "1", "yes")

    # Server Settings
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", "5000"))
    SECRET_KEY: str = os.getenv("SECRET_KEY", "lifelink-dev-secret-key-default")
    JWT_SECRET_KEY: str = os.getenv("JWT_SECRET_KEY", "lifelink-jwt-secret-key-default")
    TOKEN_EXPIRATION_HOURS: int = int(os.getenv("TOKEN_EXPIRATION_HOURS", "8"))

    # Database
    DB_TYPE: str = os.getenv("DB_TYPE", "sqlite").lower()
    DB_NAME: str = os.getenv("DB_NAME", "lifelink_local.db")
    DB_PATH: Path = BASE_DIR / DB_NAME

    POSTGRES_HOST: str = os.getenv("POSTGRES_HOST", "127.0.0.1")
    POSTGRES_PORT: int = int(os.getenv("POSTGRES_PORT", "5432"))
    POSTGRES_USER: str = os.getenv("POSTGRES_USER", "lifelink_app")
    POSTGRES_PASSWORD: str = os.getenv("POSTGRES_PASSWORD", "lifelink_secure_local_pw")
    POSTGRES_DB: str = os.getenv("POSTGRES_DB", "lifelink")

    # Biometric Encryption Key (32-byte AES key)
    _raw_key = os.getenv("TEMPLATE_ENCRYPTION_KEY", "dGVzdF9lbmNyeXB0aW9uX2tleV8zMl9ieXRlc19sb25nIQ==")
    try:
        TEMPLATE_ENCRYPTION_KEY: bytes = base64.b64decode(_raw_key)
        if len(TEMPLATE_ENCRYPTION_KEY) != 32:
            # Fallback to deterministic 32-byte key if decoded length is unexpected
            TEMPLATE_ENCRYPTION_KEY = b"LifeLink2.0_AES256_EncryptionKey!"[:32]
    except Exception:
        TEMPLATE_ENCRYPTION_KEY = b"LifeLink2.0_AES256_EncryptionKey!"[:32]

    # Wired Peripheral Connections
    ESP32_SERIAL_PORT: str = os.getenv(
        "ESP32_SERIAL_PORT",
        "/dev/serial/by-id/usb-Silicon_Labs_CP2102_USB_to_UART_Bridge_Controller-if00-port0"
    )
    ESP32_BAUD_RATE: int = int(os.getenv("ESP32_BAUD_RATE", "115200"))

    # Wired Camera Peripheral (Raspberry Pi 3B+ over Wired Ethernet, or Pi Zero W backward compat)
    CAMERA_SERVICE_URL: str = os.getenv(
        "CAMERA_SERVICE_URL",
        os.getenv("PIZERO_CAMERA_URL", "http://192.168.50.2:5000")
    )
    PIZERO_CAMERA_URL: str = CAMERA_SERVICE_URL  # Backward compatibility alias
    CAMERA_REQUEST_TIMEOUT: float = float(os.getenv("CAMERA_REQUEST_TIMEOUT", "30.0"))
    CAMERA_DEVICE: str = os.getenv("CAMERA_DEVICE", "raspberry-pi-3b-plus")
    CAMERA_API_TOKEN: str = os.getenv("CAMERA_API_TOKEN", "lifelink-wired-internal-camera-token")

    # Supabase Cloud Sync Settings
    SUPABASE_URL: str = os.getenv("SUPABASE_URL", "https://mock-lifelink.supabase.co")
    SUPABASE_ANON_KEY: str = os.getenv("SUPABASE_ANON_KEY", "mock-anon-key-placeholder")
    SUPABASE_SERVICE_ROLE_KEY: str = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "mock-service-role-key-placeholder")
    SYNC_ENABLED: bool = os.getenv("SYNC_ENABLED", "false").lower() in ("true", "1", "yes")
    SYNC_INTERVAL_SECONDS: int = int(os.getenv("SYNC_INTERVAL_SECONDS", "30"))

    # Model Weights Paths
    LIGHTIRISNET_WEIGHTS: Path = (
        BASE_DIR.parent.parent / "LifeLink" / "LightIrisNet" / "model" / "best_mobilenetv3.pt"
    )
    VIS_IRISFORMER_WEIGHTS: Path = (
        BASE_DIR.parent.parent / "LifeLink" / "models" / "vis_irisformer" / "sota.pth"
    )
