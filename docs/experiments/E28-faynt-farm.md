---
id: E28
title: Faynt in the simulator farm: exactness, agreement with Dolphin, speed
date: 2026-11-18
status: done
result: Faynt plays in the farm with inputs identical to Dolphin's (85,260 seat-frames), mirror results match E27, and 8 processes run 6,337 frames a second, about 60 times the Dolphin league
verdict: use the farm for Faynt-vs-Faynt evaluation and as the rollout engine for Yoshi RL; opponents other than Faynt still need Dolphin
runs:
prs:
follows: E27
---

## Question

E27 took 3.4 hours for 187 Dolphin games, and Faynt-style RL needs millions of frames. Can Faynt play many games at once in the simulator, seeing exactly what it sees on Dolphin, and how fast?

## Setup

`train/faynt/farm.py` runs one simulator batch (melee-brute) and one batched model step per Faynt checkpoint. Each seat's input goes through the same path as the live bot: simulator row → libmelee `GameState` (`melee_llm.sim.state`) → slippi-ai `Parser` → Faynt's tensors. The chosen controller goes back through `SimController`, which produces the integers Dolphin would read.

Two changes to Faynt's inference, both checked against its own code (`train/tests/test_faynt_farm.py`):
- **Batched cache.** Faynt's cached attention loops over the batch in Python (two `.item()` reads and a gather per game per layer). It is replaced by one indexed write and a validity mask. Softmax attention does not depend on key order, so this is the same function. Over 300 frames, with the 256-frame ring wrapping and games restarting mid-run, the logits differ by at most 5e-5 and the argmax agrees everywhere.
- **CUDA graph.** The step is recorded once and replayed every frame. Faynt checks its inputs with Python reads of GPU tensors and builds small constant tables each step. A warm-up step on valid inputs records those answers and tables, and the recording replays them. Button logits are identical to the eager step (difference 0.0 over 300 frames).

One fix outside the farm: `melee_llm.sim.state.StateBuilder` did not fill in Fountain of Dreams' platform heights, which libmelee reads from Slippi events. Faynt reads them.

## Judged by

- **Inputs:** `python -m faynt.parity` encodes every farm frame as Slippi events, rebuilds it with libmelee's Console as `bots/server.py` does for the live bot, and compares every field of slippi-ai's Game.
- **Outcomes:** the Arena-vs-Expert mirrors from E27 (Dolphin, 8 games each), replayed in the farm with UCF on, as in our Dolphin.
- **Speed:** game frames a second, with two Faynt models in each process.

## Result

**Inputs:** 85,260 seat-frames over all six stages (Yoshi vs Fox, so eggs and lasers included): every field equal, once the Fountain of Dreams fix was in.

**Outcomes** (Arena wins, mean stock lead):

| Mirror | Dolphin (E27) | Farm, eager step | Farm, CUDA graph |
|---|---|---|---|
| Yoshi | 8/8, +2.6 | 63/64, +2.52 | 252/256, +2.41 |
| Fox | 8/8, +4.0 | 64/64, +3.91 | 64/64, +3.81; 512/512, +3.88 |
| Marth | 8/8, +3.4 | 64/64, +3.23 | |
| Falco | 8/8, +3.5 | 64/64, +3.25 | |

The first eager Yoshi run (62/64, +2.5) came before the Fountain of Dreams fix. The other runs above include it.

**Speed** (frames a second; the Dolphin league ran about 107):

| Setup | Upstream cache | Batched cache | CUDA graph |
|---|---|---|---|
| 1 process, 64 games | about 360 (profiled) | 1,141 | 2,061 |
| 4 processes × 16 games | | about 800 | |
| 4 × 64 | | | 4,844 |
| 8 × 64 | | | **6,337** |
| 4 × 128 | | | 5,465 |

Without the graph, extra processes only queued on the GPU's many small kernel launches. With it, 8 processes of 64 games are fastest.

## Verdict

The farm is exact where it can be checked and agrees with Dolphin on every mirror, about 60 times faster than the Dolphin league. Use it for Faynt-vs-Faynt evaluation and as the rollout engine for RL. Limits: only Faynt plays in it (HAL, Phillip and CPUs still need Dolphin), the simulator's RNG is not Dolphin's, and per-game Python (state building, parsing) is now the main cost if more speed is needed.
