"""
LifeLink 2.0 - 850 nm IR LED Illumination Controller
Controls the 850 nm infrared LED module on the Raspberry Pi Zero W via GPIO18 (Pin 12).
Ensures safe startup in OFF state, thread-safe operation, automatic safety shutoff timers,
and graceful fallback on development/mock environments.
"""

import logging
import sys
import threading
import time
from typing import Optional, Dict, Any

try:
    from . import config
except ImportError:
    import config

logger = logging.getLogger("LifeLink.IRLED")
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("[%(asctime)s] [%(name)s] [%(levelname)s] %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


def _safe_log(msg: str):
    """Safely logs message without failing if stderr or handler streams are closed."""
    for h in logger.handlers:
        s = getattr(h, "stream", None)
        if s is not None and getattr(s, "closed", False):
            return
    if hasattr(sys, "stderr") and getattr(sys.stderr, "closed", False):
        return
    if hasattr(sys, "is_finalizing") and sys.is_finalizing():
        return
    try:
        logger.info(msg)
    except Exception:
        pass


class IRLEDController:
    """
    Thread-safe controller for 850 nm IR LED illumination on GPIO18.
    
    Guarantees:
    1. Initializes strictly in the OFF state.
    2. Switches ON only during active iris acquisition.
    3. Turns OFF immediately upon scan completion, failure, cancellation, or shutdown.
    4. Automatically enforces a fail-safe maximum on-time watchdog to protect eye safety
       and prevent thermal overload if caller crashes or hangs.
    5. Clean fallback to simulated mock device when running off-Pi.
    """

    def __init__(
        self,
        pin: Optional[int] = None,
        active_high: Optional[bool] = None,
        enabled: Optional[bool] = None,
        settle_time: Optional[float] = None,
        max_on_time: Optional[float] = None
    ):
        self.pin = pin if pin is not None else config.IR_LED_GPIO_PIN
        self.active_high = active_high if active_high is not None else config.IR_LED_ACTIVE_HIGH
        self.enabled = enabled if enabled is not None else config.IR_LED_ENABLED
        self.settle_time = settle_time if settle_time is not None else config.IR_LED_SETTLE_TIME
        self.max_on_time = max_on_time if max_on_time is not None else config.MAX_SCAN_TIMEOUT_SECONDS

        self._lock = threading.RLock()
        self._is_on: bool = False
        self._turned_on_at: Optional[float] = None
        self._watchdog_timer: Optional[threading.Timer] = None
        self._device = None
        self._is_hardware: bool = False

        self._initialize_gpio()

    def _initialize_gpio(self):
        """Initializes the physical GPIO via gpiozero or falls back to mock device."""
        with self._lock:
            if not self.enabled:
                logger.info("[IR LED] Illumination disabled via configuration")
                self._is_hardware = False
                self._is_on = False
                return

            try:
                # Attempt physical gpiozero initialization
                from gpiozero import LED, BadPinFactory, GPIOZeroError
                self._device = LED(self.pin, active_high=self.active_high, initial_value=False)
                self._is_hardware = True
                self._is_on = False
                logger.info(f"[IR LED] GPIO{self.pin} initialized via gpiozero (default OFF, active_high={self.active_high})")
            except Exception as exc:
                # Running on non-Pi OS, missing pigpio/lgpio/RPi.GPIO, or dev machine
                logger.warning(f"[IR LED] Hardware GPIO{self.pin} unavailable ({exc}). Using simulated IR LED controller.")
                self._device = None
                self._is_hardware = False
                self._is_on = False

    def turn_on(self) -> bool:
        """
        Activates the IR LED.
        Starts a watchdog timer to guarantee automatic shutoff if not explicitly turned off.
        Returns True if illumination activated, False if disabled.
        """
        with self._lock:
            if not self.enabled:
                logger.info("[IR LED] Activation requested but illumination is disabled in config")
                return False

            # Cancel any existing watchdog timer
            self._cancel_watchdog()

            try:
                if self._device is not None:
                    self._device.on()
                self._is_on = True
                self._turned_on_at = time.time()
                logger.info(f"[IR LED] ON (GPIO{self.pin})")

                # Arm safety watchdog timer to enforce max on-time
                if self.max_on_time > 0:
                    self._watchdog_timer = threading.Timer(self.max_on_time, self._watchdog_expired)
                    self._watchdog_timer.daemon = True
                    self._watchdog_timer.start()

                return True
            except Exception as e:
                logger.error(f"[IR LED] Failed to turn ON: {e}")
                self._is_on = False
                return False

    def turn_off(self) -> bool:
        """
        Deactivates the IR LED and cancels watchdog timers.
        Guaranteed safe to call repeatedly.
        """
        with self._lock:
            self._cancel_watchdog()

            try:
                if self._device is not None:
                    self._device.off()
            except Exception as e:
                logger.error(f"[IR LED] Error during device.off(): {e}")
            finally:
                was_on = self._is_on
                self._is_on = False
                self._turned_on_at = None
                if was_on:
                    logger.info(f"[IR LED] OFF (GPIO{self.pin})")
                return True

    def _cancel_watchdog(self):
        """Cancels any pending watchdog timer."""
        if self._watchdog_timer is not None:
            try:
                self._watchdog_timer.cancel()
            except Exception:
                pass
            self._watchdog_timer = None

    def _watchdog_expired(self):
        """Failsafe callback: automatically forces LED OFF if max on-time elapsed."""
        logger.warning(
            f"[IR LED] SAFETY WATCHDOG EXPIRED: Force turning OFF GPIO{self.pin} after {self.max_on_time}s!"
        )
        self.turn_off()

    def is_on(self) -> bool:
        """Returns True if the IR LED is logically illuminated."""
        with self._lock:
            return self._is_on

    def get_status(self) -> Dict[str, Any]:
        """Returns comprehensive status dictionary for diagnostics and API."""
        with self._lock:
            now = time.time()
            uptime_seconds = round(now - self._turned_on_at, 2) if (self._is_on and self._turned_on_at) else 0.0
            return {
                "enabled": self.enabled,
                "pin": self.pin,
                "active_high": self.active_high,
                "is_on": self._is_on,
                "driver": "gpiozero" if self._is_hardware else "mock_simulation",
                "settle_time": self.settle_time,
                "max_on_time": self.max_on_time,
                "active_seconds": uptime_seconds
            }

    def cleanup(self):
        """
        Safe shutdown: turns off LED, cancels timers, and closes GPIO resource.
        Idempotent and safe to invoke in atexit or signal handlers.
        """
        with self._lock:
            _safe_log("[IR LED] Cleaning up IR LED controller...")
            self.turn_off()
            if self._device is not None:
                try:
                    self._device.close()
                except Exception:
                    pass
                self._device = None
            self._is_hardware = False
            _safe_log("[IR LED] Cleanup complete")


# Singleton instance
_controller_instance: Optional[IRLEDController] = None
_instance_lock = threading.Lock()


def get_ir_led_controller() -> IRLEDController:
    """Returns the shared authoritative IR LED controller instance."""
    global _controller_instance
    with _instance_lock:
        if _controller_instance is None:
            _controller_instance = IRLEDController()
        return _controller_instance
