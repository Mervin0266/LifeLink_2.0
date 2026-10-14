# ==============================================================================
# LifeLink 2.0 - ESP32 MicroPython Boot Initialization
# ==============================================================================
import gc
import esp

# Disable ESP OS debug output to prevent serial bus interference on USB CDC
esp.osdebug(None)

# Collect garbage at boot
gc.collect()
