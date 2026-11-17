---
id: E23
title: Delay: imitate the no-delay model on our own delayed games
date: 2026-11-17
status: running
result:
verdict:
runs: hal-dida-1
prs:
follows: E22
---

## Question

E22 showed that more imitation of human data does not help under delay. Does the bot get better at 10 frames of delay if it plays with that delay and is then trained, on those games, toward what the no-delay model would have done seeing the present?

This is DIDA (Liotet et al. 2022; see [delay.md](../delay.md)): play with delay, label every step with an undelayed expert's action in the true current state, train on the learner's own games. It needs no reward and gives a label on every frame.

## Setup

**Games.** `hal:AMSA#0,return_target=40` at 9, 10 and 11 frames of delay (stomped needs 10 and lands pads a frame late in stretches), 8 games per delay against each of 12 opponents, 288 games:
- HAL as a Master-rank player on Fox, Falco, Marth, Sheik and Peach, and HAL as aMSa on Yoshi;
- Phillip's Platinum, Diamond, Master and Grandmaster Fox;
- MIMIC Marth and CPU 9 Fox.

Phillip's agents trained against Yoshi and its `super-gm` Fox are kept out of training, so they stay an untouched test.

**Data path.** `haltrain/own.py` turns the replays into HAL's training batches with HAL's own extraction, return labels and window code, in memory, with our bot as the player. Checked on the 60 delay-10 games from E22: 57 convert (3 are too short or torn), and the released model scores them at 0.9 to 1.2 bits per frame, as it does human games.

**Loss.** For a position t in one of our games and delay d, the student is the model's output for d+1 frames ahead, given the game up to t and the d actions that were on their way (which is exactly what it had when it played). The label is an action sampled from the frozen released model's "1 ahead" output given the game up to t+d, with the same steering. The loss is the student's negative log-likelihood of that label, on outputs d+1 and d+2 (the two it executes between replans).

**Mix.** Each update is two microbatches of this loss and two of HAL's own loss on aMSa's games, to keep play without delay where it was. 2,000 updates at 0.05 of HAL's learning rates. Every tenth game is held out.

**Before training** (released weights, the 57 delay-10 games): the student needs 1.19 bits per frame for the expert's action; the expert itself needs 1.04 for its own. So the gap that delay opens, measured this way, is 0.15 bits per frame.

**The one thing that changes against E22:** the data (our own delayed games instead of aMSa's) and the label (the no-delay model instead of the human).

## Judged by

League, `return_target=40`, 6 games against each of `hal-amsa-yoshi`, `hal-master-fox`, `phillip-diamond-fox`, `phillip-plat-fox` and `cpu9-fox`, as in E22:
- at `delay=10` against the released weights' 10 of 30;
- at no delay against the released weights' 23 of 30.

Then, if it wins clearly more at `delay=10` (about 8 wins more is what 30 games can separate), 6 games against each of the six held-out yardstick opponents at `delay=10`, against the released weights at the same delay.

## Result

## Verdict
