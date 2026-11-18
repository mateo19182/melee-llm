---
id: E25
title: Small student of HAL: design and speed
date: 2026-11-18
status: running
result:
verdict:
runs: student-w256-c128, student-w256-c256, student-w384-c128, student-w384-c256
prs:
follows: E24
---

## Question

RL needs far more games than HAL's 247M model can play (E24: about 1,800 game frames a second). Faynt and MIMIC both found that a 5M to 10M model is enough once it does RL. Can a small student of HAL play fast enough in the farm, and does it keep HAL's strength after copying it?

This entry covers the design and the speed. Training it is the next step and gets its result here.

## Setup

**A smaller HAL is not faster.** Random-weight models of HAL's exact shape, 64 games, delay 10, through HAL's own inference code:

| Model | Parameters | Game frames a second |
|---|---|---|
| HAL (12 + 6 layers, width 1024), compiled | 247M | 1,919 |
| 8 + 4 layers, width 512 | 44M | 1,484 |
| 6 + 3 layers, width 384 | 20M | 1,545 |
| 6 + 3 layers, width 256 | 10M | 1,579 |

Two causes. HAL's inference code handles each game separately in Python (a 71-field record per player per frame), which caps the farm near 2,000 frames a second whatever the model. And under delay HAL's decoder re-reads the actions already sent before choosing: 48 tokens and 8 sampling passes per decision at 10 frames.

**The student** (`train/haltrain/student.py`):
- Input as in HAL: HAL's own code turns a frame into a token, and HAL's trunk blocks run over the frames. Farm frames and HAL's human dataset feed it unchanged.
- The actions already sent are an input. With d frames of delay, the d pending actions and the number d go into a two-layer head together with the trunk's output for the last frame seen.
- The head outputs one action, for frame t+d+1, its four controller groups picked in HAL's order.
- The trunk never sees d, so one pass over a game trains every delay.
- It plays Yoshi only. HAL's weights cannot be loaded into it.

Decided with Mateo on 2026-11-18: pending actions as input, Yoshi only, train 10M-class and 20M-class students, and compare 128 against 256 frames of memory.

**Runtime.** `student.Cache` keeps the trunk's attention keys and values for every game in one tensor, so a new frame costs one token per game and nothing is done per game in Python.

**Training data.** Everything is Yoshi, by stomped's rules (no UCF):
- 1,440 farm games of the teacher (`hal:AMSA#0,return_target=40`): 360 each at 0, 9, 10 and 11 frames of delay, against HAL as a Master player on Fox (96), Captain Falcon, Falco, Marth and Jigglypuff (48 each), Sheik and Peach (24 each), and against HAL as aMSa (24). The mix follows who we meet on stomped ([yoshi.md](../yoshi.md)). About 9.6M frames, in `/mnt/data/melee/farm/student-1`. The teacher won 171 of 360 without delay and 47, 35 and 27 of 360 at 9, 10 and 11 frames.
- aMSa's human games on Yoshi from HAL's dataset.

**Training** (`train/haltrain/distill.py`). Every example is the game up to frame t, the d actions that followed, and a label for the action of frame t+d+1:
- games played without delay (the teacher's and aMSa's): the label is the action that was played, and d is drawn from 0, 9, 10, 11. This is imitation at delay alignment, as slippi-ai does it;
- games the teacher played with delay d: these hold the positions a delayed player gets into. The label is what the teacher would do seeing the present (`train/haltrain/relabel.py`), at the game's own d. This is the DIDA step of E23, with the student in place of the big model.

Each update takes 64 windows of farm games and 64 of aMSa's; 20,000 updates; Muon on the trunk's matrices and AdamW on the rest, cosine decay. Every tenth farm game is held out. No return steering and no advantage weights in this first version.

**The four students:** width 256 (6.7M) and width 384 (14.8M), each with 128 and with 256 frames of memory. Runs `student-w256-c128`, `student-w256-c256`, `student-w384-c128`, `student-w384-c256`.

**Playing.** `haltrain.farm` seats a student with `student:RUN[,delay=N]`. Its inputs go through the same HAL code as training windows; checked equal, value for value, on 256 frames of a saved game.

## Judged by

Speed: game frames a second in the farm at delay 10, with the real simulator stepping every game.

Strength, once trained: in the farm against the opponents of E24 at delay 10 and at no delay, against HAL's own numbers there (20 of 192 at delay 10; 14 of 32 and 25 of 32 without), then the Dolphin league.

## Result

**Cached inference is exact.** In full precision, feeding a game frame by frame through the cache gives the same trunk output as one pass over the window (largest difference 0.0000). Once a game is longer than the memory the two differ (0.11 on outputs of size 0.8), because cached frames were computed when they could still see older ones. HAL's cache has the same property.

**Speed** (random weights, delay 10, one simulator thread, both players of every game on the student; the conversion from simulator columns to model features is not in this number yet):

| Student | Memory | Games at once | Game frames a second | Time in model | Time in simulator | GPU |
|---|---|---|---|---|---|---|
| 6.7M (width 256, 6 layers) | 128 frames | 256 | 9,757 | 49% | 51% | 0.5 GB |
| 6.7M | 128 | 1,024 | 15,025 | 23% | 77% | 1.7 GB |
| 6.7M | 256 | 1,024 | 14,702 | 28% | 72% | 3.2 GB |
| 14.8M (width 384, 6 layers) | 128 | 1,024 | 14,120 | 27% | 73% | 2.6 GB |
| 14.8M | 256 | 1,024 | 13,617 | 32% | 68% | 4.9 GB |

That is about eight times HAL in the farm and ninety times one Dolphin. The simulator, on one core, is now the limit: the model alone would allow 45,000 to 65,000. Size and memory length barely change the speed, so they can be chosen for strength.

## Verdict
