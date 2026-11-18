---
id: E26
title: Does HAL execute Yoshi's techniques like aMSa, and what does delay take away?
date: 2026-11-18
status: done
result: same aerials, double-jump cancels and L-cancels as aMSa; half his double-jump lands; parries against Fox drop from 0.17 to 0.02 a minute at delay 10
verdict: delay takes Fox parries and some precision; the gap to aMSa in double-jump lands is there without delay too
runs:
prs:
follows: E24
---

## Question

Before adding anything for Yoshi's techniques ([yoshi.md](../yoshi.md)), measure: does HAL imitating aMSa execute them as often as aMSa does, and which ones does input delay take away?

## Setup

`train/haltrain/style.py` counts technique use from the animation state on every frame:
- aerials per minute, and the share started straight out of the double jump (double-jump cancelled);
- the share of aerial landings that were L-cancelled, from how long the landing lasted (down air left out);
- double-jump lands per minute: a double jump that ends on the ground with no fall in between;
- shields per minute, and parries per minute. A parry is counted when the opponent's attack freezes on Yoshi's 6-frame shield start-up while Yoshi does not freeze and nobody takes damage. It is an approximation: an attack hitting an egg in that moment counts too.

Sources: the first 150 of aMSa's human games against each character (HAL's dataset), and the 32-game farm runs of E24 with HAL as aMSa (`return_target=40`) at no delay and at 10 frames. The farm opponents are HAL imitating a Master-rank player, not the pros aMSa faced.

## Judged by

Rates side by side, per opponent character. No pass mark: this is a measurement to decide what, if anything, needs teaching.

## Result

| Opponent | Player | Games | Aerials/min | Double-jump cancelled | L-cancelled | Double-jump lands/min | Shields/min | Parries/min |
|---|---|---|---|---|---|---|---|---|
| Fox | aMSa | 150 | 27.1 | 58% | 94% | 4.65 | 3.4 | 0.16 |
| Fox | HAL, no delay | 32 | 27.9 | 61% | 92% | 2.69 | 3.1 | 0.17 |
| Fox | HAL, delay 10 | 32 | 25.9 | 62% | 89% | 1.96 | 2.6 | 0.02 |
| Falco | aMSa | 150 | 28.0 | 61% | 93% | 4.28 | 4.3 | 0.09 |
| Falco | HAL, delay 10 | 32 | 25.3 | 61% | 87% | 1.67 | 3.1 | 0.07 |
| Marth | aMSa | 150 | 24.0 | 53% | 93% | 3.97 | 3.6 | 0.09 |
| Marth | HAL, delay 10 | 32 | 24.5 | 61% | 87% | 2.23 | 2.6 | 0.11 |
| Yoshi | HAL, no delay | 32 | 29.4 | 52% | 93% | 2.80 | 2.9 | 0.03 |
| Yoshi | HAL, delay 10 | 32 | 28.0 | 52% | 87% | 1.99 | 3.3 | 0.02 |

- **Aerials and double-jump cancels are intact.** HAL throws as many aerials as aMSa and cancels the double jump on the same share of them, with or without delay.
- **L-cancels slip a little with delay:** 94% for aMSa, 92 to 93% for HAL without delay, 87 to 89% at 10 frames.
- **Double-jump lands are the gap, and delay is only part of it.** HAL does about 2.7 a minute without delay against aMSa's 4 to 4.7, and about 2 at delay 10.
- **Parries against Fox disappear with delay** (0.17 to 0.02 a minute). Against Falco and Marth they stay near aMSa's rate.

Parry counts are small: 0.16 a minute is about one every six minutes, so 32 games give a few dozen events at most.

## Verdict

HAL already executes most of aMSa's technique, so adding technique examples across the board would teach what it knows. Two things stand out and both fit the research page: Fox's fast attacks cannot be parried with a 10-frame delay, and platform movement by double-jump land is weaker than aMSa's even without delay.

Neither is known to cost games. The counter now runs on any farm output, so the students and later RL models get the same table, and a technique is worth teaching only if it is both missing and tied to losses.
