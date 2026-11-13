#!/usr/bin/env bash
# Rendered Slippi Dolphin on the NVIDIA GPU via VirtualGL's EGL backend (no root, no real X server).
# Frames are read back into the X display in $DISPLAY (the Xvfb :99 that live.sh starts).
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export LD_LIBRARY_PATH="$ROOT/bin/vgl/usr/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
exec "$ROOT/bin/vgl/opt/VirtualGL/bin/vglrun" -d egl "$ROOT/bin/Slippi_Mainline.AppImage" "$@"
