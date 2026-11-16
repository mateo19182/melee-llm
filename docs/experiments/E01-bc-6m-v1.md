---
id: E01
title: First clone of Yoshi players, 5.4M
date: 2026-11-14
status: done
result: loss 0.783; 0 of 12 vs CPU 9
verdict: Too small
runs: bc-6m-v1
prs: 8, 11
follows:
---

## Question

Can a small behaviour-cloned model play Yoshi at all?

## Setup

Decoder-only transformer that predicts the next frame's controller from game state and the previous input. Trained from scratch, context 256 frames. 5.4M parameters (6 layers × 256), batch 64, learning rate 3e-4, 30k steps on ranked Yoshi replays.

## Judged by

Games as Yoshi against the level 9 CPU Fox with no delay (`meleebot.evaluate`). 12 games.

## Result

Validation loss 0.783. 0 of 12; it took about one stock a game.

## Verdict

It moves and attacks but cannot win. Go bigger.
