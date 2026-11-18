"""
LifeLink 2.0 - Standalone Pi Zero W Test for IR LED Controller
Can be run directly on the Raspberry Pi Zero W via pytest.
"""

import sys
import os
import time
import threading
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from ir_led_controller import IRLEDController


class TestIRLEDControllerLocal:
    def test_led_initializes_in_off_state(self):
        led = IRLEDController(pin=18, enabled=True)
        try:
            assert led.is_on() is False
        finally:
            led.cleanup()

    def test_turn_on_and_turn_off(self):
        led = IRLEDController(pin=18, enabled=True)
        try:
            assert led.turn_on() is True
            assert led.is_on() is True
            assert led.turn_off() is True
            assert led.is_on() is False
        finally:
            led.cleanup()

    def test_watchdog_safety_timeout(self):
        led = IRLEDController(pin=18, enabled=True, max_on_time=0.2)
        try:
            led.turn_on()
            assert led.is_on() is True
            time.sleep(0.35)
            assert led.is_on() is False
        finally:
            led.cleanup()
