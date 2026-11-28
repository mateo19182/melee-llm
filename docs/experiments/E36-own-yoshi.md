---
id: E36
title: Our own model: Yoshi fine-tune
date: 2026-11-28
status: done
result: 1 billion Yoshi frames, no rollbacks; validation on Yoshi 0.709 at no delay and 0.711 at 12 frames (0.740 and 0.743 at step 2,000). In the farm the fine-tune beat the base 56 of 64 at both delays, Faynt's 10M Base 62 to 64 of 64 (base 56 to 58), and at 12 frames E33's RL Yoshi 40 to 41 of 64 (base 19 to 25); 0 of 64 against Phillip's Yoshi. On Dolphin at no delay 20 of 24 against CPU 9 and 7 of 24 against HAL's aMSa Yoshi, 262 Elo over 48 games
verdict: fine-tuning on the character works and step-0122070 is RL's starting model. Imitation at 12 frames now beats the RL of E33, yet never Phillip's Yoshi, and at no delay it is still below HAL's aMSa Yoshi (393 Elo). The name code does not matter for Yoshi
runs: own-yoshi-ft
prs: 127, 131
follows: E35
---

## Question

Stage 2 of the [plan](../own-model.md): does fine-tuning the all-character base (E35) on Yoshi's games alone make a better Yoshi, at no delay and at 12 frames? This model is where RL starts (stage 3), so the answer also picks RL's starting weights.

## Setup

`own.train own-yoshi-ft --init` E35's `own-pre-10m-b/ckpt/step-0793457`, with `--character YOSHI --boost 2`:

- **Data:** only Yoshi's side of the games with a Yoshi in them (73.5k sides in HAL's dataset, about 0.6 billion frames). Games won by a Master or a pro are used twice per pass.
- **Budget:** 1 billion frames (122,070 steps of batch 32, about 5 hours), so each game is seen one to two times.
- **Learning rate:** peak 3e-5 after 500 warm-up steps, cosine decay to 10%. E35 ended at 1e-5.
- Everything else as E35: both delays (`--delays 0,12`), float32, the rollback guard. Validation every 2,000 steps on 240 held-out Yoshi sides; a weight folder every 10,000 steps.

## Judged by

Yoshi in the farm at 64 games per match (`train/own/eval-yoshi.sh`), the fine-tune and the base in the same matches so they compare directly:

- **Validation loss on Yoshi** per delay, against the base's at step 0. A loss that rises while training loss falls means the 73.5k sides are being memorised; then an earlier weight folder is the result.
- **Fine-tune against the base,** both with code 14 at no delay and 15 at 12 frames.
- **Against Faynt's 10M Base** at no delay (the base won 58 of 64 with code 18).
- **At 12 frames** against `yoshi-rl-3-ladder` step 1795 at the same delay (the base won 25 of 64) and Phillip's Yoshi (0 of 64).
- **Name code:** Master winner (14 and 15) against pro winner (18 and 19) in the Faynt Base and RL Yoshi matches. aMSa is the one pro Yoshi, so here the pro code may be the better one.
- **Dolphin league** for the final choice: Yoshi at no delay against CPU 9 and against `hal-amsa-yoshi` (the best imitation Yoshi so far, 385 Elo), 24 games each.

## Result

**The run.** `own-yoshi-ft` reached step 122,070 on 11-28 at about 08:00 with no rollbacks, at 41,000 frames a second while farm matches shared the GPU and 56,000 alone. Validation on Yoshi fell throughout: 0.740 and 0.743 (no delay, 12 frames) at step 2,000, 0.720 and 0.723 at step 56,000, 0.709 and 0.711 at the end; the best was 0.707 at step 114,000, so the Yoshi games were not memorised. The mean top button logit moved back from -131 to -116.

**Farm, 64 games each** (`train/own/eval-yoshi.sh`, logs `/mnt/data/melee/runs/own-yoshi-ft-eval.log` and `own-yoshi-base-eval.log`):

| Yoshi (name code) | Opponent | Delay | Fine-tune: wins, stocks a game | Base: the same |
|---|---|---|---|---|
| 14 | The base, code 14 | 0 | 56, +1.52 | |
| 15 | The base, code 15 | 12 | 56, +1.56 | |
| 14 (Master winner) | Faynt 10M Base | 0 | 62, +2.62 | 56, +1.70 |
| 18 (pro winner) | Faynt 10M Base | 0 | 64, +2.61 | 58, +1.83 |
| 15 | `yoshi-rl-3-ladder` step 1795 | 12 | 41, +0.55 | 19, −0.80 |
| 19 | `yoshi-rl-3-ladder` step 1795 | 12 | 40, +0.44 | 25, −0.31 |
| 15 | Phillip's Yoshi (18 frames) | 12 | 0, −3.08 | 0, −3.67 |

Master and pro codes play the same for Yoshi.

**Dolphin league, Yoshi at no delay with code 18, 24 games each** (`train/own/yoshi-dolphin.sh`, log `/mnt/data/melee/runs/own-yoshi-dolphin.log`):

| Opponent | Wins | Stocks a game |
|---|---|---|
| CPU 9 (Fox) | 20 of 24 | +1.58 |
| HAL's aMSa Yoshi | 7 of 24 | −0.67 |

League rating 262 Elo over these 48 games (CPU 9 = 0; HAL's aMSa Yoshi 393).

## Verdict

Fine-tuning on one character works: the fine-tune beats the base it came from 7 games in 8 at both delays, and `own-yoshi-ft/ckpt/step-0122070` is the starting model of stage 3.

- At 12 frames, a few hours of imitation now beat the model that E33's RL took days to make from a no-delay start. Training with the delay from the first frame was the right call.
- It has still never won a game against Phillip's Yoshi, and at no delay it sits below HAL's aMSa Yoshi. Imitation at this size is not enough; RL (E37) has to supply the rest.
- Either name code can be used for Yoshi.
