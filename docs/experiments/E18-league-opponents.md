---
id: E18
title: Stronger league opponents
date: 2026-11-16
status: running
result:
verdict:
runs:
prs:
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


## Verdict

