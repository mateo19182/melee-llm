---
id: E31
title: The simulator reproduces Dolphin games frame for frame
date: 2026-11-19
status: done
result: given each replay's recorded inputs and random seeds, the simulator reproduces 406 of 411 of our Dolphin bot games and 36 of 40 random human ranked Yoshi games frame for frame to the end; the optimised build plays bit-identical frames
verdict: the farm's physics are Dolphin's; what differs is only the random number stream, which changes which games happen, not how likely each outcome is
runs:
prs:
follows: E30
---

## Question

E30 showed that the farm/Dolphin gaps were a Dolphin bug. Is the simulator itself faithful, or did it just happen to agree on 11 pairings? Earlier checks (`melee_llm/sim/parity.py`) stopped at the first random choice that came out differently, so they covered game openings, not whole games.

## Setup

**Randomness.** Melee draws all its randomness from one generator. Slippi records its value before each fighter's frame, and replay playback restores it there. The simulator's own validator (melee-brute `tools/validation/validate_replay.py`) does the same. Slippi online also resets it every frame (to `base + 65536 * frame`), so netplay games are fully determined by inputs plus those seeds. With the seeds forced, any drift is a physics difference.

**Replays.**
- All 445 of our Dolphin replays (`/mnt/data/melee/league-replays`: league, HAL dida, HAL delay, HAL train loop). These are bots of every kind on our headless Dolphin. 34 were truncated or unreadable and are left out.
- 40 random human games from `/mnt/data/melee/ranked-replays/slp/YOSHI` (2023 ranked, Slippi 3.14 to 3.16). The dataset strips `playedOn`, so they run with `--played-on dolphin --diagnostic`. These versions don't record raw c-stick values, and players differed in which UCF fixes they had, so each was tried under all 32 combinations of the 5 UCF switches.

**Build.** The validator binary and the farm's Python library compile the same melee-brute commit (d3832724).

```sh
# in a melee-brute checkout, with game data at data/
python -m tools.validation.validate_replay REPLAY.slp --diagnostic --played-on dolphin [--no-ucf cardinals_1_0]
```
`--played-on` and `--no-ucf` come from melee-brute PR #19.

## Judged by

Every field the validator compares (positions, speeds, actions, action frames, percent, shields, items and flags), on every frame.

## Result

**Our Dolphin bot games: 406 of 411 exact to the last frame.** The rest:
- 2 differ in one status-flag bit for 190 to 315 frames, then resync. Positions and actions match throughout.
- 1 differs in its last 21 frames.
- 2 diverge for real: Peach on Yoshi's Story is moved during her entry at frame -120, and Fox vs Yoshi on Yoshi's Story differs in a knockback at frame 1,040. Both unexplained; three other Peach games on Yoshi's Story pass.

Turning UCF's 1.0 cardinals on or off changes none of them: bots never send the near-full stick values it rounds.

**Human ranked games: 36 of 40 exact to the last frame** under the right UCF settings, 99.65% of all frames. The other 4 drift by 0.0375 units for a few hundred frames or fewer, then resync. Under the validator's default (every UCF fix on), only 9 passed. Most failures were the 1.0 cardinals fix, which these players didn't have. These games include Yoshi's shield and spot dodges, analog shields and platforms.

**Optimised build.** The farm loaded melee_sim's fallback `-O0` library. `make python-release` builds the optimised one. Over 192,000 random-input frames (26 characters, 6 stages, analog triggers), it produced an identical hash of every frame. It steps 39,300 frames a second on one core against 7,600. The farm now uses it when it is built. Farm games don't get faster yet, because the models set the pace. Faynt Arena Yoshi vs Fox, 512 games on 8 workers, ran at 6,853 and 6,808 frames a second on the optimised build and 6,686 on `-O0`; it frees CPU for when the simulator's share grows. With 2 workers both builds gave identical games. With 8 workers, totals differ slightly between runs of the same build (3,418,227 and 3,419,569 frames): the models' GPU arithmetic is not deterministic when several processes share the GPU.

## What this means

- **Physics:** the farm plays Melee as Dolphin does.
- **Inputs:** E30 checked controller input against Dolphin. Sticks and buttons were exact, and triggers are exact since the fix.
- **Observations:** what each bot reads is checked against libmelee's parse of Slippi events (`--check`, E28 and E29).
- **Randomness:** the simulator's generator is not seeded per frame like Slippi online's. The same seed and inputs repeat exactly in the farm but play out differently on Dolphin. Outcomes are as likely in both.

**Default changed:** `farm.run` now plays with UCF's 1.0 cardinals on, matching current Slippi and our Dolphin. `--no-ucf` turns it off. Earlier runs all passed `--ucf`, and bot games don't depend on it.
