#!/usr/bin/env bash
# Virtual displays :99 (rendered Dolphin, streamed) and :98 (headless jobs). Watch at https://melee.m19182.dev,
# http://m19182:8889/live/ (WebRTC, tailnet) or http://m19182:8767/watch (MJPEG via scripts/viewer.py).
# VNC=1 also starts x11vnc + noVNC on :6080, laggy but interactive, useful for debugging menus.
# Then run: DISPLAY=:99 uv run -m melee_llm.match --iso <path>
set -euo pipefail
cd "$(dirname "$0")/.."
BIND=${BIND:-100.83.166.6}
systemctl --user is-active -q melee-xvfb || { systemctl --user reset-failed melee-xvfb 2>/dev/null || true;
  systemd-run --user --unit=melee-xvfb --description="Xvfb :99 for Melee" Xvfb :99 -screen 0 1280x960x24 >/dev/null; }
systemctl --user is-active -q melee-xvfb-headless || { systemctl --user reset-failed melee-xvfb-headless 2>/dev/null || true;
  systemd-run --user --unit=melee-xvfb-headless --description="Xvfb :98 for headless Melee jobs" Xvfb :98 -screen 0 640x480x24 >/dev/null; }
sleep 1
if [ "${VNC:-0}" = 1 ]; then
  pgrep -f "x11vnc -display :99" >/dev/null || x11vnc -display :99 -localhost -forever -shared -nopw -quiet -bg -o /tmp/melee-x11vnc.log
  pgrep -f "websockify.*6080" >/dev/null || (uv run websockify --web vendor/noVNC "$BIND:6080" localhost:5900 >/tmp/melee-novnc.log 2>&1 &)
  echo "vnc: http://m19182:6080/vnc.html?autoconnect=1&resize=scale"
fi
echo "live: https://melee.m19182.dev · http://m19182:8889/live/ · http://m19182:8767/watch"
