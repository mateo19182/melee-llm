---
id: E22
title: HAL under delay: rebalance the action offsets
date: 2026-11-17
status: running
result:
verdict:
runs: hal-delay-offsets
prs:
follows: E19, E16
---

## Question

HAL loses 200 to 300 points with input delay (E16), and stomped needs 10 frames of it. Is that because the heads it plays from under delay were barely trained, and does retraining them fix it?

How HAL plays with delay, read from its code: it is not given old observations. With d frames of delay the d actions already on their way are fed to the decoder as known, and the model samples the action for d+1 frames ahead. So at 10 frames it plays from offsets 11 and 12, never from offset 1.

HAL's loss gives offset 1 a weight of 0.50, offsets 2 to 6 0.07 each and offsets 7 to 28 0.015 each, and it applies advantage weights to offsets 1 to 6 only. The heads used at 10 frames of delay had 3% of the weight of the head used with no delay, and no advantage weighting.

## Setup

Measured before training, released weights on aMSa's held-out Yoshi games (932 windows), bits per frame:

| Offset | Given the true earlier actions | Given its own sampled earlier actions |
|---|---|---|
| 1 | 0.97 | 1.14 |
| 6 | 0.92 | 4.13 |
| 11 | 0.93 | 7.16 |
| 12 | 1.05 | 7.69 |

Given the true earlier actions, offset 12 is predicted as well as offset 1, so by imitation loss the far heads are not undertrained. This weakens the hypothesis: the reweighting can still change play through the advantage weights, but there is little imitation loss left to recover. The second column is open-loop sampling and grows as expected; live play with delay sits between the two, because the earlier actions are the bot's own but each was chosen with a later observation.

The run, `hal-delay-offsets`: fine-tune the released weights on aMSa's Yoshi games with `--offsets delay` (offsets 1 to 12 at 1/12 each, advantage weights on all twelve; offsets 16 to 28 unchanged). 4,000 updates of 64 windows at 0.05 of HAL's learning rates, 100 updates of warm-up. This is also the first run at a learning rate meant to change the model; E19 used 1/170.

The one thing that changes against E19's check: the offset weighting (and the learning rate needed for it to matter).

## Judged by

League, `return_target=40`, 6 games against each of `hal-amsa-yoshi`, `hal-master-fox`, `phillip-diamond-fox`, `phillip-plat-fox` and `cpu9-fox`:
- released weights at `delay=10` (baseline, not measured before with this steering),
- the fine-tune at `delay=10`,
- the fine-tune at no delay, against the released weights' 23 of 30.

It is a success if the fine-tune wins clearly more at `delay=10` (30 games separate only large differences: about 8 wins more) without losing more than a few at no delay. Validation loss per offset is logged but does not decide.

## Result

## Verdict
