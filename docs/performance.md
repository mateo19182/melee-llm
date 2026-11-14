# Performance

What a game costs, what limits throughput, what was changed and what is not worth changing. Every number here was measured on m19182 (Ryzen 9 5950X, 32 threads, RTX 3090) on 2026-11-14 while the bench, a bot-writer ladder and an LLM arena were running: the load average was between 18 and 51, so absolute numbers are pessimistic and noisy. Comparisons were run back to back on the same load.

## Summary

| Change | Before | After |
|---|---|---|
| Start of a game process without an LLM player (imports) | 1.25 s | 0.3 s |
| HAL plus MIMIC: process start to first game frame | 24.7 s | 19.5 s |
| HAL vs Phillip in fast mode, frames per second | 89 | 98 |
| Web UI game index rebuild (1,240 replays) | 0.74 s | 0.23 s |

The machine, not the code, is the main limit on throughput: with every track running, 32 threads carried a load of 35 to 50.

## How many games at once

Level-9 CPU against level-9 CPU in fast mode (Dolphin only, no bot, no GPU), N copies started together, frames per wall second over 25 s. The machine was already at load 30 to 40 from other work:

| Games at once | Per game | All games together |
|---|---|---|
| 1 | 254 fps | 254 fps |
| 4 | 231 fps | 925 fps |
| 8 | 170 fps | 1,361 fps |
| 16 | 84 fps | 1,348 fps |
| 24 | 38 fps | 920 fps |

One unthrottled Dolphin fills about two cores, so 8 of them fill the 16 physical cores. From 8 to 16 the total does not grow, each game only gets slower. At 24 the total falls by a third and every game runs below 60 fps: at that point a real-time game on the same machine cannot hold its speed, and the bench throws it away as `slow`. A run with 32 did not get all its games started in three minutes.

So every track takes a machine-wide slot before it starts an unthrottled game (`util.claim_slot`): 8 slots here, `MELEE_UNTHROTTLED_GAMES` to change it. The bench (its bot-vs-bot games), the bot-writer ladder and fast web jobs wait for one; before, each track had only its own limit (3, 8 workers and 4), which add up to 15. Real-time games and LLM games where the emulator waits for the model take no slot, since their Dolphin is mostly idle. Bot-writer practice games take none either: the writing agent's tool call has a time limit that a wait would eat. Games between two learned bots count as one slot each although they are bound by inference, not by Dolphin (98 fps for HAL vs Phillip); how many of those fit was not measured.

## Starting a game

Time from process start to the first in-game frame, fast mode:

| Players | Seconds | Where it goes |
|---|---|---|
| CPU vs CPU | 3.5 | Dolphin boot and connect 1.0, menus 2.2, Python imports 0.2 |
| HAL vs CPU | 20.6 | HAL's model process 17 (documented as 12 on an idle machine: torch import, weights, CUDA-graph capture), the rest as above |
| HAL vs MIMIC | 19.5 | the slower of the two loads, since they now load together; 24.7 before |

Stopping takes about 1 s (closing the bots, killing Dolphin).

Two changes:

- **Player classes are imported on first use** (`players.py`). The OpenAI client alone took 0.7 s of the old 1.25 s, in every game process, including bot-vs-bot games that never call an LLM.
- **Learned bots load in parallel.** `setup()` starts the model process and `ready()` waits for it; the runner calls `setup` on both players, then `ready` on both. With two bots the cost is the slower load, not the sum.

What is left is the model load itself, once per game process. Every scheduler starts one process per game, so a bot game pays 5 to 17 s before it starts. See "Not done" below.

## Per frame

In fast mode nothing throttles the game, so the frame time is Dolphin plus everything Python does.

HAL vs Phillip, 3,700 frames after warm-up, two back-to-back runs per version:

| | Run 1: fps (ms per frame) | Run 2: fps (ms per frame) |
|---|---|---|
| Before: bots stepped one after the other | 89.1 (11.2) | 38.5 (26.0) |
| After: both get the frame, then both answer | 98.1 (10.2) | 63.1 (15.8) |

Run 2 hit a load spike; the direction is the same in both. In run 1 the two round trips were 4.9 and 3.1 ms before, so about 3.3 ms per frame is Dolphin, the Slippi parse and the runner. After the change the frame costs about the slower bot plus that. The two models slow each other down a little when they run together (each round trip rose by 1 to 3 ms), which is why the gain is 10% and not the 25% the arithmetic suggests.

How it works: `Agent.begin(gs)` is called for both players before either `step(gs)`. A learned bot sends the frame to its model process in `begin` and reads the answer in `step`. A coach forwards `begin` to the bot it steers. Callers that only call `step` still work: `step` sends first if `begin` was not called.

Other per-frame costs, for scale:

- The match registry (`matches.py`) reports its own cost as `overhead_us` in each `data/matches/*.json`: about 30 µs per frame in lockstep. It samples at most 60 times per second and writes at most 15 times per second, on a thread.
- LLM players build prompts only when they decide, not per frame; their decision log is flushed per decision.
- A learned bot's frame is one pickle over a pipe each way. The child parses the raw Slippi events again with its own libmelee build; that is deliberate, since each bot was trained against a specific parser.

## Web UI

Measured against the live data (1,240 replays, 42 bench results, 97 arena games, 18 running matches):

| Path | Cost | Note |
|---|---|---|
| Game index rebuild | 0.23 s, was 0.74 s | at most every 15 s, on demand; see below |
| Match registry scan | 4 ms | per SSE tick (10 per second while a Matches page is open), shared between clients for 80 ms |
| Bench board, entrant page | under 10 ms | read from `standings.json` |
| Ladder boards | 0.2 s first time, 4 ms after | cached on the games file's mtime |
| Arena, coach, sessions pages | 1 to 30 ms | |
| Worker: token count of a running job | 30 ms per 1.8 MB decision log | every 5 s per running job |

The game index (`web/games.py`) joins every `.slp` under `replays/` and the ladders with whichever results file knows it. It used to glob the replay's directory for decision logs and resolve symlinks once per replay and once per results row. Now it lists each directory once, takes the logs from the same listing, resolves only symlinks, and remembers resolved result paths. The output was compared record by record against the old code on the live data and is identical. It still grows linearly with the number of replays; at ten times today's count a rebuild would take about 2 s, at which point it should become incremental (keyed on directory mtimes).

Browser side: periodic refreshes (`lib.js` `every()`) now pause while the tab is hidden and run once when it is shown again; a job page stops refreshing once the job has finished. The "on air" indicator does the same.

## Schedulers

Measured on a copy of the bench's data (35 active entrants, 42 results, 938 imported games):

| Step | Cost | How often |
|---|---|---|
| `pick()`: both tracks' fits and every candidate pairing | 24 ms | each time a slot is free, at most every 5 s |
| `standings()` with 300 bootstrap resamples | 0.8 s | at most every 2 min |
| `nvidia-smi`, `systemctl is-active` | 27 ms, 5 ms | per `pick()` |

None of this limits the bench: a game takes minutes. The one part that would grow is `est_tokens`, which scanned every result for each of about 1,700 calls per `pick()`; it is now computed once per entrant until the next result arrives.

What does limit the bench is deliberate: one new game per 20 s (`stagger_s`, because Dolphin boots and model loads are CPU-heavy), the load cap (`load_cap`, 36), and the slots per kind of game. They are fields of `bench/scheduler.py` `Config`; `--parallel`, `--load-cap`, `--slots`, `--provider-slots` and `--stagger` set the main ones.

## Not done, in order of expected payoff

1. **Keep bots and Dolphin up across games.** `play(games=N)` already reuses both, but every scheduler starts one process per game, and the arena changes players each game. A fast bot-vs-bot game pays 5 to 20 s of start-up for 2 to 5 minutes of play, so by that arithmetic the ceiling is 5 to 10% more games per hour; for the live arena it would cut the 14 to 30 s gap between games to the menu time. It needs either batches of the same pairing per process (simple, but the bench picks one game at a time on purpose) or model servers that outlive a game (a real change to `bots/`).
2. **Incremental game index**, when the replay count makes the rebuild slow.
3. **Incremental token counts in the worker** (remember the byte offset per decision log). Today it re-reads each log every 5 s: 30 ms for the largest log seen. Only worth it with many long LLM jobs at once.
4. **Per-frame micro-costs** in the macro executor and the controller writes (a few microseconds each against 3 to 10 ms frames): not worth the risk.

## How to measure

- Game throughput: run `python -m melee_llm.match --mode fast` with `MELEE_MATCHES=0` and divide the result's `frames` by `seconds`; a learned bot's `latency()` gives its round trip and model time per frame.
- A learned bot alone, without the ISO: `python -m melee_llm.bots.bench <bot> <replay.slp>` ([bots.md](bots.md)).
- Registry overhead: `overhead_us` in any `data/matches/*.json`.
- Web paths: call the function behind the endpoint (`games.INDEX.get()`, `bench.views.board()`, `registry.scan()`) under `cProfile`. Point `MELEE_MATCHES_DIR` at a copy before calling `registry.scan()`: it prunes ended matches.
