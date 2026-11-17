---
id: E13
title: Fine-tune to break the input holding
date: 2026-11-16
status: abandoned
result: crashed at step 1,000 with loss 1.692
verdict: Dropped with the own pipeline
runs: fox-20m-padfix
prs:
follows: E12
---

## Question

Can a fine-tune that hides part of the previous input stop the model copying it?

## Setup

From `fox-20m-check`, 8k steps planned, learning rate 3e-4. The code was never committed.

## Judged by

The E11 games again.

## Result

The job crashed after step 1,000, at validation loss 1.692.

## Verdict

Abandoned when the own pipeline was stopped. The idea is untested, not refuted.
