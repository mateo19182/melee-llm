---
id: E32
title: Faynt-style RL for a Yoshi
date: 2026-11-19
status: done
result: from Faynt 10M Arena, 1,000 PPO steps in the farm took the Yoshi from losing to winning every Phillip anti-Yoshi agent; in Dolphin step 400 won 72 of 78 against ten opponents and step 1000 won 85 of 88, 8 of 8 against step 400. With any input delay it collapses (0 of 48 against the anti-Yoshi Fox from 1 frame); fed its own pads it keeps 42 of 48 at 1 frame but none from 4
verdict: the strongest Yoshi we have, at no delay. It cannot play on stomped.dev (10 frames of delay from this server) until it is trained with the delay: next, the same RL at delay 10
runs: yoshi-rl-1
prs: 109
follows: E27, E31
---

## Question

Faynt 10M Arena as Yoshi beats every Yoshi in our league but loses every game to Phillip's anti-Yoshi agents (E27). Faynt's RL only played Fox mirrors. Does the same RL recipe, run on Yoshi against those agents and against itself, fix that?

## Setup

`train/farm/rl.py`, in the simulator farm (faithful to Dolphin, E31), on the local 3090.

- **Start and reference:** Faynt 10M Arena. Its weights are both the starting policy and the KL anchor.
- **Recipe:** the paper's 10M "leash" run (Table 2, appendix E.6).
  - Learning rate 1e-4, Adam.
  - Policy-gradient weight 3, behaviour KL 0.3, reference KL 0.003 in each direction.
  - Log-space clip 0.01, reward half-life 8 s, unnormalised advantages.
  - Two PPO epochs per step, an update guard at KL 0.005, no entropy bonus.
  - slippi-ai's zero-sum reward: stocks, damage, ledge grabs on a vulnerable opponent, time far offstage, approach.
- **Rollouts:** 128 frames each, scored from the actor's stored attention cache. The learner reproduces the actor's log-probabilities to within 7×10⁻⁷.
- **Value network:** separate, 2 blocks of width 128 with its own encoder. It reads the 128 frames before each rollout and starts with 20 value-only steps.
- **Lanes:** 64 games at once, Yoshi for the learner, no delay. Rules: 4 stocks, 8 minutes, the six legal stages.
  - 32 Yoshi dittos with the learner on both sides.
  - 32 games against Phillip agents at their own 18 frames of delay: anti-Yoshi Fox 8, Marth 8, Falco 4, Sheik 4, Peach 4, and Yoshi ditto 4.
- **Step size:** each step is 2,048 frames per game, so 196,608 learner decisions.

Differences from the paper:
- Yoshi instead of Fox.
- Fixed Phillip opponents next to self-play.
- Games with stocks and a timer.
- Our Arena start replaces their supervised start as the reference.

## Judged by

`train/farm/rl_eval.py`: every 50th checkpoint and the start play 48 farm games each as Yoshi, against:
- Phillip's anti-Yoshi Fox;
- Phillip's anti-Yoshi Marth;
- Phillip's Yoshi ditto agent;
- the starting Faynt Arena Yoshi.

Win rate and stock margin are tracked against step. A checkpoint that clearly beats the start and the Phillip agents goes to the Dolphin league before any claim.

The web Training page (melee.m19182.dev/training) charts the run, and its lanes play live on All matches.

## Result

**The run.** 1,000 steps, 131M game frames (about 25 days of play at game speed), in 25.5 hours of running time:
- about 1,850 frames a second alone;
- about 1,200 while the evaluations or Dolphin shared the machine.

It was killed once, at step 406, when the machine ran out of memory. Other services held about 40 GB, and this job is set to be killed first. It resumed from step 400 sixteen hours later. The six lost steps were dropped from the log.

Training signals (the policy learns from step 24):

| Step | Reward per minute | KL to the start | Entropy |
|---|---|---|---|
| 24 | −0.11 | 0.001 | 0.62 |
| 100 | +0.14 | 0.021 | 0.60 |
| 200 | +0.50 | 0.056 | 0.54 |
| 400 | +1.03 | 0.105 | 0.56 |
| 700 | +1.63 | 0.143 | 0.62 |
| 1000 | +1.28 | 0.178 | 0.67 |

The leash held the policy close to the start: KL to Arena grew steadily, by about 0.02 per 100 steps, without a jump. Entropy stayed between 0.54 and 0.69, so the policy did not collapse onto a few habits.

**Farm evaluations** (wins of 48, stock margin a game):

| Step | Anti-Yoshi Fox | Anti-Yoshi Marth | Phillip Yoshi ditto | Starting Arena Yoshi |
|---|---|---|---|---|
| 0 | 11 (−1.3) | 6 (−1.5) | 8 (−1.1) | 23 (−0.1) |
| 100 | 21 (−0.2) | 11 (−1.0) | 38 (+0.9) | 42 (+1.5) |
| 200 | 28 (+0.4) | 39 (+1.2) | 43 (+1.9) | 48 (+2.7) |
| 400 | 43 (+1.7) | 46 (+2.4) | 46 (+2.6) | 48 (+3.3) |
| 600 | 47 (+2.2) | 48 (+2.6) | 48 (+2.9) | 48 (+3.3) |
| 1000 | 48 (+2.9) | 48 (+3.1) | 48 (+3.2) | 48 (+3.5) |

- The ditto and the self-match improved first.
- Fox came steadily.
- Marth stayed flat until step 100, then jumped between 100 and 200.
- From step 750 every opponent loses every game. Stock margins kept rising to the end.

**Dolphin league** (`meleebot.league`, no delay, 8 games a pairing, stages cycling):

| Opponent | Arena start (E27) | Step 400 | Step 1000 |
|---|---|---|---|
| Phillip anti-Yoshi Fox | 0/6 | 7/8 (+1.8) | 8/8 (+2.6) |
| Phillip anti-Yoshi Marth | 5/6 | 5/7 (+1.3) | 7/8 (+2.6) |
| Phillip Yoshi ditto | 0/6 | 8/8 (+2.6) | 8/8 (+3.0) |
| Phillip anti-Yoshi Falco | – | 6/8 (+0.9) | 8/8 (+2.1) |
| Phillip anti-Yoshi Sheik | – | 7/8 (+1.4) | 6/8 (+1.4) |
| Phillip anti-Yoshi Peach | – | 8/8 (+2.0) | 8/8 (+2.4) |
| Phillip Yoshi-vs-Fox | 4/6 | 8/8 (+3.5) | 8/8 (+3.1) |
| HAL as aMSa (Yoshi) | 6/6 | 8/8 (+3.4) | 8/8 (+3.2) |
| HAL Master Fox | 4/6 | 7/7 (+2.4) | 8/8 (+2.6) |
| Arena start (Yoshi) | – | 8/8 (+3.1) | 8/8 (+3.5) |
| Step 400 | – | – | 8/8 (+2.8) |

- Step 400 won 72 of 78. Two games were lost to Dolphin connection errors and not replayed.
- Step 1000 won 85 of 88, all 8 against step 400. Its only losses were 2 to the Sheik and 1 to the Marth. The later training was real progress, not tuning to the four farm opponents: it also won by more against the Falco, which the farm never evaluated.
- The farm's verdicts held in Dolphin:
  - the two agents that beat the Arena start every time (anti-Yoshi Fox, Phillip's Yoshi ditto) went from 0 of 12 to 15 of 16 at step 400;
  - Marth was the weakest matchup at step 400 in both the farm and Dolphin.
- League Elo, with CPU 9 Fox at 0: step 1000 1299, step 400 1066. That puts step 1000 above Faynt Arena playing Fox (1193), and above every Phillip agent by 400 or more.

**Delay.** Our wrapper ran Faynt with no delay, as the paper does, and so did the whole run. stomped.dev needs a pad 11 frames ahead from this server, which is 10 frames of delay. `farm.faynt` now takes `delay=N`: the pad chosen after reading frame F lands on frame F + 1 + N.

Step 1000 against the anti-Yoshi Fox, 48 games per row:

| Delay (frames) | 0 | 1 | 2 | 4 | 6 | 10 |
|---|---|---|---|---|---|---|
| As is | 48 (+2.9) | 0 (−2.7) | 0 (−3.5) | 0 (−3.8) | 0 (−4.0) | 0 (−4.0) |
| Reading its own pads (`own=1`) | 48 (+3.0) | 42 (+1.4) | 20 (−0.5) | 0 (−3.2) | — | 0 (−3.9) |

- The starting Arena model fails the same way: 11 wins at no delay, 0 at 1 and at 10. This is how Faynt models behave, not something the RL introduced.
- Most of the one-frame collapse comes from the controller input. The model reads its own controller from the game, and expects to see the pad it chose one frame ago. Under delay it sees an older pad and stops making sense.
- Feeding it the pad it last chose (`own=1`, now also the `own` setting of `melee_llm/bots/bot_faynt.py`) fixes 1 frame of delay.
- It does not fix the delay itself. A policy trained to react on frame F + 1 loses everything from 4 frames on.

**stomped.dev.** `meleebot.stomped` now serves Faynt checkpoints (`faynt:VARIANT --lead 11`) through the bot server, as it serves HAL. It reads its own pads by default. It passed the local arena's protocol check, and its pads landed on time when the machine was not loaded. It is not deployed: at 10 frames of delay it would lose every game. The live bot stays paused.

## Verdict

Faynt's RL recipe works for a Yoshi in our farm, and what it learns carries over to Dolphin. 1,000 steps turned a Yoshi that lost every game to Phillip's anti-Yoshi agents into one that beats them by 2 to 3 stocks. That makes it the strongest Yoshi we have, by a wide margin.

It is strong only without delay, and stomped.dev needs 10 frames from here. The next step is the same RL at the delay we serve (E33):
- start from step 1000;
- give the model its own pads;
- raise the delay in steps from 1 to 10;
- credit each action from the frame it lands on.

Phillip's agents show the delayed version is learnable: they were trained with RL at 18 frames.

The paid alternative is hosting near the arena (US East). Even with no round trip, stomped's minimum lead is 2 frames, which is 1 frame of delay. Reading its own pads, step 1000 keeps 42 of 48 there, but that needs a decision under about 9 ms and a rented machine.
