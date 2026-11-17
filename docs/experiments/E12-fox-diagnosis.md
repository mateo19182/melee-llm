---
id: E12
title: Why the E11 Fox loses
date: 2026-11-16
status: done
result: holds inputs: stick changes on 8.6% of frames, humans 22.9%
verdict: Behaviour, not plumbing or polling drift
runs: fox-20m-check
prs:
follows: E11
---

## Question

Is E11's failure a bug in how the bot is wired to the game, or how the model plays?

## Setup

Replays of the E11 games compared with human pro Fox games, plus direct checks of the live input path. Scripts were in `/tmp/amsa-peek/diag/` and are not kept.

## Judged by

Measurements, no new games except 15 at lower temperature.

## Result

- **Plumbing is correct.** Decisions land exactly one frame later on 9,460 of 9,460 frames; live features match the training distributions; the cached one-step path matches the full-window path.
- **Polling drift is not the cause.** Slippi Dolphin ships the fix. It does matter on stomped's arena.
- **The behaviour is wrong.** The stick changes on 8.6% of frames against 22.9% for humans; 33.5% of the time is spent in stick holds longer than 60 frames against 6%. 27 of 47 deaths were self-destructs from held Firefox or air-dodge inputs.
- Temperature 0.3 and 0.7 won 0 of 15.

## Verdict

The model copies its own previous input and gets stuck once it is the one playing. Validation loss does not see this: E11's loss is as good as our Yoshi runs'.
