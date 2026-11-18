#!/usr/bin/env python3
"""
LifeLink 2.0 - System Bootstrap Utility
Checks runtime dependencies, model files, and database readiness.
"""

import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def check_python():
    print("[1/5] Checking Python Version...")
    v = sys.version_info
    print(f"      Python {v.major}.{v.minor}.{v.micro} detected.")
    if v.major < 3 or (v.major == 3 and v.minor < 10):
        print("      [ERROR] Python 3.10+ required.")
        return False
    return True


def check_libraries():
    print("[2/5] Checking Required Packages...")
    packages = ["flask", "werkzeug", "cryptography", "cv2", "torch", "numpy", "PIL", "pydantic"]
    missing = []
    for pkg in packages:
        try:
            __import__(pkg)
            print(f"      [OK] {pkg}")
        except ImportError:
            print(f"      [MISSING] {pkg}")
            missing.append(pkg)
    if missing:
        print(f"      [ERROR] Missing packages: {missing}. Run: pip install -r requirements.txt")
        return False
    return True


def check_models():
    print("[3/5] Checking Machine Learning Model Weights...")
    from backend.config import Config
    
    seg_path = Config.LIGHTIRISNET_WEIGHTS
    rec_path = Config.VIS_IRISFORMER_WEIGHTS
    
    if seg_path.exists():
        print(f"      [OK] LightIrisNet: {seg_path} ({seg_path.stat().st_size / 1e6:.1f} MB)")
    else:
        print(f"      [WARNING] LightIrisNet weights not found at {seg_path}")
        
    if rec_path.exists():
        print(f"      [OK] Vis-IrisFormer: {rec_path} ({rec_path.stat().st_size / 1e6:.1f} MB)")
    else:
        print(f"      [WARNING] Vis-IrisFormer weights not found at {rec_path}")
    return True


def check_database():
    print("[4/5] Initializing Database Schema...")
    from backend.database.connection import init_db, Database
    init_db()
    res = Database.execute_one("SELECT 1 as val;")
    if res and res["val"] == 1:
        print("      [OK] Database schema initialized and functional.")
        return True
    print("      [ERROR] Failed to query database.")
    return False


def check_crypto():
    print("[5/5] Testing Biometric Encryption Round-Trip...")
    from backend.database.crypto import TemplateCrypto
    c = TemplateCrypto()
    data = b"synthetic_fingerprint_498_bytes_test"
    enc = c.encrypt(data)
    dec = c.decrypt(enc)
    if dec == data:
        print("      [OK] AES-256-GCM encryption verified.")
        return True
    print("      [ERROR] Encryption test failed.")
    return False


def main():
    print("==================================================")
    print(" LifeLink 2.0 - System Bootstrap & Diagnostic")
    print("==================================================")
    
    success = (
        check_python()
        and check_libraries()
        and check_models()
        and check_database()
        and check_crypto()
    )
    
    print("==================================================")
    if success:
        print(" LifeLink 2.0 Environment Ready!")
        print(" Run: python scripts/seed_demo.py to populate test data.")
        print(" Run: python scripts/run_mock.py to launch in mock mode.")
    else:
        print(" Bootstrap encountered issues. Please inspect errors above.")
    print("==================================================")
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
