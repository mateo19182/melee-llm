---
id: E20
title: Return-conditioned self-improvement in the simulator
date: 2026-11-16
status: planned
result:
verdict:
runs:
prs:
follows: E19, E18
---

## Question

HAL is conditioned on the return it is asked for. Can it improve by playing games and then training on them, labelled with the returns it actually got?

## Setup

Not designed in detail yet; depends on E19 and on the opponents E18 finds.

- Generate games of HAL-as-aMSa against a pool of opponents: HAL imitating other pros, and the opponents that beat it in E18.
- Fine-tune on those games with HAL's own loss, which already weights actions by advantage and conditions on return.
- Repeat with the new model.

Open choices: simulator or Dolphin for generating games (HAL's simulator adapter needs building), how many games per round, and whether to mix in the original aMSa data so it does not forget.

## Judged by

League games against the E18 yardstick opponents, no delay, at least 30 per model, compared with `hal:AMSA#0,return_target=40`.

## Result

## Verdict
