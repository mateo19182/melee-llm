---
id: E22
title: HAL under delay: rebalance the action offsets
date: 2026-11-17
status: done
result: at 10 frames of delay the fine-tune won 8 of 30, the released weights 10 of 30
verdict: no effect; the offset weighting is not why HAL is weak under delay
runs: hal-delay-offsets
prs: 94
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

The run: 4,000 updates, 256,000 windows, 64 minutes at 67 windows a second, 7.0 GB. Stable throughout: gradient norm 0.9 to 1.0, training loss flat around 1.14 bits.

Validation on aMSa's held-out Yoshi games, bits per frame with HAL's weighting:

| Update | Total | Offset 1 | Offset 6 | Offset 11 | Offset 12 |
|---|---|---|---|---|---|
| 0 | 1.0369 | 0.969 | 0.920 | 0.927 | 1.048 |
| 2,000 | 1.0302 | 0.961 | 0.918 | 0.926 | 1.040 |
| 4,000 | 1.0309 | 0.968 | 0.917 | 0.910 | 1.038 |

Offsets 11 and 12 improved by 0.01 to 0.02 bits and offset 1 did not get worse.

League, return target 40, wins of 6 against each opponent. No game died with an error.

| Opponent | Released, delay 10 | Fine-tune, delay 10 | Fine-tune, no delay | Released, no delay (E15) |
|---|---|---|---|---|
| HAL as aMSa, default steering | 2 | 2 | 4 | 4 |
| HAL Master Fox | 0 | 0 | 3 | 4 |
| Phillip Diamond Fox | 1 | 1 | 3 | 3 |
| Phillip Platinum Fox | 3 | 1 | 4 | 6 |
| CPU 9 | 4 | 4 | 6 | 6 |
| Total of 30 | 10 | 8 | 20 | 23 |

- **Delay 10 costs the released weights 13 wins in 30** on these opponents (23 to 10), now measured with the steering we use.
- **The fine-tune did not recover any of it:** 8 against 10 is inside the noise, and it is not better.
- **No delay:** 20 against 23, also inside the noise.

## Verdict

The far offsets were not the problem. They already imitated as well as offset 1 before training, a 0.02-bit improvement on them changed nothing in play, and advantage weights on them did not either. Imitation data cannot teach play under delay: every human action in it was chosen with an up-to-date view of the game, so the model never sees what it costs to act on a view that is 10 frames old.

What this does show: the loop trains HAL's model stably at 0.05 of its learning rates and 64 windows per update, and the result still plays at the released strength.

Next: the bot has to learn from its own games played under delay, as Phillip's agents did.
