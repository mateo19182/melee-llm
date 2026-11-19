---
id: E29
title: Phillip and HAL in the farm
date: 2026-11-18
status: done
result: Phillip and HAL play in the farm with live-path inputs; 9 of 11 pairings matched Dolphin, and the two Phillip pairings that did not were a Dolphin bug (analog triggers off, E30): with it fixed, Dolphin matches the farm
verdict: use the farm for Faynt, Phillip and HAL; it reproduces the game better than our Dolphin did before E30
runs:
prs:
follows: E28
---

## Question

E28 put Faynt in the farm. Can Phillip and HAL join, so Faynt's Yoshi can be evaluated and trained against them there, and does the farm then agree with Dolphin?

## Setup

`train/farm/` (renamed from `train/faynt/`): one coordinator (`farm/run.py`, Faynt's venv) and one brain per model.
- **Faynt** steps in the coordinator's process, as in E28.
- **Phillip** (`farm/phillip.py`) runs in slippi-ai's venv as a helper process (`farm/remote.py`). It uses slippi-ai's own `DelayedAgent`, built as the live bot builds it, with one row per seat. The published ONNX exports take one game at a time. `farm/phillip_onnx.py` rewrites a copy to take a batch: the reshapes that bake in the batch of 1, and the squeeze that reads the temperature. Each copy is checked row for row against the original before use, and its outputs are bit-identical. On the CPU with 4 threads, 64 seats take 4.9 ms a step.
- **HAL** (`farm/hal.py`) runs in HAL's venv with HAL's batched evaluator adapter, as in `haltrain.farm`. Its GameStates come from the Slippi events, parsed by its own libmelee fork: the fork builds HAL's observations from parsed event data, which a GameState built field by field does not carry.

Two fixes on the way:
- With two stages, lane parity tied each port to one stage. Games 2k and 2k+1 now share a stage.
- Phillip's conversion is locked so workers starting together convert a model once.

## Judged by

- **Inputs:** `--check` rebuilds every frame from Slippi events, as the live bots see Dolphin, and compares what Faynt and Phillip read.
- **Outcomes:** farm win rates against Dolphin for pairings with Dolphin results: the bench (Fox dittos on Battlefield and Final Destination), E27, and new Dolphin runs. All farm runs use UCF on, which matches our Dolphin: its default codes include UCF 0.84 with the 1.0 cardinals, and the simulator always applies the other UCF fixes.

## Result

**Inputs:** every field equal for Faynt and Phillip, over every checked run. HAL reads the event path itself.

**Outcomes** (first player's wins; the farm uses 64 games per pairing):

| Pairing | Farm | Dolphin |
|---|---|---|
| HAL Master vs Phillip plat | 55/64 | 18/22 (bench) |
| Phillip gm vs Phillip plat | 64/64 | 45/45 (bench) |
| Faynt Arena Fox vs Phillip gm | 64/64 | 349/349 (bench) |
| Faynt Expert Fox vs HAL Master Fox | 9/64 | 5/30 (E27, five HAL characters) |
| Faynt Expert Fox vs Phillip gm | 4/64 | 2/24 (new) |
| Faynt Arena Yoshi vs Phillip anti-Yoshi Fox | 4/64 | 0/6 (E27) |
| Faynt Arena Yoshi vs Phillip Yoshi (trained vs Fox) | 53.5/64 | 4/6 (E27) |
| Faynt Arena Yoshi vs HAL as aMSa | 57/64 | 6/6 (E27) |
| Faynt Expert Yoshi vs HAL as aMSa | 14/64 | 2/6 (E27) |
| Faynt Arena Yoshi vs HAL Master Fox | 43/64 | 4/6 (E27) |
| **HAL Master vs Phillip gm** | **8/64 (12%)** | **21/71 (30%; bench 14/47, new 7/24)** |
| **Faynt Arena Yoshi vs Phillip anti-Yoshi Marth** | **7/64 (11%)** | **9/23 (39%, new; E27's 5/6 was a small sample)** |

**The two gaps are not from the farm.** Single-game simulator mode (`melee_llm.match --mode sim`), where each bot runs its own unbatched live code, shows the same thing: HAL beat Phillip gm in 1 of 16 games on Battlefield from port 1, and Faynt beat the Marth in 2 of 12.

**Ruled out:**
- **UCF:** Dolphin's default codes match the simulator with `--ucf`.
- **Timing:** Dolphin's fast mode blocks on every input.
- **The controller path:** 12,590 random stick values sent through Dolphin reached the game as exactly the integers `SimController` computes, one frame later.
- **Phillip's batching:** the converted graph is bit-identical row for row.

**Narrowed:** against a third player each bot measures the same in both places (Faynt Expert vs HAL, vs Phillip gm, Faynt vs Phillip's other agents). So the gap appears only in some matchups, and in both Phillip is stronger in the simulator.

**Speed:** 650 to 3,700 frames a second per run with 2 to 4 workers. Phillip-only pairings are slowest (two CPU brains). HAL's 250M model needs about 3 to 5 GB of GPU memory per worker, so HAL runs fit 2 to 4 workers next to other GPU jobs.

## Verdict

Phillip and HAL play in the farm exactly as they play in the simulator. The farm agreed with Dolphin on 9 of 11 pairings, and on every pairing without Phillip.

**Update, E30:** the two gaps were a bug in our Dolphin, not the simulator. The headless build read every analog trigger below full as 0, so analog shields and airdodges never happened on Dolphin. With the trigger fix, Dolphin gives HAL vs Phillip gm 3/24 and Faynt's Yoshi vs the anti-Yoshi Marth 2/24, matching the farm's 8/64 and 7/64. The farm needs no change. Use it for Faynt, Phillip and HAL, and treat Dolphin results from before E30 as played without analog triggers.
