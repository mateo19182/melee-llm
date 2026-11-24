---
id: E33
title: RL under input delay from a no-delay model
date: 2026-11-21
status: done
result: PPO in the farm with the delay raised during training took the no-delay Yoshi to 8 frames in 1,800 steps: 5 level changes, about 450 steps a frame from 7 on. At the 10 frames stomped needs it won 3 of 48 against Phillip's Yoshi and 4 of 48 against Faynt Arena Yoshi at step 1600, and 0 against Phillip's Fox and Marth
verdict: delay can be learned by RL from a no-delay model, but too slowly to be the route; stopped at step 1799 for a model trained with the delay from the start (E34). The run resumes from its checkpoint if needed
runs: yoshi-rl-2-delay, yoshi-rl-3-ladder
prs: 112, 114, 115, 116
follows: E32
---

## Question

E32's Yoshi loses everything with any input delay, and stomped.dev needs 10 frames from this server. Can the same RL teach it to play with delay, starting from the no-delay weights?

## Setup

`farm.rl` with `--delay`: the pad chosen after reading frame F lands on frame F + 1 + N, and the model reads its own last pad as its controller (`own`). Reward, penalty toward the start model and PPO settings as in E32. No shift of the reward for the delay.

- **yoshi-rl-2-delay:** from `yoshi-rl-1` step 1000, a fixed schedule: 1, 2, 3, 4, 6, 8, 10 frames, 60 steps each.
- **yoshi-rl-3-ladder:** from `yoshi-rl-2-delay` step 125 (2 frames), a ladder 3 to 10 that moves up one frame when the win rate against Phillip's agents over the last 20 steps reaches a target. Penalty weights 0.001.
  - Target 0.6, then 0.5 from step 925, then 0.3 from step 1190.
  - From step 925 the opponents were 12.5% self-play, 75% Phillip's 18-frame agents (six anti-Yoshi agents and super-gm Fox) and 12.5% no-delay Faynt Arena Fox and `yoshi-rl-1` step 1000.

## Judged by

Win rate in training at the current delay, and `farm.rl_eval` every 200 steps at 10 frames: 48 games each against Phillip's anti-Yoshi Fox and Marth, Phillip's Yoshi and Faynt Arena Yoshi.

## Result

**Fixed schedule (yoshi-rl-2-delay).** It learned within each level and the schedule outran it: win rate 0.92 at 1 frame, 0.66 to 0.78 at 2, 0.31 to 0.37 at 3, 0.07 to 0.15 at 4, and 0 from 6 on. Stopped at step 511.

**Ladder (yoshi-rl-3-ladder).**

| Delay | Reached at step | Steps at the previous level |
|---|---|---|
| 4 | 120 | 120 |
| 5 | 273 | 153 |
| 6 | 707 | 434 |
| 7 | 1210 | 503 |
| 8 | 1668 | 458 |

- At 6 frames the win rate against Phillip rose from about 0.10 to 0.27 and stayed there for 450 steps; the 0.5 target was never reached. With the target at 0.3 it moved on within 20 steps.
- At 7 frames it climbed from 0.10 to about 0.27 in 450 steps. At 8 frames it was at 0.08 to 0.12 after 130 steps when stopped.
- Against the two no-delay bots in the pool it won almost nothing: 2 of about 700 games by step 1549.
- The run was killed by the machine running out of memory four times (other jobs; ours is set to die first). It restarted itself each time and lost at most 5 steps.

**At 10 frames** (48 games each; wins, mean stock margin):

| Step | Phillip Fox | Phillip Marth | Phillip Yoshi | Faynt Arena Yoshi |
|---|---|---|---|---|
| 900 | 0, −3.56 | | | 0, −2.48 |
| 1000 | 0, −3.60 | 0, −3.73 | 0, −2.98 | 2, −2.46 |
| 1200 | 0, −3.52 | 0, −3.48 | 0, −3.00 | 0, −2.58 |
| 1400 | 0, −3.23 | 0, −3.35 | 0, −2.88 | 2, −2.06 |
| 1600 | 0, −2.92 | 0, −3.27 | 3, −2.21 | 4, −1.73 |

## Verdict

RL alone can teach a no-delay model to play with delay, and each extra frame costs about 450 steps (15 hours) from 7 frames on. Reaching 10 and then becoming good there would take days more, for a model whose imitation stage never saw delay.

Lessons carried into [the plan for our own model](../own-model.md):

- Train with the delay from the first step; Phillip's agents, which we train against, play at 18 frames because their imitation stage is aligned to it.
- A win-rate target for moving up can stall a run. A fixed number of steps per level, or training at the target delay directly, avoids it.
- The run never played its own past versions; published recipes do.
- Give the value network the present state and shift the reward by the delay; this run did neither.
