---
id: E19
title: A training loop for HAL's model on the 3090
date: 2026-11-16
status: planned
result:
verdict:
runs:
prs:
follows: E14
---

## Question

Can we train HAL's released 247M model on the 3090, and do we compute its loss the way HAL does? Every later step (E20, E21) updates this model, so the loop has to be proven correct before anything is trained with it.

## Setup

A small package, `train/haltrain/`, run with HAL's own Python environment. It reuses HAL's code and does not copy it: the model, the Muon optimiser and the data loaders come from `vendor/hal/hal`, and the loss, the return labels and the validation metric come from HAL's training script `experiments/059_muon_action_sequence.py`, loaded as a module.

Three stages, each a gate for the next:

1. **Validation.** Load `hal-250m.hal` as a full-precision trainable model and compute HAL's validation loss.
2. **One training step on the 3090.** The original used batch 512 on a 128 GB card. Here: small microbatches with gradient accumulation. Measure peak memory and windows per second.
3. **A short fine-tune** on aMSa's Yoshi games (21,423 games, 176M frames, already on disk) at the learning rate the original run ended on.

No simulator and no new data yet. HAL's simulator adapter is not built on this machine and needs a newer melee-sim-light; that belongs to E20.

## Judged by

1. Validation loss of the released weights on HAL's own validation set: HAL recorded **1.087 bits** (`val/nll`, `experiments/o59/scaling-comparison/sources/o59_cooldown_validation.json`). Ours must match to within 0.01. Also recorded: the loss on aMSa's held-out Yoshi games, as the baseline for E20.
2. A training step fits in 24 GB next to the live stomped bot, with its speed written down.
3. After the short fine-tune, validation loss on aMSa's held-out games is no worse than before, and the fine-tuned model is no weaker than `hal:AMSA#0,return_target=40` over 30 league games. This run is not expected to make the bot stronger: the model has already seen this data. It only proves the loop does no harm.

## Result

## Verdict
