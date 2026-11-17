---
id: E03
title: Clone of aMSa only
date: 2026-11-14
status: done
result: loss 0.662; 6 of 36 vs CPU 9
verdict: One pro is not enough data
runs: bc-20m-amsa
prs: 25
follows: E02
---

## Question

Is it better to copy only the best Yoshi player than every ranked Yoshi?

## Setup

The E02 model, 15k steps on aMSa's games only (`amsa-v2`, 181M frames, 21.7k games).

## Judged by

Games as Yoshi against the level 9 CPU Fox with no delay (`meleebot.evaluate`). 36 games.

## Result

Validation loss 0.662. 6 of 36.

## Verdict

Better than E02 but still far below CPU 9. HAL later shows aMSa's play is worth copying (E14); a 20M model trained on him alone cannot do it.
