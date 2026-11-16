---
id: E16
title: Input delay 3, 6 and 10 on HAL-as-aMSa
date: 2026-11-16
status: done
result: 135, 87, 176 Elo against 403 with no delay
verdict: Delay costs 200–300 Elo, most of it by 3 frames
runs:
prs: 76
follows: E14
---

## Question

What does input delay cost?

## Setup

`hal:AMSA#0,delay=N`, default steering.

## Judged by

League, 13–18 games per delay.

## Result

| Delay | Elo | vs CPU 9 | vs Phillip Platinum | vs the no-delay version |
|---|---|---|---|---|
| 3 | 135 | 4 of 6 | 3 of 6 | 0 of 6 |
| 6 | 87 | 5 of 6 | 0 of 6 | 1 of 6 |
| 10 | 176 | 5 of 6 | 0 of 1 | 1 of 6 |

Five of six delay-10 games against Phillip Platinum died with a Dolphin disconnect; the cause was not found.

## Verdict

Most of the loss is already there at 3 frames. With so few games the order of 3, 6 and 10 is noise. Return target 40 was not tested with delay.
