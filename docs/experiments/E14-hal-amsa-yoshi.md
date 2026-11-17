---
id: E14
title: HAL's 247M model imitating aMSa
date: 2026-11-16
status: done
result: 403 Elo, no delay; HAL as a Master Yoshi 220
verdict: Best Yoshi, with no training
runs:
prs: 74
follows: E11
---

## Question

How good is HAL's released model as a Yoshi, with no training by us?

## Setup

`vendor/hal/weights/hal-250m.hal`, identity `AMSA#0` (21,238 Yoshi games in its training data), default steering: return target 20, temperature 1. League names `hal-amsa-yoshi` and `hal-master-yoshi`.

## Judged by

League, no delay (78 games).

## Result

403 Elo, against 220 for HAL asked to play as a generic Master Yoshi and 398 for Phillip Diamond Fox.

## Verdict

The best Yoshi we have. At the same delay of 3 frames it rates 135 (E16) against −66 for our own best. Fine-tuning it on Yoshi data was judged not worth it: it has already seen that data.
