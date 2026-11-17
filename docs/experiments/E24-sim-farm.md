---
id: E24
title: Simulator game farm: speed, and agreement with Dolphin
date: 2026-11-17
status: running
result:
verdict:
runs:
prs:
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

## Verdict
