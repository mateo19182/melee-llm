---
id: E08
title: stomped.dev with our clone
date: 2026-11-14
status: done
result: 8 of 36 finished matches won; 26 disconnects
verdict: Too weak at that delay; switched off
runs:
prs: 34
follows: E04
---

## Question

How does our clone do against other people's bots on [stomped.dev](https://stomped.dev)?

## Setup

`meleebot.stomped` from the home server. The round trip to the arena is 130 ms, so the bot acts 11 frames ahead. The model was whichever clone was newest at the time; which one played which match was not recorded.

## Judged by

Match results in `data/stomped/matches.jsonl`.

## Result

62 matches on 11-14 and 11-15: 36 finished, 8 won; 26 ended in a disconnect.

## Verdict

Too weak at that delay. Switched off on 11-15. From now on record the model with every match.
