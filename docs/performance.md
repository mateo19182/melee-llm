# Performance

Measured on m19182 (Ryzen 9 5950X, 32 threads, RTX 3090) on 2026-11-14 while the bench, a bot-writer ladder and an LLM arena were running. The load average was 18 to 51, so absolute numbers are pessimistic and noisy. Comparisons ran back to back on the same load.

## Summary

| Change | Before | After |
|---|---|---|
| Start of a game process without an LLM player (imports) | 1.25 s | 0.3 s |
| HAL plus MIMIC: process start to first game frame | 24.7 s | 19.5 s |
| HAL vs Phillip in fast mode, frames per second | 89 | 98 |
| Web UI game index rebuild (1,240 replays) | 0.74 s | 0.23 s |

The machine, not the code, is the main limit on throughput: with every track running, 32 threads carried a load of 35 to 50.

## How many games at once

Level-9 CPU against level-9 CPU in fast mode (Dolphin only, no bot, no GPU), N copies started together, frames per wall second over 25 s, with the machine already at load 30 to 40 from other work:

| Games at once | Per game | All games together |
|---|---|---|
| 1 | 254 fps | 254 fps |
| 4 | 231 fps | 925 fps |
| 8 | 170 fps | 1,361 fps |
| 16 | 84 fps | 1,348 fps |
| 24 | 38 fps | 920 fps |

One unthrottled Dolphin fills about two cores, so 8 fill the 16 physical cores and more games only make each one slower. At 24 no game reaches 60 fps: a real-time game on the same machine cannot hold its speed, and the bench throws it away as `slow`.

So every track takes a machine-wide slot before it starts an unthrottled game (`util.claim_slot`): 8 slots here, changed with `MELEE_UNTHROTTLED_GAMES`.

- **Wait for a slot:** the bench's bot-vs-bot games, the bot-writer ladder and fast web jobs.
- **Take no slot:** real-time games and LLM games where the emulator waits for the model, since their Dolphin is mostly idle. Bot-writer practice games take none either: the writing agent's tool call has a time limit that a wait would eat.
- **Two learned bots** count as one slot per game although inference, not Dolphin, bounds them (98 fps for HAL vs Phillip). How many of those fit was not measured.

## Starting a game

Time from process start to the first in-game frame, fast mode:

| Players | Seconds | Where it goes |
|---|---|---|
| CPU vs CPU | 3.5 | Dolphin boot and connect 1.0, menus 2.2, Python imports 0.2 |
| HAL vs CPU | 20.6 | HAL's model process 17 (12 on an idle machine), the rest as above |
| HAL vs MIMIC | 19.5 | the slower of the two loads: learned bots load in parallel |

Stopping takes about 1 s. Player classes are imported on first use (`players.py`), so a game that never calls an LLM does not pay for the LLM clients.

What is left is the model load: every scheduler starts one process per game, so a bot game pays 5 to 17 s before it starts (item 1 under "Not done").

## Per frame

In fast mode nothing throttles the game, so the frame time is Dolphin plus everything Python does. HAL vs Phillip runs at 98 fps (10.2 ms per frame): about 3.3 ms for Dolphin, the Slippi parse and the runner, plus the slower of the two bots, since both think at once. Under a load spike the same game ran at 63 fps.

The contract behind that: the runner calls `Agent.begin(gs)` for both players before either `step(gs)`. A learned bot sends the frame to its model process in `begin` and reads the answer in `step`. Callers that only call `step` still work.

Other per-frame costs, for scale:

- The match registry (`matches.py`) reports its own cost as `overhead_us` in each `data/matches/*.json`: about 30 µs per frame in lockstep.
- LLM players build prompts only when they decide, not per frame.
- A learned bot's frame is one pickle over a pipe each way. The child parses the raw Slippi events again with its own libmelee build, deliberately: each bot was trained against a specific parser.

## Web UI

Measured against the live data (1,240 replays, 42 bench results, 97 arena games, 18 running matches):

| Path | Cost | Note |
|---|---|---|
| Game index rebuild (`web/games.py`) | 0.23 s | at most every 15 s, on demand |
| Match registry scan | 4 ms | per SSE tick (10 per second while a Matches page is open), shared between clients for 80 ms |
| Bench board, entrant page | under 10 ms | read from `standings.json` |
| Ladder boards | 0.2 s first time, 4 ms after | cached on the games file's mtime |
| Arena, coach, sessions pages | 1 to 30 ms | |
| Worker: token count of a running job | 30 ms per 1.8 MB decision log | every 5 s per running job |

The game index grows linearly with the number of replays: at ten times today's count a rebuild would take about 2 s, at which point it should become incremental (keyed on directory mtimes). In the browser, periodic refreshes pause while the tab is hidden.

## Schedulers

Measured on a copy of the bench's data (35 active entrants, 42 results, 938 imported games):

| Step | Cost | How often |
|---|---|---|
| `pick()`: both tracks' fits and every candidate pairing | 24 ms | each time a slot is free, at most every 5 s |
| `standings()` with 300 bootstrap resamples | 0.8 s | at most every 2 min |
| `nvidia-smi`, `systemctl is-active` | 27 ms, 5 ms | per `pick()` |

None of this limits the bench, where a game takes minutes. Its real limits are deliberate: one new game per 20 s (`stagger_s`, because Dolphin boots and model loads are CPU-heavy), the load cap (`load_cap`, 36), and the slots per kind of game. They are fields of `bench/scheduler.py` `Config`; `--parallel`, `--load-cap`, `--slots`, `--provider-slots` and `--stagger` set the main ones.

## Not done, in order of expected payoff

1. **Keep bots and Dolphin up across games.** Every scheduler starts one process per game, so a fast bot-vs-bot game pays 5 to 20 s of start-up for 2 to 5 minutes of play: the ceiling is 5 to 10% more games per hour, and a shorter gap between live arena games (14 to 30 s today). It needs batches of the same pairing per process, or model servers that outlive a game (a real change to `bots/`).
2. **Incremental game index**, when the replay count makes the rebuild slow.
3. **Incremental token counts in the worker.** Only pays with many long LLM jobs at once.
4. **Per-frame micro-costs** in the macro executor and the controller writes (a few microseconds each against 3 to 10 ms frames): not worth the risk.

## How to measure

- **Game throughput:** run `python -m melee_llm.match --mode fast` with `MELEE_MATCHES=0` and divide the result's `frames` by `seconds`. A learned bot's `latency()` gives its round trip and model time per frame.
- **A learned bot alone, without the ISO:** `python -m melee_llm.bots.bench <bot> <replay.slp>` ([bots.md](bots.md)).
- **Registry overhead:** `overhead_us` in any `data/matches/*.json`.
- **Web paths:** call the function behind the endpoint (`games.INDEX.get()`, `bench.views.board()`, `registry.scan()`) under `cProfile`. Point `MELEE_MATCHES_DIR` at a copy before calling `registry.scan()`: it prunes ended matches.
