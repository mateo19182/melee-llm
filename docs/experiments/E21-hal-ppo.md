---
id: E21
title: PPO on HAL with a KL penalty toward the clone
date: 2026-11-16
status: planned
result:
verdict:
runs:
prs:
follows: E20, E09
---

## Question

Does policy-gradient RL with a penalty for drifting from the cloned policy, the recipe of slippi-ai and Faynt, lift HAL-as-aMSa further than E20?

## Setup

Not designed yet; depends on E19 and E20. PPO in the simulator against a pool of opponents, never one frozen copy of the learner (lesson of E09), with a KL penalty toward the starting model.

## Judged by

League games against the E18 yardstick opponents, at least 30 per snapshot. Simulator win rate is recorded but does not decide anything.

## Result

## Verdict
