---
id: E35
title: Our own model: all-character pretrain
date: 2026-11-25
status: done
result: 6.5 billion frames in float32, no rollbacks; validation 0.760 at no delay and 0.769 at 12 frames (gate model 0.784 and 0.796). At no delay Fox with a Master code beat CPU 9 on Dolphin 24 of 24 and Faynt's 10M Base 19 of 24 (farm 50 of 64); Yoshi beat Base 58 of 64 in the farm. League rating 245 Elo (Base 145), with 4 wins in 120 games against the Fox roster. At 12 frames Yoshi won 25 of 64 against E33's RL Yoshi and 0 of 64 against Phillip's Yoshi
verdict: the CPU 9 bar is met and the no-delay base is stronger than Faynt's 10M Base, so stage 2 (Yoshi fine-tune) starts from step-0793457. Play with a Master code (14 or 15), not the pro-winner one, which is weaker and unstable for Fox. Imitation does not make a 12-frame player; that is RL's job (stage 3). The button logits still drift in float32, so the next long run should pin their level
runs: own-pre-10m, own-pre-10m-b, own-diverge-bf16, own-diverge-f32
prs: 121, 124, 125, 126, 127, 128, 129
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

**Cause: bfloat16.** Two side runs from the step-200,000 weights at that step's learning rate (2.7e-4), same seed, guard off, differing only in the compute precision:

| Step | `own-diverge-bf16`: validation loss, top logit, spread | `own-diverge-f32`: the same |
|---|---|---|
| 4,000 | 0.801, -52, 8.8 | 0.800, -45, 7.5 |
| 12,000 | 0.816, -58, 11.1 | 0.814, -40, 7.3 |
| 16,000 | 0.822, -72, 14.8 | 0.818, -41, 7.7 |
| 19,000 | 0.835, -89, 18.9 | |
| 20,000 | 1.011, -630, 144 | 0.823, -40, 7.6 |
| 22,000 | stopped | 0.819, -40, 7.3 |

In bfloat16 the failure repeats on schedule (the first run broke 16,000 steps after the same weights), and the logits speed up as they pass -64, where bfloat16's step doubles. In float32 the logits hold still over these 22,000 steps. Over the full restart they drift too, only far slower and without a collapse (see Result), so bfloat16 turns the drift into a failure but is not its only source. The learning rate is not the trigger: the float32 run holds 2.7e-4 without trouble. It is still too high for the loss: both side runs sit at 0.80 to 0.83 while the restart at 1e-4 reached 0.78.

### The restart: own-pre-10m-b

From the step-180,000 weights of the first run (validation 0.804), a new optimizer, float32 (the same speed here: 56,000 frames a second), peak learning rate 1e-4 with 2,000 warm-up steps and a cosine decay over 6.5 billion frames (793,457 steps, about 33 hours). Final weight folder: `step-0793457`.

`own.train` now guards itself: the state at the last healthy validation is kept, and a validation loss 8% over the best, or a gradient norm 6 times its recent median for 300 steps, sends the run back to it at half the learning rate; after 4 of these it stops. Validation also logs the level and spread of the button logits, and every weight folder holds the optimizer state, so a run can be resumed from any of them.

At step 20,000 the restart was stopped and resumed with a new loader: each worker interleaves four shards (a shard is about 170 games of one source, and reading them one after another made batches of about five sources). Its validation loss had moved between 0.782 and 0.812 without any change in the logits.

## Judged by

All at 64 games in the farm unless said (`train/own/eval.sh`), then the Dolphin league for the final checkpoint.

- Validation loss per delay on the same 240 held-out games as E34 (0.784 at no delay, 0.796 at 12 frames).
- **Which code plays best:** pro winner, Master winner and Master loser, as Fox against Faynt's 10M Base at no delay. If winner and loser codes play the same, the labels carry nothing.
- **Against the gate model,** both at no delay and both at 12 frames, as Fox and as Yoshi.
- **Against Faynt's 10M Base** at no delay, as Fox and as Yoshi (the gate model won 27 and 35 of 64).
- **At 12 frames** as Yoshi against `yoshi-rl-3-ladder` step 1795 at the same delay (the gate model won 7 of 64) and Phillip's Yoshi (0 of 64).
- **Dolphin league:** Fox at no delay against CPU 9, 24 games (the gate model won 14 of 24, Faynt's 10M Base 10 of 12), then the Fox roster at 12 games each. A clear win over CPU 9 is the bar E34 left open.

## Interim check at step 100,000 of the restart (11-26)

About 2.3 billion frames seen in total. Farm, 64 games each, after the name-code fix of PR #128 (log `/mnt/data/melee/runs/own-rerun-fixed.log`):

| Player (name code) | Opponent | Delay | Wins | Stocks a game |
|---|---|---|---|---|
| Fox (18, pro winner) | Faynt 10M Base, Fox | 0 | 31 | −0.14 |
| Fox (12, Master loser) | Faynt 10M Base, Fox | 0 | 39 | +0.36 |
| Yoshi (18) | Faynt 10M Base, Yoshi | 0 | 52.5 | +1.58 |
| Fox (18) | E34's mixed model, Fox | 0 | 34 | +0.20 |
| Yoshi (19) | `yoshi-rl-3-ladder` step 1795, also delayed | 12 | 19 | −0.92 |

E34's mixed model at 1 billion frames had 25, 35 and 9 in the first, third and fifth matchups. Yoshi is clearly ahead, Fox is level within noise, and the pro-winner code is not better than the Master-loser one here.

## Interim check at step 500,000 (11-27)

Farm, 64 games each (log `/mnt/data/melee/runs/own-interim-500k.log`): Fox (18) 45 and Yoshi (18) 59 against Faynt's 10M Base at no delay; Yoshi (19) 16 against `yoshi-rl-3-ladder` at 12 frames.

## Result

**The run.** `own-pre-10m-b` reached step 793,457 on 11-27 at 21:25 with no rollbacks. systemd restarted it twice (killed for memory on 11-26 at 17:06; exit code 1 with no traceback in the journal on 11-27 at 11:19) and it resumed from its last save both times. Validation over the last four checks was 0.749 to 0.769 at no delay and 0.757 to 0.779 at 12 frames; the last, at step 790,000, 0.760 and 0.769. The 240 validation games are few enough that it moves by 0.01 between checks.

**The logits drift in float32 too.** The mean top button logit went from -42 at the start of the restart to -110 by step 600,000 and -127 at the end, its spread from 6 to 30, and the gradient norm from 0.23 to between 3 and 5 (clipped to 1 on every step). The loss kept improving throughout. Nothing fixes the level of these logits, so the next long run should pin it.

**Farm, final checkpoint, 64 games each** (`train/own/eval.sh own-pre-10m-b 0793457`, log `/mnt/data/melee/runs/own-pre-10m-b-eval.log`):

| Player (name code) | Opponent | Delay | Wins | Stocks a game | Gate model in the same match |
|---|---|---|---|---|---|
| Fox (18, pro winner) | Faynt 10M Base | 0 | 32 | −0.09 | 25 |
| Fox (14, Master winner) | Faynt 10M Base | 0 | 50 | +1.05 | |
| Fox (12, Master loser) | Faynt 10M Base | 0 | 47 | +1.00 | |
| Yoshi (18) | Faynt 10M Base | 0 | 58 | +1.83 | 35 |
| Fox (18) | Gate model | 0 | 37 | +0.25 | |
| Fox (19) | Gate model | 12 | 46 | +0.83 | |
| Yoshi (18) | Gate model | 0 | 60 | +1.64 | |
| Yoshi (19) | Gate model | 12 | 54 | +1.42 | |
| Yoshi (19) | `yoshi-rl-3-ladder` step 1795 | 12 | 25 | −0.31 | 9 |
| Yoshi (19) | Phillip's Yoshi (18 frames) | 12 | 0 | −3.48 | 0 |

- **Name code.** For Fox the pro-winner code is the weak one: 32 against 47 and 50 for the Master codes, and it gave 31, 45 and 32 at steps 100,000, 500,000 and the end. Master winner and Master loser play the same, so the win label carries little; the rank part does.
- **12 frames.** 25 of 64 against the RL Yoshi is up from 9 for the gate model, and still 0 against Phillip.

**Dolphin league, Fox at no delay, 24 games each** (`train/own/pre-dolphin.sh`, log `/mnt/data/melee/runs/own-pre-dolphin.log`):

| Name code | Opponent | Wins |
|---|---|---|
| 14 (Master winner) | CPU 9 | 24 of 24 |
| 18 (pro winner) | CPU 9 | 23 of 24 |
| 14 | Faynt 10M Base | 19 of 24 |

The gate model won 14 of 24 against CPU 9 and Faynt's 10M Base 27 of 36. Against Faynt Base, Dolphin (79%) and the farm (78%) agree.

**Fox roster, same Fox with code 14, 12 games each** (`train/own/pre-dolphin.sh roster`, log `/mnt/data/melee/runs/own-pre-roster.log`):

| Opponent (Fox) | Wins of 12 | Stocks a game |
|---|---|---|
| Phillip Platinum | 1 | −1.92 |
| Phillip Diamond | 3 | −1.17 |
| Phillip Master | 0 | −2.08 |
| Phillip Grandmaster | 0 | −3.08 |
| Phillip super-GM | 0 | −2.75 |
| Phillip Fox v6.2 | 0 | −3.00 |
| Mimic Fox | 0 | −2.33 |
| HAL Master | 0 | −2.08 |
| Faynt 10M Arena | 0 | −3.92 |
| Faynt 75M Arena | 0 | −3.25 |

League rating over these 168 games: 245 Elo (CPU 9 = 0), against 145 for Faynt's 10M Base, 58 to 102 for the gate model, 349 for Phillip Platinum and 1,086 for Faynt 10M Arena. The base is one step above Faynt's own base and below every other bot of the roster.

## Verdict

The bar E34 left open is met: a clear win over CPU 9 on Dolphin, and at no delay the model is ahead of Faynt's 10M Base as Fox and as Yoshi. It is also far below the roster's trained bots (245 Elo, 4 wins in 120 roster games), as Faynt's base is: the strength has to come from RL. `step-0793457` is the base for stage 2 (Yoshi fine-tune) and stage 3 (RL).

- Play with a Master code. Which code is best should be checked again after each later stage.
- More imitation will not make the 12-frame model: it gained against the RL Yoshi and nothing against Phillip. RL at 12 frames comes first in stage 3.
- For the next long run: pin the level of the button logits, and use a larger validation set.
