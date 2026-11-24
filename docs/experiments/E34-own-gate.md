---
id: E34
title: Our own model: the gate
date: 2026-11-24
status: running
result: running
verdict: pending
runs: own-gate-d0, own-gate-mix
prs:
follows: E13, E33
---

## Question

Before anything is scaled up ([plan](../own-model.md), stage 0): does a model trained from scratch with our own code play properly in closed loop, where our earlier pipeline held its inputs and lost to CPU 9 (E11 to E13)? And what does telling the model its input delay cost at no delay?

## Setup

`own.train`: Faynt's 10M architecture (5 layers, width 384, 256-frame context, 10.2M parameters) from random weights, without the Fountain of Dreams platform input (HAL's dataset does not have it) and with a name-code input that carries the delay. AdamW, learning rate 3e-4 with 1,000 warm-up steps and a cosine decay to 10%, batch 32 windows of 256 frames, bfloat16.

Data: all of HAL's dataset (1.3M games, every character and rank), both sides of each game, in 256-frame windows. Mang0's and M2K's own sides are left out (slippi-ai's opt-out list). `own.hal` turns a dataset row into the model's inputs; on real ranked replays it agrees with slippi-ai's live parser on 99.3 to 100% of frames per field, the rest being rollback frames where the dataset keeps the final version.

At delay D the model reads the game at frame t and the pad applied at t + D, and predicts the pad for t + D + 1.

Two runs of 1 billion frames, differing only in the delays:

- **own-gate-d0:** delay 0 only.
- **own-gate-mix:** each window at 0 or 12 frames, the model told which.

## Judged by

- Validation loss per delay (nats per frame) on 240 held-out games. Faynt reports 0.798 for its 10M Base on its own test set.
- In closed loop at no delay, in the farm and then Dolphin: Fox against CPU 9 (HAL's 20M Fox wins 95%), and the share of frames on which the stick changes (humans 22.9%, our failed models 8.6%).
- `own-gate-mix` against `own-gate-d0`, both at no delay: the cost of the delay input.
- `own-gate-mix` at 12 frames against E33's last checkpoint at the same delay.

## Result

## Verdict
