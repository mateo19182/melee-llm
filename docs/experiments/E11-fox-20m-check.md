---
id: E11
title: Does our pipeline reproduce HAL's 20M Fox?
date: 2026-11-16
status: done
result: loss 0.661; 2 of 24 vs CPU 9 (HAL: 95%)
verdict: No. Own pipeline stopped
runs: fox-20m-check
prs:
follows: E07
---

## Question

HAL's first post reports a 20M clone of pro Fox winning 95% against CPU 9. Ours never got near that with Yoshi. Is the difference the character and data, or our pipeline?

## Setup

The 20.7M model, 45k steps on `fox-pro-v1` (300M frames, 33.6k pro Fox games), AdamW, cosine, dropout 0.1, delays 0–4.

## Judged by

12 games against CPU 9 at delay 0 and 12 at delay 3, as Fox.

## Result

Validation loss 0.661. 1 of 12 at each delay.

## Verdict

The pipeline is at fault, not Yoshi. E12 finds why. Mateo stopped the own pipeline here and chose to build on HAL.
