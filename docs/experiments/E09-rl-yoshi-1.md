---
id: E09
title: Self-play PPO in the simulator
date: 2026-11-15
status: done
result: 77% vs teacher, then collapse; −141 and −270 Elo at delay 3
verdict: Simulator gains did not transfer to Dolphin
runs: rl-yoshi-1
prs: 55
follows: E07
---

## Question

Can reinforcement learning in melee-sim-light lift `bc-20m-ft` above its teacher?

## Setup

`meleebot.rl.ppo`. 512 simulated matches, 128-frame unrolls, delay 3. The learner is Yoshi; opponents are the frozen starting model (30%), a recent copy of itself (40%) and the all-character pretrain as seven other characters (30%). Learning rate 1e-5, KL penalty 0.1 toward the starting model, reward = stocks plus 0.01 × damage.

## Judged by

Win rate against the frozen teacher in the simulator, then league games in Dolphin for the snapshots.

## Result

146 of 189 (77%) against the teacher in the first 100 iterations, 37% in the next 100, then entropy collapsed and the loss went non-finite at iteration 262. League at delay 3, 30 games each: iteration 100 rates −141 and iteration 200 −270, against −66 for the teacher.

## Verdict

The early 77% did not show up in Dolphin, which points at the learner exploiting that one frozen opponent, not getting better. On 30 games, −141 against −66 is within noise, so the fair reading of iteration 100 is "no better".
