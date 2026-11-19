---
id: E32
title: Faynt-style RL for a Yoshi
date: 2026-11-19
status: running
result: running
verdict: running
runs: yoshi-rl-1
prs:
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

Running.
