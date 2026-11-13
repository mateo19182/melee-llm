# melee-llm

Experiments with LLMs playing Super Smash Bros. Melee through [libmelee](https://github.com/vladfi1/libmelee) (vladfi1's maintained fork, `pip install melee`) and Slippi Dolphin.

## Requirements

- Your own **NTSC 1.02 vanilla** Melee ISO (not UnclePunch/20XX). It is not in the repo and never downloaded.
  Its md5 is `0e63d4223b01d9aba596259dc155a174`.
- Run `scripts/setup.sh`. It fills the gitignored `bin/` and `vendor/` folders:
  - `Slippi_Mainline.AppImage`: project-slippi mainline beta.19, rendered, used to watch.
  - `Slippi_Mainline_ExiAI.AppImage`: vladfi1 ExiAI mainline beta.14.1, headless and unthrottled.
  - VirtualGL.
  - noVNC.
  - Slippi Lab, with `patches/slippilab.patch` applied. The patch lets `?replayUrl=` select the loaded replay, and keeps CPU and non-legal games, which upstream silently drops.

Rendered modes run Dolphin through `scripts/dolphin-gpu.sh`. VirtualGL's EGL backend renders on the NVIDIA GPU and copies the frames into the Xvfb display, so no root and no real X server are needed. Plain Xvfb renders on the CPU at about 3 fps in game; this setup runs at 60 fps.

## Watch a match live

```sh
./live.sh                      # Xvfb :99 → x11vnc (localhost) → noVNC on the Tailscale IP
DISPLAY=:99 uv run match.py --iso ~/melee.iso --p1 cpu:9 --p2 cpu:9
```

Open http://m19182:6080/vnc.html?autoconnect=1&resize=scale. The page has no password and is bound only to the Tailscale IP.

Players are `cpu:N`, `shine` (libmelee's multishine demo) or `idle`. There are three modes:

- `--mode watch`: real time, rendered.
- `--mode paused`: the game waits for each input, so slow players such as LLMs can think.
- `--mode fast`: headless and unthrottled; it only produces replays.

## Replays

`replays/` gets one `.slp` per game. The viewer runs as a transient user service:

```sh
systemd-run --user --unit=melee-viewer --working-directory=$PWD $PWD/.venv/bin/python viewer.py
```

Open http://m19182:8767/list. Port 8766 is taken by another service on this host.
