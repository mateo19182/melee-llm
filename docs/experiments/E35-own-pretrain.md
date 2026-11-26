---
id: E35
title: Our own model: all-character pretrain
date: 2026-11-25
status: running
result: running
verdict: pending
runs: own-pre-10m, own-pre-10m-b, own-diverge-bf16, own-diverge-f32
prs: 121, 124
follows: E34
---

## Question

Stage 1 of the [plan](../own-model.md): the base model for every character, at no delay and at 12 frames, from all of HAL's dataset. How much stronger is it than the gate model (E34), which saw 1 billion frames and no labels?

## Setup

`own.train` as in E34's mixed run (Faynt's 10M architecture from random weights, each window at 0 or 12 frames of delay, batch 32, learning rate 3e-4 with a cosine decay to 10%), with two changes:

- **8 billion frames** instead of 1 billion: 976,562 steps, about 30% of one pass over the 26 billion perspective-frames. At the measured 58,000 frames a second that is 38 hours on the 3090.
- **Labels as inputs.** The name code now carries the player's rank (Platinum, Diamond, Master, or the pro of a pro folder) and whether they won the game, as well as the delay: 20 codes (`python -m own.data 0,12` prints them). The model learns from every game and in play we ask for a winning pro or Master. HAL steers the same way and Faynt ends its training on Master winners.

The winner is the player with more stocks on the game's last frame, then less percent. Weight folders are written every 20,000 steps.

### The first run diverged (11-25)

`own-pre-10m` broke at step 216,300 of 976,562 and ran on unwatched for 14 hours. Best validation loss was 0.796 at step 135,000; from step 185,000 the button loss crept up, at 216,300 the gradient norm went from 0.25 to 2 to 10 within 500 steps, and by step 220,000 the button loss had doubled (0.29 to 0.57) while the stick loss stayed at 0.52. Stopped at step 553,200 on 11-26.

What the checkpoints show: the button logits have no fixed level and drifted down at a steady rate, the mean top logit going from -14 at step 60,000 to -27, -40 and -49 at steps 140,000, 180,000 and 200,000, then to -955 at 220,000 with their spread up from 8.5 to 221. The run computed in bfloat16, whose steps are 0.25 between 32 and 64 and 0.5 above 64. Faynt's released models are float32.

Two side runs test whether the precision is the cause: `own-diverge-bf16` and `own-diverge-f32`, both from the step-200,000 weights at the learning rate of that step (2.7e-4), differing only in the compute precision, guard off.

### The restart: own-pre-10m-b

From the step-180,000 weights of the first run (validation 0.804), a new optimizer, float32 (the same speed here: 56,000 frames a second), peak learning rate 1e-4 with 2,000 warm-up steps and a cosine decay over 6.5 billion frames (793,457 steps, about 33 hours). Final weight folder: `step-0793457`.

`own.train` now guards itself: the state at the last healthy validation is kept, and a validation loss 8% over the best, or a gradient norm 6 times its recent median for 300 steps, sends the run back to it at half the learning rate; after 4 of these it stops. Validation also logs the level and spread of the button logits, and every weight folder holds the optimizer state, so a run can be resumed from any of them.

## Judged by

All at 64 games in the farm unless said (`train/own/eval.sh`), then the Dolphin league for the final checkpoint.

- Validation loss per delay on the same 240 held-out games as E34 (0.784 at no delay, 0.796 at 12 frames).
- **Which code plays best:** pro winner, Master winner and Master loser, as Fox against Faynt's 10M Base at no delay. If winner and loser codes play the same, the labels carry nothing.
- **Against the gate model,** both at no delay and both at 12 frames, as Fox and as Yoshi.
- **Against Faynt's 10M Base** at no delay, as Fox and as Yoshi (the gate model won 27 and 35 of 64).
- **At 12 frames** as Yoshi against `yoshi-rl-3-ladder` step 1795 at the same delay (the gate model won 7 of 64) and Phillip's Yoshi (0 of 64).
- **Dolphin league:** Fox at no delay against CPU 9, 24 games (the gate model won 14 of 24, Faynt's 10M Base 10 of 12), then the Fox roster at 12 games each. A clear win over CPU 9 is the bar E34 left open.

## Result

## Verdict
