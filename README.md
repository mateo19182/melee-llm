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
./live.sh                      # Xvfb :99 as user service melee-xvfb
DISPLAY=:99 uv run match.py --iso ~/melee.iso --p1 cpu:9 --p2 cpu:9
DISPLAY=:99 uv run match.py --iso ~/melee.iso --p1 llm_paused:claude-haiku-4-5-20251001 --p2 cpu:5 --mode paused
```

Open http://m19182:8889/live/ for the main live view. It's a WebRTC stream from mediamtx, H.264 encoded on the GPU with NVENC at 60 fps and 4 Mbit/s. mediamtx runs as the user service `melee-mediamtx` with config `scripts/mediamtx.yml`, and starts `scripts/stream.sh` only while someone watches. That stream is cropped to Dolphin's game window.

http://m19182:8767/watch is the fallback: an MJPEG stream of Dolphin's game window at about 60 fps, served by `viewer.py` and bound only to the Tailscale IP. `VNC=1 ./live.sh` also starts a noVNC view on :6080, which is interactive but laggy.

Players are `cpu:N`, `shine` (libmelee's multishine demo), `idle`, `llm_paused:<model>` or `llm_live:<model>`. The LLM players are described in [docs/llm-player.md](docs/llm-player.md). There are three modes:

- `--mode watch`: real time, rendered.
- `--mode paused`: the game waits for each input, so slow players such as LLMs can think.
- `--mode fast`: headless and unthrottled; it only produces replays.

## Replays

`replays/` gets one `.slp` per game. The viewer runs as a transient user service:

```sh
systemd-run --user --unit=melee-viewer --working-directory=$PWD $PWD/.venv/bin/python viewer.py
```

Open http://m19182:8767/list. Port 8766 is taken by another service on this host.

## Tracks

- LLM plays: see [docs/llm-player.md](docs/llm-player.md).
- LLM writes bots: see [docs/bot-writer.md](docs/bot-writer.md).
- Learned bots (HAL, Faynt, MIMIC, Phillip), which serve as ladder opponents and as the body an LLM coach steers: see `docs/bots.md`.

## Arena

`arena.py` runs the learned bots and a level-9 CPU back to back on display :99, in lockstep at about 60 fps. Each game uses the least-played pairing, random characters (Fox, Falco, Marth or Falcon) and a random legal stage. It writes a strip under the stream with the matchup and Elo, and results go to `arena/results.jsonl` and `arena/standings.json`. Standings are at http://m19182:8767/arena.

```sh
systemd-run --user --unit=melee-arena --working-directory=$PWD --setenv=DISPLAY=:99 $PWD/.venv/bin/python arena.py --iso ~/melee.iso
systemctl --user stop melee-arena
```
