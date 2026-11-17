---
id: E24
title: Simulator game farm: speed, and agreement with Dolphin
date: 2026-11-17
status: done
result: 1,700 to 1,900 game frames a second at 64 lanes; at delay 10 the simulator gave 20 wins in 192, Dolphin 7 in 60
verdict: the farm replaces Dolphin for generating games and for quick checks; Dolphin stays the judge
runs:
prs: 97
follows: E23
---

## Question

Dolphin gave E23 about 1.2 games a minute and lost games to disconnects. Phillip and MIMIC train in the decompiled simulator ([simulator.md](../simulator.md)), and HAL ships a batched interface to it. Two things decide whether we move game generation there:

1. How fast does HAL's 247M model play when one GPU call serves many simulator games?
2. Do win rates in the simulator agree with our Dolphin league for the same pairings? The simulator's random numbers differ from Dolphin's, so single games cannot be compared, only rates.

## Setup

**Simulator.** melee-sim-light at the version we vendor, plus one commit from the HAL author's fork (`5a27ac78`, "Expose exact hitlag in observation ABI 2"), which HAL's compiled adapter requires. Built in `~/.t3/worktrees/melee-sim-light/hal-abi2`; the adapter is `/mnt/data/melee/native/libhal_native.so`.

**Farm.** `train/haltrain/farm.py`: N simulator lanes in one process, HAL's own batch adapter and KV-cached inference, each player with its own identity, return target and delay. The first player alternates ports by lane; stages cycle. Games run to the end or the 8-minute timer. It writes one result row per game and every frame of every game (HAL's 71 observation columns, both controllers, reward).

**Speed runs.** 64 lanes, Yoshi as aMSa against Fox as a Master player, both on the released weights, 200 frames after warm-up.

**Agreement runs.** `hal:AMSA#0,return_target=40,delay=10` against HAL as a Master player on Fox, Falco, Marth, Sheik and Peach and against HAL as aMSa, 32 games each; and the same Yoshi without delay against the Master Fox and against HAL as aMSa, 32 games each. All released weights.

## Judged by

The Dolphin league has, for the same pairings: at `delay=10`, 7 wins in 60 games (6 of 14 against HAL as aMSa, 0 of 14 against the Master Fox, 1 of 24 against Falco, Marth and Sheik together, 0 of 8 against Peach); without delay, 4 of 6 against each of the two. Written before the simulator games were played.

The farm agrees if the delay-10 rate is in the same region (Dolphin's 7 of 60 has a 95% interval of about 5% to 22%) and the ordering holds: close to even against HAL as aMSa, near zero against the Master players, clearly better without delay.

## Result

**Speed** (64 lanes, both players on the 247M model, 200 frames after warm-up):

| Setting | Game frames a second | GPU memory | Share of time in the model |
|---|---|---|---|
| no delay, not compiled | 1,336 | 5.4 GB | 76% |
| no delay, compiled | 1,683 | 5.7 GB | 75% |
| delay 10, compiled | 1,919 | 5.7 GB | 66% |

The simulator takes 7 to 8% and Python bookkeeping 17 to 25%. The simulator alone steps 64 lanes at about 21,600 frames a second on one busy core.

**Agreement** (32 games per pairing, 32 lanes; our Yoshi and its opponent are two model groups here, which is why these runs made 1,200 to 1,550 frames a second):

| Our Yoshi | Opponent | Simulator | Dolphin league |
|---|---|---|---|
| delay 10 | HAL as aMSa, Yoshi | 15 of 32 | 6 of 14 |
| delay 10 | HAL Master, Fox | 0 of 32 | 0 of 14 |
| delay 10 | HAL Master, Falco | 0 of 32 | 0 of 8 |
| delay 10 | HAL Master, Marth | 1 of 32 | 1 of 8 |
| delay 10 | HAL Master, Sheik | 3 of 32 | 0 of 8 |
| delay 10 | HAL Master, Peach | 1 of 32 | 0 of 8 |
| delay 10 | all six | 20 of 192 (10%) | 7 of 60 (12%) |
| no delay | HAL Master, Fox | 14 of 32 | 4 of 6 |
| no delay | HAL as aMSa, Yoshi | 25 of 32 | 4 of 6 |

No game reached the timer and none failed. The 256 games took about half an hour including eight model start-ups; E23's Dolphin run needed over two hours for 167. All frames of the 256 games are in `/mnt/data/melee/farm/agree-1` (44 MB).

## Verdict

The farm agrees with Dolphin where Dolphin has enough games to say anything: 10% against 12% at delay 10, with the same ordering by opponent. The no-delay rows are consistent too, but 6 Dolphin games per pairing cannot confirm more than that.

So games for training come from the farm from now on, and it is also the quick check for a new model. Dolphin stays the judge for the league table and the yardstick, because Phillip's agents and CPU 9 do not run in the farm yet.

The model is the bottleneck, as expected. A billion-frame RL run would take about a week of rollouts at this speed, which is why RL will run on a small student of HAL and not on the 247M model.

Since then the simulator commit is in our fork ([melee-brute#18](https://github.com/mateo19182/melee-brute/pull/18)) and the farm builds from a checkout of it in `/mnt/data/melee/native/melee-brute`. Open: Phillip's agents need a batched export to join the farm.
