"""
LifeLink 2.0 - Camera Subsystem Communication Module
Formats and handles payloads transferred between Raspberry Pi 3B+ and Raspberry Pi 5
over the dedicated wired Ethernet connection (192.168.50.0/24 or configurable).
"""

import base64
from typing import Dict, Any, Optional

try:
    from . import config
except ImportError:
    import config


class CameraCommunicationHelper:
    """Utilities for serializing and dispatching image data over wired network."""

    @staticmethod
    def format_capture_response(
        result: Dict[str, Any],
        include_image_base64: bool = False
    ) -> Dict[str, Any]:
        """Formats the iris capture response for transmission to the Pi 5."""
        response = {
            "status": result.get("status", "error"),
            "eye_side": result.get("eye_side", "OD"),
            "quality": result.get("quality", {}),
            "transport": getattr(config, "TRANSPORT_NAME", "Wired-Ethernet"),
            "device": getattr(config, "DEVICE_NAME", "RaspberryPi-3B-Plus-CameraModule3-NoIR")
        }

        if "message" in result:
            response["message"] = result["message"]

        if "attempts" in result:
            response["attempts"] = result["attempts"]

        image_bytes: Optional[bytes] = result.get("image_bytes")
        if image_bytes:
            response["image_size_bytes"] = len(image_bytes)
            if include_image_base64:
                response["image_base64"] = base64.b64encode(image_bytes).decode("ascii")

        return response

    @staticmethod
    def format_health_response(
        camera_state: str,
        led_status: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Formats system health for Pi 5 monitoring."""
        return {
            "status": "ready" if camera_state in ("IDLE", "COMPLETED", "PREVIEW") else "busy",
            "camera_state": camera_state,
            "device": getattr(config, "DEVICE_NAME", "RaspberryPi-3B-Plus-CameraModule3-NoIR"),
            "transport": getattr(config, "TRANSPORT_NAME", "Wired-Ethernet"),
            "service": "LifeLink-Camera-Daemon-v2-Pi3B",
            "ir_led": led_status
        }


# Backward-compatibility alias
USBCommunicationHelper = CameraCommunicationHelper
