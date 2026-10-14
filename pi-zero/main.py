"""
LifeLink 2.0 - Camera Daemon Entry Point
Launches the Pi Zero W camera service daemon.
"""

import sys
import logging
from camera_service import app, config

logger = logging.getLogger("LifeLink.Main")

def main():
    logger.info("==================================================")
    logger.info("LifeLink 2.0 - Camera & 850nm IR LED Daemon")
    logger.info(f"Target: Raspberry Pi Zero W (USB Gadget: {config.HOST}:{config.PORT})")
    logger.info(f"IR LED: GPIO{config.IR_LED_GPIO_PIN} (Active High: {config.IR_LED_ACTIVE_HIGH})")
    logger.info("==================================================")
    app.run(host=config.HOST, port=config.PORT, debug=False)

if __name__ == "__main__":
    main()
