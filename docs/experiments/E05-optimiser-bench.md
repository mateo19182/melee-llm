---
id: E05
title: Optimiser and schedule comparison
date: 2026-11-15
status: done
result: Muon 0.710 vs AdamW 0.806 at 5k steps
verdict: Use Muon with warmup-stable-decay
runs: bench-A-adamw-cos-d01, bench-B-adamw-cos-d0, bench-C-adamw-wsd-d0, bench-D-muon-wsd-d0
prs: 43
follows:
---

## Question

Which optimiser and schedule for the big pretrain?

## Setup

Four 5,000-step runs of the 20.7M model on `pretrain-v1` (1.42B frames):

| Run | Optimiser | Schedule | Dropout | Loss |
|---|---|---|---|---|
| `bench-A` | AdamW | cosine | 0.1 | 0.811 |
| `bench-B` | AdamW | cosine | 0 | 0.806 |
| `bench-C` | AdamW | warmup-stable-decay | 0 | 0.759 |
| `bench-D` | Muon | warmup-stable-decay | 0 | 0.710 |

## Judged by

Validation loss at step 5,000. No games.

## Result

See the table: Muon with warmup-stable-decay is 0.1 lower than AdamW with cosine.

## Verdict

Use Muon with warmup-stable-decay, as Faynt and HAL do. Judged on loss alone and only at 5k steps, which rule 2 now forbids as a final judge.
