"""
LifeLink 2.0 - Unit Tests for IR LED Controller
Tests GPIO18 initialization state, turn ON/OFF, thread safety, watchdog timeout,
and cleanup behavior under mock/simulated conditions.
"""

import sys
import os
import time
import threading
import pytest

# Ensure iris-module/camera-client is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../iris-module/camera-client")))

from ir_led_controller import IRLEDController  # type: ignore


class TestIRLEDController:
    """Test suite for 850 nm IR LED controller."""

    def test_led_initializes_in_off_state(self):
        """Invariant: IR LED must initialize strictly in the OFF state."""
        led = IRLEDController(pin=18, active_high=True, enabled=True)
        try:
            assert led.is_on() is False
            status = led.get_status()
            assert status["is_on"] is False
            assert status["pin"] == 18
            assert status["active_high"] is True
        finally:
            led.cleanup()

    def test_turn_on_and_turn_off(self):
        """Verifies turning ON sets state to True, and turn OFF restores False."""
        led = IRLEDController(pin=18, active_high=True, enabled=True)
        try:
            assert led.turn_on() is True
            assert led.is_on() is True
            assert led.get_status()["is_on"] is True

            assert led.turn_off() is True
            assert led.is_on() is False
            assert led.get_status()["is_on"] is False
        finally:
            led.cleanup()

    def test_turn_off_is_idempotent(self):
        """Calling turn_off multiple times must remain safe and return True."""
        led = IRLEDController(pin=18, enabled=True)
        try:
            led.turn_off()
            led.turn_off()
            assert led.is_on() is False
        finally:
            led.cleanup()

    def test_disabled_led_does_not_activate(self):
        """When enabled=False in config, turn_on must be a no-op and remain OFF."""
        led = IRLEDController(pin=18, enabled=False)
        try:
            assert led.turn_on() is False
            assert led.is_on() is False
        finally:
            led.cleanup()

    def test_watchdog_safety_timeout_shuts_off_led(self):
        """Eye Safety Watchdog: LED must automatically shut off if max_on_time expires."""
        # Set a short 0.2s max_on_time for test verification
        led = IRLEDController(pin=18, enabled=True, max_on_time=0.2)
        try:
            led.turn_on()
            assert led.is_on() is True
            # Wait for safety watchdog timer to fire
            time.sleep(0.35)
            assert led.is_on() is False, "Watchdog failed to automatically force LED off!"
        finally:
            led.cleanup()

    def test_cleanup_guarantees_led_off(self):
        """Calling cleanup while ON must turn LED OFF and clear timers."""
        led = IRLEDController(pin=18, enabled=True)
        try:
            led.turn_on()
            assert led.is_on() is True
            led.cleanup()
            assert led.is_on() is False
        finally:
            led.cleanup()

    def test_thread_safety_under_concurrent_access(self):
        """Multiple threads toggling LED must not corrupt state or deadlock."""
        led = IRLEDController(pin=18, enabled=True)
        errors = []

        def worker():
            try:
                for _ in range(20):
                    led.turn_on()
                    time.sleep(0.005)
                    led.turn_off()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert led.is_on() is False
        led.cleanup()
