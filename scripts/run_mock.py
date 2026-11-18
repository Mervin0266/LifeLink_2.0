#!/usr/bin/env python3
"""
LifeLink 2.0 - Mock Server Launcher
Launches the full stack in MOCK_MODE on port 5000 with simulated hardware.
"""

import sys
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Enforce MOCK_MODE for this runner
os.environ["MOCK_MODE"] = "true"
os.environ["HARDWARE_MODE"] = "false"

from backend.config import Config
from backend.app import create_app
from backend.database.connection import init_db


def main():
    print("=====================================================================")
    print("  LifeLink 2.0 — Emergency Medical Identity & Patient Information")
    print("  Target: Raspberry Pi 5 Touchscreen Terminal (MOCK MODE)")
    print("=====================================================================")
    print(f"  Web Server:      http://127.0.0.1:{Config.PORT}")
    print(f"  Operational Mode: MOCK_MODE=true (Physical hardware simulated)")
    print(f"  Local Database:  {Config.DB_TYPE.upper()} ({Config.DB_NAME})")
    print("---------------------------------------------------------------------")
    print("  Demo Staff Accounts:")
    print("    • Clinical Portal: doctor@lifelink.local     / Clinical@123")
    print("    • Hospital Portal: registrar@lifelink.local  / Hospital@123")
    print("    • Admin Portal:    recordsadmin@lifelink.local / Admin@123")
    print("    • Admin Portal:    sysadmin@lifelink.local     / SysAdmin@123")
    print("---------------------------------------------------------------------")
    print("  Press CTRL+C to terminate.")
    print("=====================================================================\n")

    init_db()
    app = create_app()
    app.run(host=Config.HOST, port=Config.PORT, debug=False)


if __name__ == "__main__":
    main()
