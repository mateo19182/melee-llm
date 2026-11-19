---
id: E30
title: Analog triggers were off in headless Dolphin
date: 2026-11-19
status: done
result: the ExiAI build read every analog trigger below full as 0 and a full press as 25 of 140; with the fix, HAL beats Phillip gm 3/24 (was 21/71) and Faynt's Yoshi beats the anti-Yoshi Marth 2/24 (was 9/23), matching the simulator farm
verdict: every earlier fast and realtime Dolphin result ran without analog shields or airdodges; the simulator was right; fixed in the runner for the headless build
runs:
prs:
follows: E27
---

## Question

The simulator farm (E29 on the farm branch) agreed with Dolphin on every pairing except two with Phillip. In those, Phillip won far more in the simulator: HAL beat Phillip gm 12% of the time there and 30% on Dolphin, and Faynt's Yoshi beat Phillip's anti-Yoshi Marth 11% against 39%. Single-game simulator mode, which runs each bot's own unbatched code, showed the same gap. Which side is wrong?

## Setup

Ruled out first:
- **Physics:** replaying 12 Dolphin replays' inputs in the simulator matches Dolphin field for field. The two drift apart only at random choices, such as which tumble animation plays.
- **UCF:** our Dolphin enables UCF 0.84 with the 1.0 cardinals, which is what the simulator runs with `--ucf`.
- **Timing:** fast mode blocks on every input, and an input set at frame f lands at f + 1 in both.
- **Ports:** results don't depend on port.
- **Behaviour:** stock losses, self-destructs and percent at death look similar in both.

The lead came from HAL's live bot. On Dolphin it reported "executed action differs from sent", and in the simulator it never did. A debug run showed the differences were all in the analog triggers. Two sweeps through Dolphin's fast mode followed:
1. **Through libmelee:** 12,590 random `tilt_analog` / `press_shoulder` calls, comparing the raw values in the replay with `SimController`'s.
2. **Raw pipe values:** 1,025 `SET L` / `SET R` values from 0 to 1, without libmelee's pre-distortion.

## Judged by

The raw values the replay records, and the two disagreeing pairings re-run on Dolphin with the fix, 24 games each, outside the league log.

## Result

**Sticks:** exact (12,590/12,590).

**Triggers:** wrong. libmelee sends an analog trigger as (raw + 0.1)/255 (`fix_analog_trigger`), for a build that reads 255 v. The ExiAI build reads `round(510 v - 255)` (round half to even), clipped to Melee's 0..140, as if the trigger were a centred axis. This formula reproduces all 1,025 measured values. So:
- Every analog press below about 0.91 arrived as 0.
- A full press arrived as 23 to 25, below the shield threshold of 43.

Digital L/R worked. Bots that press the analog shoulder without the digital button, which HAL does constantly and Phillip and Faynt do in part, could not shield or airdodge with it.

**Fix:** `ExiAIController` in `melee_llm/runner.py`, used only for `DOLPHIN_HEADLESS`. It sends `(raw + 255) / 510`, which the build maps to `round(amount * 140)`, the raw value libmelee intends and the simulator uses. Through Dolphin, 7,065/7,065 trigger values were exact. `tests/test_exi_triggers.py` checks the inverse.

**Re-run on Dolphin with the fix:**

| Pairing | Dolphin before | Dolphin fixed | Simulator farm |
|---|---|---|---|
| HAL Master vs Phillip gm | 21/71 (30%) | 3/24 (12%) | 8/64 (12%) |
| Faynt Arena Yoshi vs Phillip anti-Yoshi Marth | 9/23 (39%) | 2/24 (8%) | 7/64 (11%) |

## Verdict

The simulator was right and our Dolphin was wrong. With the fix, Dolphin agrees with the farm on both pairings it disagreed on.

Every earlier `fast` and `realtime` Dolphin result was played without analog triggers: the bench, the league, E27, and local tests of the stomped bot. Bots that use analog shoulders were weakened, by different amounts. E27's ordering of Faynt's Expert and Arena is likely to hold, but ratings and margins need re-running.

Not checked: the mainline build that netplay and `play.py` use. It would not start headless here, so whether it reads triggers correctly is unknown. The live stomped bot sends its inputs to stomped's servers, not to our Dolphin.
