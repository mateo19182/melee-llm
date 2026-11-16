---
id: E10
title: PPO with stability fixes
date: 2026-11-16
status: done
result: no divergence, but 77% → 31% vs teacher
verdict: Stability was not the problem
runs: rl-yoshi-2
prs: 58
follows: E09
---

## Question

Does E09 work once it stops diverging?

## Setup

E09 plus a dual-clipped policy loss with a bounded ratio, skipping of non-finite steps, and an entropy bonus that switches on below entropy 0.3.

## Judged by

Win rate against the frozen teacher in the simulator.

## Result

Ran 1,545 iterations (101M frames, 3.6 hours) with no skipped steps. Win rate against the teacher: 77% in the first 100 iterations, then a steady fall: 59%, 47%, 34%, and 31% at the end. Its snapshots were not league-rated.

## Verdict

The fixes work; the learning does not. E12 gives a second suspect besides opponent exploitation: the starting model itself plays badly in closed loop. Do not repeat this setup.
