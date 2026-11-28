---
id: E37
title: Our own model: RL at 12 frames
date: 2026-11-28
status: running
result: running
verdict: pending
runs: own-rl-12
prs: 128
follows: E36, E33
---

## Question

Stage 3 of the [plan](../own-model.md), the 12-frame branch first: does RL in the farm turn the Yoshi fine-tune (E36), which imitation trained at 12 frames from the start, into a bot that beats Phillip's agents at that delay? E33 tried the same RL from Faynt's no-delay model and needed about 450 steps for each extra frame; here the start model already plays at 12 frames (41 of 64 against E33's result) and has never won a game against Phillip's Yoshi.

## Setup

`farm.rl own-rl-12 --init` and `--ref` E36's `own-yoshi-ft/ckpt/step-0122070`, `--name 19 --items 4 --delay 12`, 1,000 steps (about 40 hours):

- **Delay:** 12 frames from the first step, no ladder. The model reads its own last pad.
- **Credit:** an action's advantage is the one measured on the frame it lands on (`--shift`, the default since PR #128). The value network reads the present state.
- **Penalty:** Faynt's two KL terms toward the start model at 0.003 each, as in E32 and E33.
- **Opponents:** the default pool of 64 lanes: 32 of self-play and 32 against Phillip's five anti-Yoshi agents and Phillip's Yoshi, which play at 18 frames.
- Everything else at the defaults of E32 (Faynt's 10M "leash" settings): 2,048 frames a lane per step, learning rate 1e-4, two PPO epochs.

Checked before launch (`--check`, 2 steps): the learner reproduces the actor's action probabilities to 3e-6.

## Judged by

- **`farm.rl_eval` every 100 steps at 12 frames,** 48 games each against Phillip's anti-Yoshi Fox and Marth, Phillip's Yoshi and Faynt Arena Yoshi (which plays with no delay). The start model won 0 of 64 against Phillip's Yoshi.
- **Against the start model** at 12 frames, 64 games, at the end. Winning the pool while losing to the model it came from would mean it only learned the pool.
- **Training log:** win rate per opponent, and the KL to the start model (E33 ended at 0.33).
- **Dolphin league** for the best checkpoint, at 12 frames, against the roster's Yoshi rivals and anti-Yoshi agents.

A clear rise against Phillip within the first 300 steps means the run goes on to 1,000 and the no-delay branch follows the same recipe. No rise by step 300 means the pool is too strong to learn from, and the pool changes (weaker Phillip tiers, past versions of itself) before more steps.

## Result

## Verdict
