"""
LifeLink 2.0 - USB Gadget Communication Module
Formats and handles payloads transferred between Pi Zero W and Pi 5
over the wired USB Gadget Ethernet connection (192.168.55.0/24).
"""

import base64
from typing import Dict, Any, Optional


class USBCommunicationHelper:
    """Utilities for serializing and dispatching image data over USB gadget ethernet."""

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
            "transport": "USB-Gadget-Ethernet",
            "device": "PiZeroW-CameraModule3-NoIR"
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
            "status": "ready" if camera_state in ("IDLE", "COMPLETED") else "busy",
            "camera_state": camera_state,
            "device": "PiZeroW-CameraModule3-NoIR",
            "transport": "USB-Gadget-Ethernet",
            "service": "LifeLink-Camera-Daemon-v2",
            "ir_led": led_status
        }
