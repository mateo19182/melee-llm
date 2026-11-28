---
id: E36
title: Our own model: Yoshi fine-tune
date: 2026-11-28
status: running
result: running
verdict: pending
runs: own-yoshi-ft
prs: 127
follows: E35
---

## Question

Stage 2 of the [plan](../own-model.md): does fine-tuning the all-character base (E35) on Yoshi's games alone make a better Yoshi, at no delay and at 12 frames? This model is where RL starts (stage 3), so the answer also picks RL's starting weights.

## Setup

`own.train own-yoshi-ft --init` E35's `own-pre-10m-b/ckpt/step-0793457`, with `--character YOSHI --boost 2`:

- **Data:** only Yoshi's side of the games with a Yoshi in them (73.5k sides in HAL's dataset, about 0.6 billion frames). Games won by a Master or a pro are used twice per pass.
- **Budget:** 1 billion frames (122,070 steps of batch 32, about 5 hours), so each game is seen one to two times.
- **Learning rate:** peak 3e-5 after 500 warm-up steps, cosine decay to 10%. E35 ended at 1e-5.
- Everything else as E35: both delays (`--delays 0,12`), float32, the rollback guard. Validation every 2,000 steps on 240 held-out Yoshi sides; a weight folder every 10,000 steps.

## Judged by

Yoshi in the farm at 64 games per match (`train/own/eval-yoshi.sh`), the fine-tune and the base in the same matches so they compare directly:

- **Validation loss on Yoshi** per delay, against the base's at step 0. A loss that rises while training loss falls means the 73.5k sides are being memorised; then an earlier weight folder is the result.
- **Fine-tune against the base,** both with code 14 at no delay and 15 at 12 frames.
- **Against Faynt's 10M Base** at no delay (the base won 58 of 64 with code 18).
- **At 12 frames** against `yoshi-rl-3-ladder` step 1795 at the same delay (the base won 25 of 64) and Phillip's Yoshi (0 of 64).
- **Name code:** Master winner (14 and 15) against pro winner (18 and 19) in the Faynt Base and RL Yoshi matches. aMSa is the one pro Yoshi, so here the pro code may be the better one.
- **Dolphin league** for the final choice: Yoshi at no delay against CPU 9 and against `hal-amsa-yoshi` (the best imitation Yoshi so far, 385 Elo), 24 games each.

## Result

## Verdict
