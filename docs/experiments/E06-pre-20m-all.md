---
id: E06
title: Pretrain on every character
date: 2026-11-15
status: done
result: loss 0.632; −433 Elo at delay 3 as Yoshi
verdict: A base, not a player
runs: pre-20m-all
prs: 43
follows: E05
---

## Question

Can one model learn from all characters' Pro and Master games, as a base for a Yoshi fine-tune?

## Setup

20.7M model, 60k steps, Muon, on `pretrain-v1`: Pro and Master games of every character, 141k perspectives, 1.42B frames.

## Judged by

League at delay 3, playing Yoshi (86 games).

## Result

Validation loss 0.632. League −433.

## Verdict

Not a Yoshi player on its own, as expected: Yoshi is a small share of its data. Its value is tested in E07.
