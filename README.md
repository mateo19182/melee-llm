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
scripts/live.sh                      # Xvfb :99 as user service melee-xvfb
DISPLAY=:99 uv run -m melee_llm.match --iso ~/melee.iso --p1 cpu:9 --p2 cpu:9
DISPLAY=:99 uv run -m melee_llm.match --iso ~/melee.iso --p1 llm_paused:claude-haiku-4-5-20251001 --p2 cpu:5 --mode paused
```

The web UI (below) is the main live view. On the tailnet, http://m19182:8889/live/ is the lowest-latency one. It's a WebRTC stream from mediamtx, H.264 encoded on the GPU with NVENC at 60 fps and 6 Mbit/s. mediamtx runs as the user service `melee-mediamtx` with config `scripts/mediamtx.yml`, and starts `scripts/stream.sh` only while someone watches. It captures Dolphin's game window at native size (1168x960, 73:60): on :99, `runner.Console` opens that window at that size from Qt's saved geometry and moves it to (0, 0), since VirtualGL can't follow a resize after launch.

http://m19182:8767/watch is the fallback: an MJPEG stream of Dolphin's game window at about 60 fps, served by `scripts/viewer.py` and bound only to the Tailscale IP. `VNC=1 scripts/live.sh` also starts a noVNC view on :6080, which is interactive but laggy.

Players are spec strings such as `cpu:N`, `hal:MASTER`, `llm_paused:<model>` or `coach:haiku,body=reyn`; `melee_llm/players.py` lists them all. There are five modes:

- `--mode watch`: real time, rendered.
- `--mode paused`: the game waits for each input, so slow players such as LLMs can think.
- `--mode lockstep` (the default): rendered like `paused`; with fast bots it runs at real time.
- `--mode fast`: headless and unthrottled; it only produces replays.
- `--mode realtime`: headless like `fast`, but capped at 60 fps and waiting for slow inputs (lockstep without rendering); the bench's real-time track uses it.

## Replays

`replays/` gets one `.slp` per game. The viewer runs as a transient user service:

```sh
systemd-run --user --unit=melee-viewer --working-directory=$PWD $PWD/.venv/bin/python scripts/viewer.py
```

Open http://m19182:8767/list. Port 8766 is taken by another service on this host.

## Tracks

- **Melee Bench**: one leaderboard for every kind of player (CPUs, learned, scripted and LLM-written bots, LLMs, Jev, LLM coaches), a real-time and an untimed board anchored to CPU 9 = 1500, filled by an active-sampling scheduler under a token budget: see [docs/bench.md](docs/bench.md).
- LLM plays: see [docs/llm-player.md](docs/llm-player.md).
- Screenshots instead of, or next to, the text state: see [docs/perception.md](docs/perception.md).
- LLM coach steering a learned bot: see [docs/coach.md](docs/coach.md).
- LLM vs LLM arena: rated round robins of `llm_paused` models: see [docs/llm-arena.md](docs/llm-arena.md).
- LLM writes bots: see [docs/bot-writer.md](docs/bot-writer.md).
- Jev (TypeSafe System One) picks macros or coaches Reyn: see [docs/jev.md](docs/jev.md).
- Play our bots yourself over Slippi Direct Connect from another machine: see [docs/netplay.md](docs/netplay.md).
- Background on Melee, the history of its bots, tooling, community and people: see [docs/research.md](docs/research.md).
- A decomp-based simulator: games without Dolphin (`--mode sim`), checked frame for frame against Dolphin and libmelee: see [docs/simulator.md](docs/simulator.md).
- Learned bots (HAL, Faynt, MIMIC, Phillip), which serve as ladder opponents and as the body an LLM coach steers: see [docs/bots.md](docs/bots.md).

## Web UI

https://melee.m19182.dev (Cloudflare Tunnel + Access, owner only) serves `melee_llm/web/` from 127.0.0.1:8770: the Melee Bench boards, the live stream with a decision feed, every match running on this host, a launcher, all replays with their decision logs, and these docs (the Docs tab renders `docs/*.md`). Pages, services and the live slot are described in [docs/web-ui.md](docs/web-ui.md).

## Code and development

[docs/architecture.md](docs/architecture.md) maps the repo: how a game runs, which process owns which display and port block, and where results land. [docs/performance.md](docs/performance.md) has the measured costs and what limits throughput.

```sh
uv sync                 # includes pytest and ruff (dev group)
uv run pytest -q        # offline: no ISO, no network; tests needing the git-ignored replays/sample-slippi-js-*.slp skip without them
uv run ruff check .
```
