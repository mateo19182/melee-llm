---
id: E18
title: Stronger league opponents
date: 2026-11-16
status: running
result: partial: 2 of 26 against Phillip's anti-Yoshi agents
verdict:
runs:
prs: 81
follows: E15
---

## Question

Our best Yoshi (E15) tops the league, so the league can no longer tell a better model from an equal one. How does it do against the strongest published bots, and against Phillip's own Yoshi agents?

## Setup

New roster entries, all from weights already public:
- **Faynt 75M** (`faynt-75m-fox`), no delay.
- **Phillip's newest agents**: `super-gm`, and the per-character v6.2 Fox, Marth and Falco (21 frames of delay).
- **Phillip agents trained against Yoshi** (18 frames of delay): Fox, Marth, Falco, Sheik, Peach.
- **Phillip's Yoshi agents**, as rivals for ours: imitation only, ditto, and one per matchup (Fox, Marth, Falco, Sheik, Peach).

Phillip plays with its built-in delay and our Yoshi with none, as in the rest of the league.

## Judged by

League, no delay for our Yoshi, 6 games per pairing:
- `hal:AMSA#0,return_target=40` against the twelve new non-rival opponents and Phillip's ditto and imitation Yoshi.
- `hal-amsa-yoshi` (default steering) against seven of them, to tie the new ratings to the old scale.
- Phillip's matchup Yoshi against the same Fox opponents ours faced, and each other matchup Yoshi against its target.

The question for later experiments is whether at least a few opponents beat our Yoshi clearly; those become the yardstick.

## Result

Running. So far, `hal:AMSA#0,return_target=40` with no delay (wins of finished games):

| Opponent | Wins | Games lost to errors |
|---|---|---|
| Phillip Fox trained against Yoshi | 0 of 6 | 1 |
| Phillip Marth trained against Yoshi | 0 of 4 | 2 |
| Phillip Falco trained against Yoshi | 0 of 4 | 2 |
| Phillip Sheik trained against Yoshi | 2 of 6 | 0 |
| Phillip Peach trained against Yoshi | 0 of 6 | 0 |
| Phillip `super-gm` Fox | 0 of 4 | 2 |
| Phillip Fox v6.2 | 0 of 2 | 4 |
| Phillip Marth v6.2 | 3 of 4 | 2 |
| Phillip Falco v6.2 | 2 of 6 | 0 |
| Phillip's ditto Yoshi | 1 of 4 | 3 |
| Faynt 75M | 0 of 1 | 0 |

- **The yardstick exists.** Phillip's agents trained against Yoshi beat our best Yoshi 24 games to 2, with 18 frames of delay against our none.
- **Errors.** 16 games died with a Dolphin disconnect (`EnetDisconnected`), the same fault as in E16. They came while training jobs were loading the machine; whether load is the cause is not established.
- **Faynt 75M** runs on the CPU at about 5 cores a game. Four at once stalled for 30 minutes, so its games now run last, two at a time.
- **Phillip's imitation-only Yoshi** cannot play as set up: its model needs a player name. It is out of the roster until that is added.

## Verdict

