#!/usr/bin/env bash
# ==============================================================================
# LifeLink 2.0 - Touchscreen Kiosk Launcher Script
# Target: Raspberry Pi 5 with Wayland / X11 Chromium Touch Terminal
# ==============================================================================

set -euo pipefail

# 1. Disable screen blanking, screensaver, and power management
xset s off || true
xset -dpms || true
xset s noblank || true

# 2. Hide cursor after 1 second of inactivity if unclutter is installed
if command -v unclutter &>/dev/null; then
    unclutter -idle 0.5 -root &
fi

# 3. Wait until the local LifeLink 2.0 backend responds on port 5000
echo "Waiting for LifeLink 2.0 backend on http://127.0.0.1:5000..."
until curl -s http://127.0.0.1:5000/api/v1/health | grep -q "healthy"; do
    sleep 0.5
done
echo "LifeLink 2.0 backend is online!"

# 4. Launch Chromium in locked touchscreen kiosk mode
# Ensures no crash bubbles, no update checks, no pinch-to-zoom disruptions
exec chromium-browser \
    --kiosk \
    --noerrdialogs \
    --disable-infobars \
    --check-for-update-interval=31536000 \
    --disable-pinch \
    --overscroll-history-navigation=0 \
    --enable-features=OverlayScrollbar \
    --touch-events=enabled \
    --disable-session-crashed-bubble \
    --disable-features=TranslateUI \
    --disable-component-update \
    --fast \
    --fast-start \
    --app=http://127.0.0.1:5000
