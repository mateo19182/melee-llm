---
id: E07
title: Fine-tune the pretrain on Yoshi at netplay delay
date: 2026-11-15
status: done
result: loss 0.622; 5 of 6 vs CPU 9; −66 Elo at delay 3
verdict: Best of our own models
runs: bc-20m-ft
prs: 51, 53
follows: E06, E04
---

## Question

Does pretraining on everyone and then fine-tuning on Yoshi beat training on Yoshi alone? Does training with delayed observations make it usable over netplay?

## Setup

Starts from `pre-20m-all`. 20k steps on `yoshi-hal-v3`, AdamW, cosine, learning rate 2e-4, dropout 0.1, observation delay drawn from 2–4 frames per window.

## Judged by

League at delay 3 (90 games).

## Result

Validation loss 0.622. League −66. 5 of 6 against CPU 9 and the first wins off MIMIC Marth and HAL's Master Yoshi. Still loses to Phillip, HAL Fox and Faynt.

## Verdict

Our best own model, about 175 Elo over E04. Two things changed at once (pretraining and delay training), so we cannot say how much each gave.
