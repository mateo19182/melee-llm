---
id: E34
title: Our own model: the gate
date: 2026-11-24
status: done
result: after 1 billion frames both models play normally (stick changes on 17 to 20% of frames) and are about level with Faynt's 10M Base in the farm at no delay (Fox 27 and 23 of 64, Yoshi 35 and 43 of 64). The mixed-delay model beat the delay-0 one 38 of 64, so the delay input costs nothing. On Dolphin the mixed model's Fox won 21 of 36 against CPU 9 where Faynt Base won 27 of 36, and 17 of 40 against Faynt Base, the same 42% as in the farm. At 12 frames it won 7 of 64 against E33's RL Yoshi and 0 of 64 against Phillip's Yoshi
verdict: the pipeline works and one model can serve both delays, so the full pretrain (E35) is mixed-delay. Farm and Dolphin agree. The CPU 9 bar (a clear win on Dolphin) is not met at 1 billion frames; E35 has to meet it. Imitation alone at 12 frames is far behind RL-trained bots
runs: own-gate-d0, own-gate-mix
prs: 118, 119, 120, 121
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

Both runs finished their 122,070 steps on 11-25 at about 28,000 frames a second each (58,000 for one run alone).

**Validation loss** (nats per frame): delay-0 model 0.790; mixed model 0.784 at no delay and 0.796 at 12 frames.

**Farm, last checkpoint, 64 games each** (`train/own/gate-eval.sh`, log `/mnt/data/melee/runs/own-gate-eval.log`). Stick changes are the share of frames on which the main stick moved, ours then the opponent's.

| Player | Opponent | Delay | Wins | Stocks a game | Stick changes |
|---|---|---|---|---|---|
| Mixed, Fox | Faynt 10M Base, Fox | 0 | 27 | −0.38 | 19.1% / 17.8% |
| Delay-0, Fox | Faynt 10M Base, Fox | 0 | 23 | −0.45 | 17.5% / 17.6% |
| Mixed, Fox | Delay-0, Fox | 0 | 38 | +0.31 | 19.6% / 17.4% |
| Mixed, Yoshi | Faynt 10M Base, Yoshi | 0 | 35 | +0.28 | 18.5% / 17.9% |
| Delay-0, Yoshi | Faynt 10M Base, Yoshi | 0 | 43 | +0.97 | 16.9% / 17.6% |
| Mixed, Fox | Faynt 10M Base, Fox, also delayed | 12 | 61.5 | +2.56 | 19.8% / 16.7% |
| Mixed, Yoshi | `yoshi-rl-3-ladder` step 1795, also delayed | 12 | 7 | −1.70 | 17.6% / 17.0% |
| Mixed, Yoshi | Phillip's Yoshi (`yoshi_d18_ditto`) | 12 | 0 | −3.77 | 16.8% |

During training the mixed model went from 0 of 16 against Faynt Base at step 2,000 to 6 of 32 at step 22,000.

**Dolphin league, mixed model as Fox at no delay** (`train/own/gate-dolphin.sh`):

| Player | Opponent | Wins |
|---|---|---|
| Mixed, reading its own last pad | CPU 9 | 14 of 24 |
| Mixed, reading the pad the game reports | CPU 9 | 7 of 12 |
| Faynt 10M Base | CPU 9 | 27 of 36 |
| Mixed, reading its own last pad | Faynt 10M Base | 17 of 40 (−0.23 stocks a game) |

The 40 games against Faynt Base are a second run (`train/own/gate-dolphin2.sh`); a first one finished only 7 games (2 wins), not counted here.

**Farm against Dolphin.** The first Dolphin games (5 of 12 against CPU 9, 2 of 7 against Faynt Base) looked worse than the farm's 42% against Faynt Base, so we checked the two play paths:

- With `--check`, what our model reads in the farm equals libmelee's parse of the same frames on 114,000 seat-frames, apart from the item limit, which both paths apply with the same function.
- The model gives the same loss on the GPU and the CPU, in bfloat16 and float32 (0.568 on the same windows).
- In the Dolphin replays our model changes the stick on 20% of frames and Faynt Base on 18%, as in the farm.
- 40 Dolphin games against Faynt Base: 17 wins, 42.5%, against 27 of 64 in the farm.

## Verdict

- **The pipeline works.** The input holding of E11 to E13 is gone: the stick moves as often as Faynt's, and the model is level with Faynt's 10M Base in the farm after 1 billion frames.
- **One model for both delays.** The mixed model is no worse at no delay than the model trained only there.
- **Farm and Dolphin agree.** Same win rate against Faynt Base in both, same inputs, same stick-change rates. The early gap was 19 games of noise.
- **The CPU 9 bar is not met.** 58% on Dolphin is not the clear win we asked for; Faynt Base, which beats our model 58 to 42, wins 75%. The model is simply not strong enough yet, and E35 sees 8 times the frames.
- **At 12 frames imitation is not enough.** It beats a no-delay model handicapped with the delay but loses to both RL-trained bots. The RL stage is where the 12-frame model gets made.
