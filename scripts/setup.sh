#!/usr/bin/env bash
# Fetch the gitignored runtime pieces: Dolphin builds, VirtualGL, noVNC, patched Slippi Lab.
# The Melee ISO is never fetched: bring your own NTSC 1.02 dump.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p bin vendor
gh_dl() { [ -f "$2" ] || curl -fsSL -o "$2" "$1"; }

gh_dl https://github.com/project-slippi/dolphin/releases/download/v4.0.0-mainline-beta.19/Slippi_Netplay_Mainline-x86_64.AppImage bin/Slippi_Mainline.AppImage
gh_dl https://github.com/vladfi1/dolphin/releases/download/4.0.0-mainline-beta.14.1-ExiAI/Slippi_Netplay_Mainline_ExiAI_NoLeak-x86_64.AppImage bin/Slippi_Mainline_ExiAI.AppImage
chmod +x bin/*.AppImage

if [ ! -d bin/vgl ]; then
  curl -fsSL -o /tmp/vgl.deb https://github.com/VirtualGL/virtualgl/releases/download/3.1.5/virtualgl_3.1.5_amd64.deb
  dpkg -x /tmp/vgl.deb bin/vgl && rm /tmp/vgl.deb
fi

[ -x bin/mediamtx ] || curl -fsSL https://github.com/bluenviron/mediamtx/releases/download/v1.21.3/mediamtx_v1.21.3_linux_amd64.tar.gz | tar -xz -C bin mediamtx
[ -d vendor/noVNC ] || git clone -q --depth 1 https://github.com/novnc/noVNC.git vendor/noVNC
if [ ! -d vendor/slippilab ]; then
  git clone -q https://github.com/frankborden/slippilab.git vendor/slippilab
  git -C vendor/slippilab apply ../../patches/slippilab.patch
fi
(cd vendor/slippilab && npm ci --no-audit --no-fund && npx vite build)
uv sync
echo "ready. ISO: NTSC 1.02, md5 0e63d4223b01d9aba596259dc155a174"
