# Melee Bench

One rating scale for every kind of player: built-in CPUs, learned bots, scripted and LLM-written bots, LLMs playing directly, Jev, LLM coaches of Reyn, and later Mateo over netplay. The web UI's **Bench** page (`/bench`) shows it, with a page per entrant.

```sh
uv run python -m melee_llm.bench entrants                 # the registry
uv run python -m melee_llm.bench imports                  # which older games count, and why the others don't
uv run python -m melee_llm.bench standings                # recompute data/bench/standings.json (1000 bootstraps)
uv run python -m melee_llm.bench recount                  # recount token spend from the decision logs (see Budget)
uv run python -m melee_llm.bench run --target 125    # the fill (resumable); runs as unit melee-bench
```

## The standard game

Fox vs Fox, Battlefield or Final Destination (stages and ports alternate per pairing), 4 stocks, 8-minute timer, a full game. A time-out goes to the player with more stocks, then lower percent. Other characters and stages would be separate boards.

## Two tracks

| Track | Who | How the game runs |
|---|---|---|
| **Real time** | `llm_live:<model>`, `jev_live`, `coach:<model>`, `coach_jev`, `coach:random` | `realtime` mode: headless Dolphin capped at 60 fps. The game never waits, so latency costs game time, as for a human. |
| **Untimed** | `llm_paused:<model>`, `jev_paused` | `fast` mode: the game waits for every decision. Measures decision quality only. |
| **Both** | CPUs, learned bots, scripted and LLM-written bots | Token-free players play identically in both modes. Their games run in `fast` mode and count on **both** boards. |

The shared games tie the two scales together, so a live and a paused LLM can be compared though they never meet.

**Slow games are not rated.** The runner waits for a late bot, so an overloaded machine slows the game and gives a wall-clock player extra game time per decision. A real-time game with a mean below **50 fps** is marked `slow`: kept, not rated, and the pairing stays available. On the loaded machine `realtime` held 59.6-60.4 fps.

Written bots keep their 16 ms per-frame wall budget (`BotAgent`) in every mode.

## Entrants

The registry is `melee_llm/bench/entrants.py`.

| Category | Entrants | Notes |
|---|---|---|
| CPU | `cpu:1,3,5,7,9` scheduled; `cpu:2,4,6,8` from imports only | `cpu:9` is the anchor, 1500 |
| Learned bot | `phillip:silver`, `phillip:plat`, `phillip:gm`, `hal:MASTER`, `mimic`, `faynt` (10M-Arena), `reyn` (no command) | Phillip tiers give graded anchors above the CPUs |
| Scripted bot | `baseline:laser`, `rusher`, `shine` | The bot-writer's reference bots |
| LLM-written bot | `written:<session name>`: every bot-writer session of 10+ minutes with a `final/bot.py` | Picked up automatically from `~/.local/share/melee-llm/botwriter/sessions/` |
| LLM player | `llm_live:<m>` and `llm_paused:<m>` for Haiku 4.5, Sonnet 5.5, gpt-6-luna, gpt-6.1-sol | Default options (`interval=30`, JSON, `effort=none`) |
| Jev player | `jev_live`, `jev_paused` | Default options |
| Coach → Reyn | `coach:<m>` for the four models, `coach_jev`, `coach:random` (control) | `interval=300` (one call per 5 s), as in the coach and Jev pilots |
| Human | `human:mateo` | Reserved slot, see below |

## Rating method

Each track is a Bradley-Terry fit (`melee_llm/bench/ratings.py`) over its `ok` games, on the Elo scale (400 points ≈ 10:1 odds), with **`cpu:9` pinned at 1500** on both boards. A draw is half a win, and a prior keeps undefeated records finite.

The 95% interval shown is the wider of the bootstrap and the Laplace estimate, because the bootstrap alone is too narrow for a perfect record. An entrant is "converged" when the half-width is at most the target (default ±125).

Port and stage are not in the model; the scheduler balances them per pairing.

## Imported games

`melee_llm/bench/imports.py` reads older results in place and tags them `imported`. A game counts only if it is the standard game between two bench entrants with the bench's spec options and, with a wall-clock player, ran at 50+ fps.

| Source | What counts |
|---|---|
| Bot-writer ladders (`ladders/*/games.jsonl`, fast mode) | Most of the imported games. Forfeits and self-play are excluded. |
| Coach and Jev pilots (`replays/{coach,jev}-pilot/*/results.jsonl`, lockstep) | Uncoached Reyn games (a bot is unaffected by fps). Most coach games ran at 15-45 fps and are excluded. Fixed-command Reyn and `interval=60` coaches are not bench entrants. |
| LLM arena (`data/llm-arena/*/results.jsonl`) | Games were capped at one minute, so only the few that ended before the cap. |
| Learned-bot arena (`data/arena/results.jsonl`) | Random characters and stages, so only its Fox dittos on BF/FD. |

The page lists the excluded counts by reason under "Older games not imported".

## Scheduler: active sampling, no token cap

Whenever a slot is free, the scheduler (`melee_llm/bench/scheduler.py`, unit `melee-bench`) starts the pairing whose next game would narrow the unconverged entrants' intervals most per unit of expected cost (tokens plus machine time). So close ratings and wide intervals win, free games are played often, and expensive LLMs play where they still need games, against opponents near their level. The maths is in the module's docstring and code.

Resource limits (defaults, `run --help`):

- **Games at once:** at most 14, including up to 3 unthrottled token-free, 6 real-time and 8 untimed-LLM games.
- **LLM sides in flight:** 6 per provider (`claude`, `gpt`) and 4 for Jev.
- **GPU:** 6 GPU bot processes, and 1.5 GB free VRAM per GPU bot (Reyn, HAL, MIMIC, Phillip).
- **Load:** a CPU-heavy game (real-time or unthrottled) starts only while the 1-minute load plus its own share stays under 36, an untimed LLM game up to 40. At least 2 games always run, since other services set most of the load.
- **Stagger:** 20 s after the previous start.
- **LLM arena:** while the `melee-llm-arena` unit runs, at most 3 token-spending games.
- **Unthrottled bot games** run under `nice` and wait for one of the machine's slots for unthrottled games ([performance.md](performance.md)).

**Stopping.** The run stops when every active entrant is converged (95% CI within `--target`) or no longer narrowing (20 more games would gain less than `--min-gain`, 5 Elo), or when nothing fits and nothing runs for 30 minutes. An entrant whose last three bench games all failed (crash, CUDA OOM, API outage) sits out for an hour. Restarting resumes from `results.jsonl`, spend included.

**Budget and spend.** There is no token cap by default; `--budget` (millions of CLIProxy tokens, games in flight counted at their estimate) adds one. Only CLIProxy tokens (Claude and GPT models) count toward it. Jev is billed to its own TypeSafe key at about a cent per game and reported in USD. The page shows spend per provider and per entrant.

**Every call counts.** A reply that is never applied still costs tokens: a live player drops replies that are older than `max_stale` frames or superseded, and a call can be in flight when the game ends. These are logged as `dropped` records with their usage and added to the side's tokens. Calls that fail in transport return no usage and stay uncounted (5 of ~5,600 coach calls). The entrant page shows `discarded_rate` (dropped / all replies).

**Recount of the overnight run.** Before 2026-11-14 the `dropped` records carried no usage, so the overnight run counted only applied replies: **100.1M CLIProxy tokens counted, 115.1M actually spent** (Claude 69.8M, GPT 45.4M). It stopped at its 100M cap; that cap is gone. `bench recount` re-reads the logs, estimates each old dropped reply at its log's mean tokens per applied call, and writes `recount.json`; `results.jsonl` is not rewritten. The standings and the page use the recount, and `status.json` has it as `spent_recounted` next to `spent`. Discarded rates in that run: GPT-6.1 Sol live 95%, Sonnet live 35%, gpt-6-luna live 23%, `jev_live` 7%, Haiku live 5%; coaches and paused players drop none.

## Isolation and files

Each game is `python -m melee_llm.bench one` in its own process group, with its own Slippi port (51920-51999) and replay dir `replays/bench/<game id>/` (replay, decision logs, `stderr.log`), on the headless display `:98`. It never touches `:99` or port 51441. A wall timeout (25 min, 3 h for untimed LLM games) kills the group, Dolphin included. A game where a side's calls failed more than 10% of the time is `void`: kept, not rated.

| File (`data/bench/`, gitignored) | What |
|---|---|
| `results.jsonl` | Append-only, one line per finished game, with status `ok`, `void`, `slow`, `error` or `timeout`. Fields: `melee_llm/bench/game.py` |
| `standings.json` | Both boards, spend per entrant, the registry, import counts. Rewritten by the scheduler at most every 2 min |
| `status.json` | Scheduler progress: phase, spend, running games, unconverged entrants, recent log lines |
| `recount.json` | Per game and side, token counts re-read from the logs by `bench recount` |

Bench games also appear on All matches (source `bench`) and in Games, where the replay page plays them with their decision logs.

## Adding an entrant

Add an `Entrant` to `registry()` in `entrants.py` and restart the unit. The scheduler sees a wide interval and plays the new entrant first, against opponents near the board's middle. Examples:

```python
# a janky variant of the live player: decides every 10 frames, drops replies older than 40
Entrant("llm_live:claude-haiku-4-5-20251001,interval=10", "Haiku 4.5 live (jumpy)", "llm", "realtime",
        "llm_live:claude-haiku-4-5-20251001,interval=10,max_stale=40", "Haiku live with a short leash.",
        provider="claude"),
# a fixed-command Reyn
Entrant("reyn:lasers", "Reyn lasers", "learned", "both", "reyn:Keep your distance and shoot lasers.",
        "Reyn holding one command all game.", gpu=True),
```

Any spec `melee_llm/players.py` understands works, including the bot-writer's `bot:PATH` and `baseline:NAME`. A wall-clock kind (`llm_live`, `jev_live`, `coach`, `coach_jev`) makes the entrant real-time automatically. New bot-writer sessions show up as `written:` entrants on the next start.

## Mateo via netplay

`human:mateo` is reserved (inactive, no spec). To rate him, play games against bench entrants over Slippi Direct Connect ([netplay.md](netplay.md)) under the standard rules and append them to `results.jsonl` with `p1`/`p2` ids, `mode: "netplay"`, `track: "realtime"` and the result. The scheduler does not start these games.

## Results

The bench has finished. Final numbers are in [status.md](status.md), and the Bench page shows the standings.
