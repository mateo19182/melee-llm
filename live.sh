#!/usr/bin/env bash
# Virtual display :99 → VNC (localhost only) → noVNC in the browser on the Tailscale IP.
# Then run: DISPLAY=:99 uv run match.py --iso <path>
set -euo pipefail
cd "$(dirname "$0")"
BIND=${BIND:-100.83.166.6}
pgrep -f "Xvfb :99" >/dev/null || (Xvfb :99 -screen 0 1280x800x24 >/tmp/melee-xvfb.log 2>&1 &)
sleep 1
pgrep -f "x11vnc.*:99" >/dev/null || x11vnc -display :99 -localhost -forever -shared -nopw -quiet -bg -o /tmp/melee-x11vnc.log
pgrep -f "websockify.*6080" >/dev/null || (uv run websockify --web vendor/noVNC "$BIND:6080" localhost:5900 >/tmp/melee-novnc.log 2>&1 &)
echo "live view: http://m19182:6080/vnc.html?autoconnect=1&resize=scale"
