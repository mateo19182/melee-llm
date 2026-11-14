# Architecture

How the repo is laid out, how one game runs, which process owns which display and port, and where results land. Measured costs are in [performance.md](performance.md).

## The idea in one paragraph

Everything is built on one function, `runner.play()`: it boots a Slippi Dolphin, connects two players, runs the games and saves a `.slp` replay for each. A player is an `Agent` made from a spec string such as `cpu:9`, `hal:MASTER` or `llm_paused:claude-haiku-4-5-20251001`. Each track (bench, arenas, bot-writer ladder, web jobs, pilots) is a scheduler that starts one child process per game, each with its own Slippi port and replay directory, and appends one line per game to a results file. The web UI only reads those files.

## Repo map

| Path | What |
|---|---|
| `melee_llm/paths.py` | Every location (repo root, `replays/`, `data/`, `arena/`, `vendor/`, the bot-writer home), the two X displays and each track's Slippi port block. Nothing else computes paths from `__file__` |
| `melee_llm/players.py` | `make(spec, character, log_dir=None)`: the one place a spec string becomes an Agent. Classes are imported on first use |
| `melee_llm/runner.py` | `play()`: Dolphin, controllers, menus, the frame loop, results. `replay_states()` yields game states from a `.slp` for tests without the ISO |
| `melee_llm/matches.py` | The match registry: every `play()` publishes its status and recent frames to `data/matches/` for the All matches page |
| `melee_llm/util.py` | Shared helpers: tolerant jsonl read and append, atomic file write, `port_free`, `exit_on_term`, `run_game_process` (a child game in its own process group, killed on timeout) |
| `melee_llm/match.py` | CLI for single matches: `uv run -m melee_llm.match --iso ~/melee.iso --p1 … --p2 …` |
| `melee_llm/arena.py` | Learned-bot arena, the live slot's idle filler: `python -m melee_llm.arena` |
| `melee_llm/agents/` | Player types that are not learned bots: `base.py` (the Agent contract, CPU, Idle, Multishine), `llm_common.py` with `llm_paused.py` and `llm_live.py`, `coach.py`, `jev_player.py`, `jev_coach.py` |
| `melee_llm/actions.py`, `state.py`, `vision.py`, `llm.py`, `jev.py` | What the LLM players are made of: macro-actions run frame by frame, the game state as prompt text plus an event tracker, screenshots, the OpenAI-compatible client, the TypeSafe Jev client |
| `melee_llm/bots/` | Learned bots (HAL, Phillip, MIMIC, Faynt, Reyn). `agent.py` is the parent side, `server.py` and `bot_*.py` run in each bot's own venv under `vendor/`, `protocol.py` is the pipe format between them |
| `melee_llm/bench/` | Melee Bench: `entrants.py` (registry), `scheduler.py` (active sampling), `game.py` (one game), `ratings.py`, `imports.py` (older results), `views.py` (what the web shows) |
| `melee_llm/llm_arena/` | LLM vs LLM round robins: `tournament.py`, `agent.py` (retries and frame cap), `ratings.py` (the Bradley-Terry fit the bench reuses) |
| `melee_llm/botwriter/` | LLM writes a bot: `session.py` (coding agent in a sandbox), `practice.py` (its tools), `agent.py` and `host.py` (run a submitted bot behind a time budget), `ladder.py`, `specs.py`, `dolphin.py` (port claiming), `template/`, `baselines/` |
| `melee_llm/netplay/` | Play our bots from another machine over Slippi Direct Connect |
| `melee_llm/web/` | Web UI: `server.py` (Starlette), `worker.py` (owns the live slot and the headless pool), `runjob.py` (one job), `jobs.py` (SQLite queue), `games.py` (game index), `registry.py` (reads the match registry), `live.py`, `specs.py` (launcher catalog and labels), `logs.py`, `slp.py`, `docs.py`, `static/` |
| `scripts/` | `setup.sh` (fetch Dolphin builds and vendored tools), `live.sh` (start the Xvfb displays), `dolphin-gpu.sh`, `stream.sh` and `mediamtx.yml` (live video), `viewer.py` (old replay list and MJPEG fallback on port 8767), `coach_pilot.py`, `perception_pilot.py`, `llm_dryrun.py`, `reyn_agreement.py` |
| `tests/` | Offline tests (`uv run pytest -q`): no ISO and no network. `fakesim.py` is a toy Fox physics used by the macro tests. `test_jev_bench.py` makes real Jev calls only with `JEV_BENCH=1` |
| `docs/` | These pages; the web UI's Docs tab renders every `docs/*.md` |
| `patches/slippilab.patch` | Changes to Slippi Lab: load a replay by URL, keep CPU games, post the frame to the embedding page, the live 2D renderer |

Gitignored, created by `scripts/setup.sh` or at run time: `bin/` (Dolphin AppImages, VirtualGL, mediamtx), `vendor/` (bot repos with their venvs, Slippi Lab, noVNC), `replays/`, `data/`, `arena/`.

## How a game runs

`play(agents, iso, stage, mode, games, replay_dir, slippi_port, observer, meta)`:

1. Checks that the Slippi port is free, then starts Dolphin with a temporary home directory. `mode` picks the build and the pacing:

   | Mode | Dolphin | Pacing |
   |---|---|---|
   | `watch` | rendered (mainline beta.19 through VirtualGL) | real time, never waits for input |
   | `paused`, `lockstep` | rendered | waits for every input: real time with fast players, slow motion with slow ones |
   | `fast` | headless (vladfi1 ExiAI build) | unthrottled, waits for every input |
   | `realtime` | headless | 60 fps cap, waits for every input |

   Headless Dolphins are moved to display `:98`; rendered ones use the caller's `DISPLAY` (`:99` for the live slot).
2. Connects, then calls `setup()` on every player and `ready()` on every player. A learned bot starts its model process in `setup` and waits for it in `ready`, so two bots load at the same time.
3. Walks the menus with libmelee's helper until the game starts. In-game CPUs are set on the character screen; the game is refused if it starts with the wrong CPU level.
4. On every in-game frame: `begin(gs)` for both players, then `step(gs)` for both, then the match registry sample and the caller's `observer`. A learned bot sends the frame to its model in `begin` and reads the answer in `step`, so both models compute at once.
5. At the end of a game: the result (stocks, then percent, decide a timed-out game), the replay path, `on_game_end()`. A Sudden Death after a timeout is played out but not counted.
6. On exit, including errors and SIGTERM (callers install `util.exit_on_term()`): players are closed and every process using Dolphin's temporary home is killed, so no stale Dolphin keeps the port.

`step` contract: in `paused`, `lockstep`, `fast` and `realtime` the game waits, so a step may take as long as it likes. In `watch` it must return within about 16 ms.

## Player specs

`kind[:arg[,key=value…]]`. The full list is the docstring of `melee_llm/players.py`.

| Kind | Player | Doc |
|---|---|---|
| `cpu:N` | In-game CPU, level 1 to 9 | |
| `shine`, `idle` | libmelee's multishine demo; stands still | |
| `llm_paused:<model>`, `llm_live:<model>` | LLM picking macro-actions; the game waits, or it thinks off-thread | [llm-player.md](llm-player.md), [perception.md](perception.md) |
| `hal`, `phillip`, `mimic`, `faynt`, `reyn` | Learned bots, each in a subprocess under its own venv | [bots.md](bots.md) |
| `coach:<model>` | LLM steering a learned bot (Reyn or HAL) | [coach.md](coach.md) |
| `jev_live`, `jev_paused`, `coach_jev` | TypeSafe Jev as player or coach | [jev.md](jev.md) |
| `bot:PATH`, `baseline:NAME` | A bot-writer bot, sandboxed with a per-frame time budget | [bot-writer.md](bot-writer.md) |

The web launcher keeps its own description of the kinds (`web/specs.py`: labels, argument widgets, validation). A new kind needs an entry in `players.KINDS` and one in `specs.catalog()`.

## Tracks

| Track | Entry point | Runs games as | Results | Rating |
|---|---|---|---|---|
| Single match | `python -m melee_llm.match` | in process | stdout, `replays/` | none |
| Web jobs | `web/worker.py` | `python -m melee_llm.web.runjob` per job | `data/web.sqlite`, `replays/jobs/<id>/` | none |
| Learned-bot arena | `python -m melee_llm.arena` (started by the worker) | in process, one game per process | `arena/results.jsonl`, `arena/standings.json` | sequential Elo, K = 24 |
| Melee Bench | `python -m melee_llm.bench run` | `python -m melee_llm.bench one` per game | `data/bench/`, `replays/bench/<id>/` | Bradley-Terry with a Gaussian prior, CPU 9 = 1500, bootstrap intervals |
| LLM arena | `python -m melee_llm.llm_arena run` | `python -m melee_llm.llm_arena one` per game | `data/llm-arena/<name>/` | the same fit, anchored to the CPUs |
| Bot-writer ladder | `python -m melee_llm.botwriter.ladder run` | worker processes, `games_per_side` games per Dolphin | `~/.local/share/melee-llm/botwriter/ladders/<name>/` | Bradley-Terry by MM with a virtual draw, no prior |
| Pilots | `scripts/coach_pilot.py`, `scripts/perception_pilot.py` | the script itself with `one` | `replays/coach-pilot/`, `replays/perception/` | win rates |
| Netplay | `python -m melee_llm.netplay` | in process | `replays/netplay/` | none |

The three rating methods give different numbers on purpose (the arena's Elo is order-dependent and cheap to show live; the ladder has no anchor). The bench is the one scale meant for comparing players across kinds; it imports the other tracks' games where they meet its standard ([bench.md](bench.md)).

## Displays and ports

| Resource | Owner |
|---|---|
| Display `:99` (Xvfb 1280x960, unit `melee-xvfb`) | The live slot: one rendered game at a time, streamed. Only the worker's jobs and the arena use it |
| Display `:98` (Xvfb 640x480, unit `melee-xvfb-headless`) | Every headless Dolphin (`MELEE_HEADLESS_DISPLAY` overrides), and netplay |
| Slippi port 51441 | The live slot |
| 51500-51599 | Bot-writer practice and ladder, claimed with a file lock (`botwriter/dolphin.py`, `MELEE_SLIPPI_PORTS`) |
| 51700-51799 | Web jobs in fast mode, up to 4 at once |
| 51480 onward (`--port0`) | `scripts/coach_pilot.py`; the Jev pilot ran it at 51840-51859 |
| 51860-51879 | `scripts/perception_pilot.py` |
| 51880-51919 | LLM arena |
| 51920-51999 | Melee Bench |
| 127.0.0.1:8770 | Web UI (behind Cloudflare Tunnel and Access) |
| 127.0.0.1:8554, 8888; Tailscale IP:8889 | mediamtx: RTSP in, LL-HLS out (proxied by the web UI at `/hls/`), WebRTC |
| Tailscale IP:8767 | `scripts/viewer.py` |
| 127.0.0.1:8317 | CLIProxy, the LLM endpoint (`MELEE_LLM_BASE_URL` overrides) |

The Slippi spectator port is the only resource parallel Dolphins share; libmelee gives each one its own temporary home. The port blocks are constants in `paths.py`. Only the bot-writer block is claimed across processes; the other tracks hand out ports from one scheduler process each, so two schedulers of the same track must not run at once.

## Services

Transient systemd user units, all started from the repo root (`--working-directory=$PWD`):

| Unit | Command |
|---|---|
| `melee-xvfb`, `melee-xvfb-headless` | started by `scripts/live.sh` |
| `melee-mediamtx` | `bin/mediamtx scripts/mediamtx.yml`; it starts `scripts/stream.sh` while someone watches |
| `melee-web` | `python -m melee_llm.web.server` |
| `melee-arena` | `python -m melee_llm.web.worker --iso ~/melee.iso` (the worker; the arena is its idle filler) |
| `melee-bench` | `python -m melee_llm.bench run --budget 100 --target 125` |
| `melee-viewer` | `python scripts/viewer.py` |

The code is imported from the working tree, not installed: a running scheduler starts each new game with whatever code is on disk at that moment. Restart the long-running units after pulling a change that moves or renames modules.

## Where results land

| Location | Content |
|---|---|
| `replays/**/*.slp` | One replay per game. Next to it, `<replay>.p<port>.llm.jsonl` or `.coach.jsonl`: the player's decision log |
| `data/matches/*.json` | Match registry, one file per running `play()`; ended ones are pruned by the web server |
| `data/live.json` | What the live slot shows right now |
| `data/web.sqlite` | Web jobs, their results and token counts, settings |
| `data/bench/`, `data/llm-arena/<name>/`, `arena/` | `results.jsonl` (append-only, one line per game) and `standings.json` |
| `~/.local/share/melee-llm/botwriter/` | Sandboxes, sessions and ladders (`BOTWRITER_HOME` overrides) |

Results files are append-only jsonl; readers skip a line that was cut by a crash or is still being written (`util.read_jsonl`). Status files that a page polls are written to a temporary name and renamed.

## Environment variables

| Variable | Effect |
|---|---|
| `MELEE_ISO` | Default ISO path for the worker and the bot-writer (`~/melee.iso`) |
| `MELEE_LLM_BASE_URL`, `MELEE_LLM_API_KEY`, `CLIPROXY_API_KEY` | LLM endpoint and key |
| `TYPESAFE_API_KEY`, `TYPESAFE_BASE_URL` | Jev |
| `MELEE_MATCHES=0`, `MELEE_MATCHES_DIR` | Turn the match registry off, or move it |
| `MELEE_HEADLESS_DISPLAY` | Display for headless Dolphins (`:98`) |
| `MELEE_SLIPPI_PORTS` | Bot-writer port block (`51500-51599`) |
| `MELEE_WEB_DATA`, `BOTWRITER_HOME` | Move `data/` or the bot-writer home |
| `BIND`, `PORT` | Web server and viewer address |

## Adding things

- **A player kind**: an `Agent` subclass (`setup`, `step`, optionally `ready`, `begin`, `on_game_start`, `on_game_end`, `close`), an entry in `players.KINDS`, and one in `web/specs.py` if the launcher should offer it. For the bench, an entry in `bench/entrants.py`.
- **A track**: build players with `players.make`, run each game in a child with `util.run_game_process`, take a port from a new block in `paths.py`, append results with `util.append_jsonl`, pass `meta={"source": …, "label": …}` to `play()` so the game shows on All matches. To list its games with players and results, add its results file to `web/games.py`.

## Known duplication, left in place

- **Two live-status channels.** `web/live.py` writes `data/live.json` for the Live page, and `matches.py` writes the registry for All matches. Both sample the same game. The registry already marks the live slot (`live_slot`), so the Live page could read it and `live.json` could go; the stream overlay and the steer state would have to move with it.
- **Three rating implementations** (see Tracks). Merging the ladder or the arena into the bench's fit would change published numbers.
- **The pilots keep their own launch loop** (`scripts/coach_pilot.py`, `scripts/perception_pilot.py`): a 20-second kill grace and a retry on "could not connect" that `util.run_game_process` does not have.
- **Spec knowledge in two places**: `players.KINDS` builds players, `web/specs.py` labels and validates them.
