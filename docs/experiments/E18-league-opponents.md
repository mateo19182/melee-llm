---
id: E18
title: Stronger league opponents
date: 2026-11-16
status: done
result: our best Yoshi wins 2 of 26 against Phillip's anti-Yoshi agents; Phillip's Yoshi rates 688 against our 402
verdict: yardstick found, and Phillip's Yoshi is a stronger Yoshi than HAL as aMSa
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

160 games finished; 32 more died with a Dolphin disconnect. Ratings are Bradley–Terry with CPU 9 at 0.

**Our best Yoshi, `hal:AMSA#0,return_target=40`, no delay** (wins of finished games):

| Opponent | Wins | Opponent's rating |
|---|---|---|
| Phillip Fox trained against Yoshi | 0 of 6 | 918 |
| Phillip Marth trained against Yoshi | 0 of 4 | 717 |
| Phillip Peach trained against Yoshi | 0 of 6 | 712 |
| Phillip Falco trained against Yoshi | 0 of 4 | 659 |
| Phillip Sheik trained against Yoshi | 2 of 6 | 576 |
| Phillip `super-gm` Fox | 0 of 4 | 834 |
| Phillip Fox v6.2 | 0 of 2 | 543 |
| Phillip Falco v6.2 | 2 of 6 | 502 |
| Phillip Marth v6.2 | 3 of 4 | 254 |
| Phillip's ditto Yoshi | 1 of 4 | 544 |
| Faynt 75M | 2 of 7 | 483 |

The default-steering Yoshi (`hal-amsa-yoshi`) did the same or worse: 1 of 28 against the anti-Yoshi agents and `super-gm`, 2 of 6 against Fox v6.2, 1 of 6 against Faynt 75M.

**Phillip's Yoshi agents, 18 frames of delay:**

| Phillip Yoshi | Opponent | Wins |
|---|---|---|
| vs Fox | Phillip Diamond Fox | 6 of 6 |
| vs Fox | Faynt 75M | 6 of 6 |
| vs Fox | CPU 9 | 6 of 6 |
| vs Fox | HAL Master Fox | 4 of 6 |
| vs Fox | Phillip Fox v6.2 | 4 of 6 |
| vs Fox | Phillip Fox trained against Yoshi | 1 of 6 |
| vs Fox | Faynt 10M | 0 of 6 |
| vs Marth | Phillip Marth trained against Yoshi | 5 of 6 |
| vs Sheik | Phillip Sheik trained against Yoshi | 4 of 6 |
| vs Peach | Phillip Peach trained against Yoshi | 3 of 6 |
| vs Falco | Phillip Falco trained against Yoshi | 2 of 6 |
| ditto | our best Yoshi | 3 of 4 |

- **The yardstick exists.** Phillip's agents trained against Yoshi beat our best Yoshi 24 games to 2.
- **Phillip's Yoshi is the stronger Yoshi.** `phillip-yoshi-vs-fox` rates 688 over 42 games against our best at 402 over 83, on overlapping Fox opponents, and it does so with 18 frames of delay against our none. Against Diamond Fox it won 6 of 6 where ours won 3 of 6; against Faynt 75M 6 of 6 where ours won 2 of 7.
- **Each matchup Yoshi was trained for one opponent character**; the others have 6 games each, so their ratings (515 to 878) are rough.
- **Errors.** 32 games died with `EnetDisconnected`, all while training jobs shared the machine. The 30 games E19 played afterwards on an otherwise idle machine had none. That points to load, but it is one comparison, not a test.
- **Faynt 75M** runs on the CPU at about 5 cores a game. Four at once stalled for 30 minutes, so its games ran last, two at a time.
- **Phillip's imitation-only Yoshi** cannot play as set up: its model needs a player name. It is out of the roster until that is added.

## Verdict

Two outcomes.

1. The league can measure again. The yardstick for a Yoshi model is the five anti-Yoshi agents plus `super-gm` Fox; our best wins 2 of 30 against them, so any real improvement will show.
2. HAL as aMSa is not the best published Yoshi. Phillip's matchup Yoshi agents are about 290 points stronger with 18 frames of delay built in, and slippi-ai is the only project that publishes the RL code that made them. This changes what E20 and E21 should start from; that decision is open.
