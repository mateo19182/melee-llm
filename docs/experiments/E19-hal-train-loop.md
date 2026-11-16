---
id: E19
title: A training loop for HAL's model on the 3090
date: 2026-11-16
status: running
result: validation 1.0867 bits (HAL: 1.0870); trains at 7 GB and about 40 windows/s
verdict:
runs: hal-ft-check
prs: 82
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

**Gate 1, validation: passed.** `python -m haltrain.validate` on the released weights, HAL's fixed cohort of 2,048 windows over all 44 sources:

| | Ours | HAL's record |
|---|---|---|
| `val/nll` (bits) | 1.0867 | 1.0870 |
| near offsets | 0.8661 | 0.8664 |
| far offsets | 0.2206 | 0.2206 |
| exact frame accuracy | 0.611 | 0.613 |

The validation games of the 37 pros that were not on disk were downloaded from HAL's public dataset (1 GB). Baseline on aMSa's held-out Yoshi games (928 windows, eight passes with different random windows): **1.037 bits**. One pass (116 windows) gave 0.933, so a single pass is too noisy to compare models.

**Gate 2, a training step on the 3090: passed.** Microbatches of 16 windows, with the trunk and decoder compiled (HAL's decoder attention cannot run a backward pass uncompiled):
- Peak GPU memory 7.0 GB, next to the stomped bot and league games.
- About 40 windows a second between validations, while league games were also using the GPU and CPU. The original run did 512 windows per update; at 64 per update here that is roughly 1.5 s per update.
- Start-up: 1.7 minutes to compile; the first start also decompresses aMSa's shards (2.4 GB to 27 GB).
- Compiled and uncompiled losses agree to three decimals on the same batch (0.9615 against 0.9623 bits).

**Gate 3, a short fine-tune: validation passed, league pending.** `hal-ft-check`: 300 updates of 64 windows (19,200 windows, 10 minutes) on aMSa's Yoshi games at 1/170 of HAL's learning rates.
- Validation on aMSa's held-out games: 1.0369 → 1.0354 → 1.0348 → 1.0345 bits. Training loss stayed around 1.1 bits, gradient norm around 1.1.
- 156 of 184 weight tensors changed, by at most 0.0014.
- The checkpoint saves as a bundle the bots load: `hal:AMSA#0,run=hal-ft-check`.
- League games against the released weights' five opponents from E15 are queued.

Problems found on the way:
- HAL's loaders delete the compressed shards after decompressing them, so training and validation read from copies (`/mnt/data/melee/hal-ft`, `/mnt/data/melee/hal-val`), never the dataset itself.
- A killed run leaves the loader's shared memory behind and the next start fails with "Reused local directory"; `streaming.base.util.clean_stale_shared_memory()` clears it.
- While this ran, the live stomped bot's decision time rose from 9 ms to 26–48 ms (95th percentile) and it missed up to 2,047 frames in a match. Training and the live bot cannot share the GPU without hurting the bot.

## Verdict
