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

The web UI (below) is the main live view. On the tailnet, http://m19182:8889/live/ is the lowest-latency one. It's a WebRTC stream from mediamtx, H.264 encoded on the GPU with NVENC at 60 fps and 4 Mbit/s. mediamtx runs as the user service `melee-mediamtx` with config `scripts/mediamtx.yml`, and starts `scripts/stream.sh` only while someone watches. That stream is cropped to Dolphin's game window.

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
- Play our bots yourself over Slippi Direct Connect from another machine: see [docs/netplay.md](docs/netplay.md).
- Learned bots (HAL, Faynt, MIMIC, Phillip), which serve as ladder opponents and as the body an LLM coach steers: see `docs/bots.md`.

## Web UI

https://melee.m19182.dev (Cloudflare Tunnel + Access, owner only) serves `melee_llm/web/` from 127.0.0.1:8770. The app has no auth of its own, so it refuses to bind all interfaces.

- **Live**: the stream of display :99 as LL-HLS, proxied same-origin from mediamtx (`/hls/`), with a broadcast scorebug and a decision feed. The feed shows each decision of `llm_paused`/`llm_live` players (state text, action, reason, latency, staleness, tokens), each coach call (command, rationale, router reply) and the steer state of learned bots. It tails the live game's decision logs over SSE. Every event carries the wall-clock time it happened (`ts`, added by `DecisionLog`), and HLS segments carry `EXT-X-PROGRAM-DATE-TIME` from the same clock, so the page holds events until the video has played that far. "Instant" shows them on arrival, dimmed until the video catches up. Per player, the newest decision the video has reached is marked "on screen". Click an entry for the full state and reply.
- **All matches**: every game running on this host, live, whoever started it (web jobs, the arena, bot-writer ladders, coach pilots, scripts). Each `runner.play()` publishes `data/matches/<pid>-<port>-<start ms>.json` (`melee_llm/matches.py`): source and label, players, stage, mode, score, speed in game frames per second, decision-log paths, results and a ring of recent compact frames (position, facing, action state, percent, stocks, shield, flags). It is rewritten at most 15 times per wall second, off the game loop on a thread; the per-frame cost is measured into `overhead_us` (about 30 µs in lockstep). `play(meta={...})` names the caller; otherwise the source is guessed from the replay dir and argv. `MELEE_MATCHES=0` turns it off. The server (`registry.py`) marks a match whose process died as crashed and forgets ended ones after 3 hours. The page (`/matches`, SSE `/api/matches/events`, list `/api/matches`) plays each match's frames back about 0.35 s behind with Slippi Lab's character renderer (`src/live/renderer.ts` from `patches/slippilab.patch`, built to `dist/live-renderer.js` by `npm run build:live`). Cards show a ×N badge for games faster than real time, the latest LLM or coach decision, and links to the focus view (`/matches/<id>`), the replay and the job; the live slot's card shows the HLS video, with a 2D toggle. Ended games move to "Recently finished".
- **Launch**: pick both players from every registered spec, characters (checked per bot: Phillip models' characters, MIMIC checkpoints), stage, mode and number of games. Models come from the CLIProxy `/v1/models`. Jobs, their results and LLM token spend (with a list-price estimate) are in `data/web.sqlite` (gitignored); replays and decision logs of job N go to `replays/jobs/N/`.
- **Games**: every `.slp` under `replays/` and the bot-writer ladders, with players and results from whichever results file knows the game; a game page embeds Slippi Lab and the decision log as a timeline. The patched Slippi Lab posts its frame to the page and accepts seeks (`patches/slippilab.patch`), so the current decision follows the replay and clicking a decision jumps to the state the model saw.
- **Arena**, **Coach** (pilot summaries), **Bot-writer** (sessions with cost, time and bot source; ladder boards computed with `botwriter.ladder.leaderboard`), **Play vs bot** (placeholder for netplay).

The frontend is plain ES modules with no build step (`melee_llm/web/static/`). One stylesheet, `style.css`, holds the look: Melee-style menu chrome for the setup pages, a broadcast HUD on the live page, P1 red, P2 blue and one cyan highlight. Headings use Barlow Condensed and body text Barlow, both under the SIL OFL and vendored in `static/vendor/fonts/`.

Two user services run it:

```sh
# web server
systemd-run --user --unit=melee-web --working-directory=$PWD --setenv=BIND=127.0.0.1 --setenv=PORT=8770 \
    $PWD/.venv/bin/python -m melee_llm.web.server
# worker: owns the live slot (display :99, Slippi port 51441) and the headless pool
systemd-run --user --unit=melee-arena --working-directory=$PWD --setenv=DISPLAY=:99 \
    $PWD/.venv/bin/python -m melee_llm.web.worker --iso ~/melee.iso
```

The worker runs queued live jobs (lockstep or paused) one at a time on :99. When none is queued, the arena fills the slot one game at a time; a queued job waits for the arena game to end, or aborts it if "start now" was ticked. The arena can be switched off from the UI. Fast jobs run headless on :98, up to 4 at once, on Slippi ports 51700-51799. Each job is `python -m melee_llm.web.runjob` in its own process group, so cancelling one kills its Dolphin and bots. The process on the live slot writes `data/live.json` (players, score, decision-log paths, steer state) and the overlay strip under the video. To take :99 for a manual `match.py` run, switch the arena off and wait for the slot to go idle.

## Arena

`arena.py` runs the learned bots and a level-9 CPU on display :99, in lockstep at about 60 fps. Each game uses the least-played pairing, random characters (Fox, Falco, Marth or Falcon) and a random legal stage. It writes the overlay strip with the matchup and Elo, and results go to `arena/results.jsonl` and `arena/standings.json`. The worker above starts it with `--games 1 --no-retry` whenever the live slot is free; standalone, `DISPLAY=:99 uv run arena.py --iso ~/melee.iso` loops forever (stop the worker first). Standings are on the Arena page, and still at http://m19182:8767/arena (`viewer.py`, Tailscale only).

Each arena game starts a fresh Dolphin, so about 14-30 s pass between games (Dolphin boot, bot setup, menus). Keeping Dolphin up across games was considered and left out: `runner.play()` binds one set of agents for all its games, while every arena game changes the pairing, characters and which ports are CPUs. Reusing Dolphin would need a session API in the runner that every caller shares, and switching ports between CPU and human on the character screen, which libmelee's menu helper does not reliably do. Even then, the results and character screens still cost about 10 s per game.
