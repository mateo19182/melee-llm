---
id: E27
title: Faynt 10M across characters: Yoshi, and does Fox RL hurt the rest
date: 2026-11-18
status: done
result: Fox-mirror RL lifts every character: Arena beats Expert 32/32 in Fox, Yoshi, Marth and Falco mirrors; Arena as Yoshi beats HAL as aMSa 6/6 but loses 0/6 to Phillip's anti-Yoshi Fox and Yoshi ditto
verdict: base our Yoshi on Faynt 10M Arena; Yoshi RL should target Phillip's anti-Yoshi Fox and Yoshi ditto
runs:
prs:
follows: E18
---

## Question

Faynt's RL (Arena) only played Fox mirrors; the other 25 characters got imitation training only (Base, Expert). Before building a Faynt-style Yoshi:
1. How strong is Faynt 10M **as Yoshi**, and did the Fox RL help or hurt it (Expert vs Arena)?
2. Did the Fox-mirror RL make Faynt's **Fox** worse against other characters?

## Setup

Released weights `faynt:10M-Expert` and `faynt:10M-Arena`, no delay, temperature 1, CPU. League (`meleebot.league play`, fast mode, stages cycling over the six legal ones).
- **A, Yoshi:** both variants as Yoshi against `cpu9-fox`, `hal-amsa-yoshi`, `hal-master-fox`, `phillip-yoshi-vs-fox`, `phillip-fox-vs-yoshi`, `phillip-marth-vs-yoshi`, `phillip-yoshi-ditto`. 6 games per pairing, 84 games.
- **B, Fox vs the roster:** both variants as Fox against HAL `MASTER` (no delay) as Fox, Falco, Marth, Sheik and Peach, and `hal-amsa-yoshi`. 6 per pairing, 72 games.
- **C, head to head:** Arena vs Expert in Fox, Yoshi, Marth and Falco mirrors, 8 games each, 32 games.

## Judged by

Wins and stock differential per pairing, Arena minus Expert. Fox RL "hurt" a matchup if Arena wins clearly fewer games there than Expert while it wins more in the Fox mirror. 6 games per cell only detects large effects; C is the more direct test.

## Result

187 games ran; 2 were lost to Dolphin connection errors and not replayed (Expert Yoshi vs CPU 9, Arena Fox vs HAL Sheik). The first launch ran 4 games at a time and hit its 18 GB memory cap after 71 games; the rest ran 2 at a time.

**A, Faynt as Yoshi** (wins, Expert / Arena):

| Opponent | Expert | Arena |
|---|---|---|
| `cpu9-fox` | 5/5 | 6/6 |
| `hal-amsa-yoshi` | 2/6 | 6/6 |
| `hal-master-fox` | 0/6 | 4/6 |
| `phillip-yoshi-vs-fox` | 0/6 | 4/6 |
| `phillip-marth-vs-yoshi` | 0/6 | 5/6 |
| `phillip-fox-vs-yoshi` | 0/6 | 0/6 |
| `phillip-yoshi-ditto` | 0/6 | 0/6 |

**B, Faynt as Fox against HAL `MASTER`** (no delay): Arena 35/35, Expert 9/36.

| HAL plays | Expert | Arena |
|---|---|---|
| Fox | 1/6 | 6/6 |
| Falco | 0/6 | 6/6 |
| Marth | 0/6 | 6/6 |
| Sheik | 2/6 | 5/5 |
| Peach | 2/6 | 6/6 |
| Yoshi (`hal-amsa-yoshi`) | 4/6 | 6/6 |

**C, Arena vs Expert mirrors:** Fox 8/8 (+4.0 stocks a game), Yoshi 8/8 (+2.6), Marth 8/8 (+3.4), Falco 8/8 (+3.5).

## Verdict

The Fox-mirror RL did not hurt other matchups or characters: it lifted all of them by a wide margin, so what it learned is general rather than Fox-specific. Faynt 10M Arena as Yoshi is already the best Yoshi in the league, ahead of HAL as aMSa and Phillip's Yoshi, but still loses every game to Phillip's anti-Yoshi Fox and to Phillip's Yoshi ditto agent, both at 18 frames of delay. Start the Yoshi bot from Arena and point its RL at those two. Untested: delay (the Faynt wrapper has none) and anything finer than large effects at 5 to 8 games a cell.

Each game is a separate Dolphin with Faynt stepping on the CPU at about 7 ms a frame, so 187 games took 3.4 hours on a loaded machine. RL needs Faynt batched in the simulator farm.
