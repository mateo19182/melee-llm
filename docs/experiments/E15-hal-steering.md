---
id: E15
title: Steering sweep: return target and temperature
date: 2026-11-16
status: done
result: return target 40: 561 Elo, 23 of 30
verdict: +160 Elo for free; tops the league
runs:
prs: 75
follows: E14
---

## Question

Do HAL's return target and temperature move its strength?

## Setup

`hal:AMSA#0` with return target 40 or 70 and temperature 0.8, no delay.

## Judged by

League, 30 games per setting against five opponents.

## Result

| Setting | Elo | Wins of 30 |
|---|---|---|
| return target 40 | 561 | 23 |
| return target 40, temperature 0.8 | 529 | 22 |
| temperature 0.8 | 440 | 19 |
| default (20, 1.0) | 403 | n/a |
| return target 70 | 384 | 17 (0 of 6 against HAL Fox) |

## Verdict

Return target 40 is the best setting found. It tops the league, above Faynt 10M (482 on 19 games), so the league needs stronger opponents (E18). Only two return targets were tried; a finer sweep waits for a better model.
