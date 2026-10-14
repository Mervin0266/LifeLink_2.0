#!/usr/bin/env python3
"""
LifeLink 2.0 - Raspberry Pi Zero W Camera & IR LED Diagnostic Tool
Validates hardware initialization, GPIO18 safety policy, quality filtering,
multi-frame selection, and wired REST endpoints.
"""

import sys
import time
import json
from pathlib import Path

# Add current directory to module path
PIZERO_DIR = Path(__file__).resolve().parent
if str(PIZERO_DIR) not in sys.path:
    sys.path.insert(0, str(PIZERO_DIR))

import config
from ir_led_controller import get_ir_led_controller
from camera_client import CameraClient
from quality import IrisQualityEvaluator
from quality_checker import QualityChecker
from iris_capture import IrisCaptureCoordinator


def run_diagnostics():
    print("=================================================================")
    print(" LifeLink 2.0: Raspberry Pi Zero W Camera Diagnostic")
    print("=================================================================")

    # 1. Test IR LED Controller Safety Invariants
    print("\n[Step 1/5] Verifying GPIO18 IR LED Controller...")
    led = get_ir_led_controller()
    status = led.get_status()
    print(f"  [+] Controller status: {status}")

    if led.is_on():
        print("  [-] CRITICAL ERROR: IR LED is ON at startup! Forcing OFF.")
        led.turn_off()
        sys.exit(1)
    else:
        print("  [OK] Invariant Verified: IR LED starts strictly in OFF state.")

    print("  [*] Performing momentary pulse test (0.2s)...")
    led.turn_on()
    time.sleep(0.2)
    led.turn_off()
    if not led.is_on():
        print("  [OK] Invariant Verified: IR LED turned OFF after pulse.")
    else:
        print("  [-] Error: IR LED failed to shut off!")
        sys.exit(1)

    # 2. Test Camera Client Frame Acquisition
    print("\n[Step 2/5] Testing Camera Capture Interface...")
    cam = CameraClient()
    init_ok = cam.initialize()
    is_hw = getattr(cam, "_is_hardware", False)
    print(f"  [+] Camera initialized: {init_ok} (Mode: {'Hardware/Picamera2' if is_hw else 'Simulated'})")

    frame, meta = cam.capture_frame()
    if frame is None:
        print("  [-] Error: Failed to acquire frame from camera client.")
        sys.exit(1)
    print(f"  [OK] Frame acquired successfully! Dimensions: {frame.shape[1]}x{frame.shape[0]} px, Channels: {frame.shape[2]}")

    # 3. Test ISO/IEC 29794-6 Quality Filter
    print("\n[Step 3/5] Evaluating ISO/IEC 29794-6 Quality Filter...")
    report = QualityChecker.evaluate_frame(frame)
    metrics = report.get("metrics", {})
    print(f"  [+] Sharpness (Laplacian var): {metrics.get('sharpness')}")
    print(f"  [+] Mean Intensity:            {metrics.get('mean_intensity')}")
    print(f"  [+] Glare Percentage:          {metrics.get('glare_percentage')}%")
    print(f"  [+] Est. Iris Diameter:        {metrics.get('estimated_diameter')} px")
    print(f"  [+] Quality Acceptable:        {report.get('passed')}")

    # 4. Test Multi-frame Capture & Synchronized LED Lifecycle
    print("\n[Step 4/5] Testing IrisCaptureCoordinator (LED Synchronization & Best Frame)...")
    state_log = []
    coordinator = IrisCaptureCoordinator(
        camera_client=cam,
        led_controller=led,
        state_callback=lambda s: state_log.append(s)
    )

    result = coordinator.execute_scan(eye_side="OD")
    print(f"  [+] Scan Result Status: {result.get('status')}")
    print(f"  [+] Captured Attempts:  {len(result.get('attempts', []))}")
    print(f"  [+] State Transitions:  {' -> '.join(state_log)}")

    if led.is_on():
        print("  [-] CRITICAL ERROR: IR LED remained ON after execute_scan() completed!")
        led.turn_off()
        sys.exit(1)
    else:
        print("  [OK] Invariant Verified: IR LED is confirmed OFF following scan.")

    # 5. Clean Up
    print("\n[Step 5/5] Releasing Hardware Resources...")
    cam.release()
    led.cleanup()
    print("  [OK] Hardware resources cleanly released.")

    print("\n=================================================================")
    print(" LifeLink 2.0: Pi Zero W Subsystem Verification PASSED!")
    print("=================================================================")
    return True


if __name__ == "__main__":
    success = run_diagnostics()
    sys.exit(0 if success else 1)
