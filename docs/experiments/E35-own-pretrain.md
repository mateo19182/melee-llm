---
id: E35
title: Our own model: all-character pretrain
date: 2026-11-25
status: running
result: running
verdict: pending
runs: own-pre-10m
prs:
follows: E34
---

## Question

Stage 1 of the [plan](../own-model.md): the base model for every character, at no delay and at 12 frames, from all of HAL's dataset. How much stronger is it than the gate model (E34), which saw 1 billion frames and no labels?

## Setup

`own.train` as in E34's mixed run (Faynt's 10M architecture from random weights, each window at 0 or 12 frames of delay, batch 32, learning rate 3e-4 with a cosine decay to 10%), with two changes:

- **8 billion frames** instead of 1 billion: 976,562 steps, about 30% of one pass over the 26 billion perspective-frames. At the measured 58,000 frames a second that is 38 hours on the 3090.
- **Labels as inputs.** The name code now carries the player's rank (Platinum, Diamond, Master, or the pro of a pro folder) and whether they won the game, as well as the delay: 20 codes (`python -m own.data 0,12` prints them). The model learns from every game and in play we ask for a winning pro or Master. HAL steers the same way and Faynt ends its training on Master winners.

The winner is the player with more stocks on the game's last frame, then less percent. Weight folders are written every 20,000 steps.

## Judged by

All at 64 games in the farm unless said, then the Dolphin league for the final checkpoint.

- Validation loss per delay on the same 240 held-out games as E34 (0.784 at no delay, 0.796 at 12 frames).
- **Which code plays best:** pro winner, Master winner and Master loser, as Fox against Faynt's 10M Base at no delay. If winner and loser codes play the same, the labels carry nothing.
- **Against the gate model,** both at no delay and both at 12 frames, as Fox and as Yoshi.
- **Against Faynt's 10M Base** at no delay, as Fox and as Yoshi (the gate model won 27 and 35 of 64).
- **At 12 frames** as Yoshi against `yoshi-rl-3-ladder` step 1795 at the same delay (the gate model won 7 of 64) and Phillip's Yoshi (0 of 64).
- **Dolphin league:** Fox at no delay against CPU 9 and the Fox roster, 12 games each.

## Result

## Verdict
