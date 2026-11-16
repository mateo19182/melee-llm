# Experiment log: our own Yoshi bot

One entry per experiment, newest last. This is the record of what we tried, what happened and what we concluded; [status](status.md) only says where things stand.

## Rules

1. **Write the entry before launching**: the question, the setup, and how it will be judged. Fill in the result and verdict when it ends, including when it fails or is abandoned.
2. **The judge is the Dolphin league** (`python -m meleebot.league`, CPU 9 = 0 Elo), not validation loss or simulator win rate. Both have misled us (E07 vs E12, E09).
3. **State the delay and the number of games** with every result. Under about 30 games a rating moves by 100 Elo or more.
4. **Name the artifacts**: run directory, scripts, PR. Run directories live in `data/train/runs/` (not in git); each has `run.json` (settings) and `log.jsonl` (loss curve). League games are in `data/train/league/games.jsonl`.
5. One change per experiment where possible. If a run changes several things, say so in the verdict.

Template:

```markdown
### E00 · name · date
**Question.** What we want to know.
**Setup.** Model, data, settings, the one thing that changed. Run: `data/train/runs/NAME`.
**Judged by.** Which games, how many, at what delay.
**Result.** Numbers.
**Verdict.** What we now believe, and what it changes.
```

## Index

Loss is validation loss (sum over the four controller heads). "vs CPU 9" is wins of games as Yoshi against the level 9 Fox. Elo is the league's, with delay after `@`.

| # | Date | Experiment | Result | Verdict |
|---|---|---|---|---|
| E01 | 11-14 | `bc-6m-v1`: first clone, 5.4M | loss 0.783; 0 of 12 vs CPU 9 | Too small |
| E02 | 11-14 | `bc-20m-v2`: 20.7M, rotary positions | loss 0.683; 1 of 12 | Bigger helps a little |
| E03 | 11-14 | `bc-20m-amsa`: aMSa's games only | loss 0.662; 6 of 36 | One pro is not enough data |
| E04 | 11-14 | `bc-20m-v3`: all Yoshi games in HAL's dataset | loss 0.644; 10 of 36; −241 @3 | More data helps |
| E05 | 11-15 | Optimiser comparison, 5k steps each | Muon 0.710 vs AdamW 0.806 | Muon with warmup-stable-decay |
| E06 | 11-15 | `pre-20m-all`: pretrain on every character | loss 0.632; −433 @3 as Yoshi | A base, not a player |
| E07 | 11-15 | `bc-20m-ft`: fine-tune E06 on Yoshi, delays 2–4 | loss 0.622; 5 of 6; −66 @3 | **Best of our own models** |
| E08 | 11-14/15 | stomped.dev with our clone | 8 of 36 finished matches | Too weak, switched off |
| E09 | 11-15 | `rl-yoshi-1`: self-play PPO in the simulator | 77% vs teacher, then collapse; −141 and −270 @3 | Sim gains did not transfer |
| E10 | 11-16 | `rl-yoshi-2`: PPO with stability fixes | stable, but 77% → 31% vs teacher | Stability was not the problem |
| E11 | 11-16 | `fox-20m-check`: can our pipeline reproduce HAL's 20M Fox? | loss 0.661; 2 of 24 (HAL: 95%) | **No. Own pipeline stopped** |
| E12 | 11-16 | Why E11 fails | holds inputs: stick changes on 8.6% of frames, humans 22.9% | Behaviour, not plumbing |
| E13 | 11-16 | `fox-20m-padfix`: fine-tune to fix E12 | crashed at step 1,000 | Abandoned |
| E14 | 11-16 | HAL 247M imitating aMSa as Yoshi | 403 Elo; HAL "Master" Yoshi 220 | **Best Yoshi, no training** |
| E15 | 11-16 | Steering sweep: return target, temperature | return target 40: 561 | +160 Elo for free |
| E16 | 11-16 | Input delay 3, 6, 10 on E14 | 135, 87, 176 against 403 | Delay costs 200–300 Elo |
| E17 | 11-16 | stomped.dev with E15 at 11 frames ahead | live; first match won | Running |

## Entries

### E01–E04 · behaviour cloning from scratch · 2026-11-14

**Question.** How far does plain behaviour cloning of Yoshi players get, and what moves it: size or data?

**Setup.** Decoder-only transformer that predicts the next frame's controller from game state and the previous input. All trained from scratch, batch 256 (E01: 64), context 256 frames.

| Run | Model | Data | Steps |
|---|---|---|---|
| `bc-6m-v1` | 5.4M (6×256) | ranked Yoshi replays | 30k |
| `bc-20m-v2` | 20.7M (8×448), rotary | same (`yoshi-v1`, 256M frames, 22.7k games) | 15k |
| `bc-20m-amsa` | 20.7M | aMSa only (181M frames, 21.7k games) | 15k |
| `bc-20m-v3` | 20.7M | every Yoshi game in HAL's dataset, Platinum to Pro (`yoshi-hal-v3`, 440M frames, 44k games) | 30k |

**Judged by.** Games against CPU 9 Fox with no delay (`meleebot.evaluate`), 12 to 36 each.

**Result.** Loss 0.783 → 0.683 → 0.662 → 0.644. Wins: 0 of 12, 1 of 12, 6 of 36, 10 of 36. In the league `bc-20m-v3` rates −241 at delay 3 (61 games).

**Verdict.** Data mattered more than anything else we changed. None of these beats CPU 9 reliably, where HAL's 20M Fox, the same kind of model, wins 95%. That gap is what E11 later tested head on.

### E05 · optimiser comparison · 2026-11-15

**Question.** Which optimiser and schedule for the big pretrain?

**Setup.** Four 5,000-step runs of the 20.7M model on `pretrain-v1` (1.42B frames): `bench-A` AdamW + cosine + dropout 0.1, `bench-B` AdamW + cosine, `bench-C` AdamW + warmup-stable-decay, `bench-D` Muon + warmup-stable-decay.

**Judged by.** Validation loss at step 5,000. No games.

**Result.** 0.811, 0.806, 0.759, 0.710.

**Verdict.** Muon with warmup-stable-decay, as Faynt and HAL use. Judged on loss alone, and only at 5k steps.

### E06–E07 · pretrain on everyone, fine-tune on Yoshi · 2026-11-15

**Question.** Does pretraining on all characters and then fine-tuning on Yoshi beat training on Yoshi alone? Does training with delayed observations make the bot usable over netplay?

**Setup.**
- `pre-20m-all`: 60k steps, Muon, on `pretrain-v1` (Pro and Master games of every character, 141k perspectives, 1.42B frames).
- `bc-20m-ft`: starts from it; 20k steps on `yoshi-hal-v3`, AdamW, cosine, learning rate 2e-4, dropout 0.1, observation delay drawn from 2–4 frames per window.

**Judged by.** The league at delay 3 (the first experiment rated there), 86 and 90 games.

**Result.** Loss 0.632 and 0.622. `pre-20m-all` −433; `bc-20m-ft` −66, with 5 of 6 against CPU 9 and its first wins off MIMIC Marth and HAL's Master Yoshi. It still loses to Phillip, HAL Fox and Faynt.

**Verdict.** Our best own model: about 175 Elo over `bc-20m-v3`. Two things changed at once (pretraining and delay training), so we can't say how much each gave.

### E08 · stomped.dev with our clone · 2026-11-14 to 15

**Question.** How does our clone do against other people's bots on [stomped.dev](https://stomped.dev)?

**Setup.** `meleebot.stomped` from the home server, 130 ms round trip to the arena, so it acts 11 frames ahead. The model was whichever clone was newest at the time.

**Result.** 62 matches logged (`data/stomped/matches.jsonl`): 36 finished, 8 won; 26 ended in a disconnect.

**Verdict.** Too weak at that delay. Switched off on 11-15.

### E09–E10 · self-play PPO in the simulator · 2026-11-15 to 16

**Question.** Can reinforcement learning in melee-sim-light lift `bc-20m-ft` above its teacher?

**Setup.** `meleebot.rl.ppo`. 512 simulated matches, 128-frame unrolls, delay 3. The learner is Yoshi; opponents are the frozen starting model (30%), a recent copy of itself (40%) and the all-character pretrain as seven other characters (30%). Learning rate 1e-5, a KL penalty of 0.1 toward the starting model, reward = stocks plus 0.01 × damage. `rl-yoshi-2` adds a dual-clipped policy loss, skipping of non-finite steps and an entropy floor of 0.3.

**Judged by.** Win rate against the frozen teacher in the simulator, then league games in Dolphin for the snapshots.

**Result.**
- `rl-yoshi-1`: 146 of 189 (77%) against the teacher in the first 100 iterations, 37% in the next 100, then entropy collapsed and the loss went non-finite at iteration 262. League at delay 3, 30 games each: iteration 100 rates −141, iteration 200 −270, against −66 for the teacher.
- `rl-yoshi-2`: ran 1,545 iterations (101M frames, 3.6 hours) without diverging. Win rate against the teacher: 77% in the first 100 iterations, then a steady fall: 59%, 47%, 34%, and 31% at the end. Its snapshots were not league-rated.

**Verdict.** The stability fixes work; the learning does not. The early 77% did not show up in Dolphin, which points at the learner exploiting that one frozen opponent, not getting better. E12 gives a second suspect: the starting model itself plays badly in closed loop. Do not repeat this setup.

### E11–E13 · does our pipeline reproduce HAL's Fox? · 2026-11-16

**Question.** HAL's first post reports a 20M clone of pro Fox winning 95% against CPU 9. Ours never got near that with Yoshi. Is the difference the character and data, or our pipeline?

**Setup.** `fox-20m-check`: the 20.7M model, 45k steps on `fox-pro-v1` (300M frames, 33.6k pro Fox games), delays 0–4.

**Judged by.** 12 games against CPU 9 at delay 0 and 12 at delay 3.

**Result.** Loss 0.661. 1 of 12 at each delay.

**Diagnosis (E12).** Scripts in `/tmp/amsa-peek/diag/` (not kept in git).
- **Plumbing is correct.** The bot's decisions land exactly one frame later on 9,460 of 9,460 frames; live features match the training distributions; the cached one-step path matches the full-window path.
- **Polling drift is not the cause.** Slippi Dolphin ships the fix. It does matter on stomped's arena.
- **The behaviour is wrong.** The stick changes on 8.6% of frames against 22.9% for humans; 33.5% of the time is spent in stick holds longer than 60 frames against 6%. 27 of 47 deaths were self-destructs from held Firefox or air-dodge inputs.
- Lower temperature (0.3, 0.7) won 0 of 15.

**E13.** `fox-20m-padfix`, a fine-tune meant to break the input holding, crashed at step 1,000 with loss 1.692 and was dropped.

**Verdict.** The pipeline is at fault, not Yoshi: the model copies its own previous input and gets stuck once it is the one playing. Mateo stopped the own pipeline here and chose to build on HAL.

### E14 · HAL imitating aMSa · 2026-11-16

**Question.** How good is HAL's released 247M model as a Yoshi, with no training by us?

**Setup.** `weights/hal-250m.hal`, identity `AMSA#0` (21,238 Yoshi games in its training data), default steering (return target 20, temperature 1). League names `hal-amsa-yoshi` and `hal-master-yoshi`. PR #74.

**Judged by.** League, no delay.

**Result.** 403 Elo on 78 games, against 220 for HAL asked to play as a generic Master Yoshi and 398 for Phillip Diamond Fox.

**Verdict.** The best Yoshi we have. At the same delay of 3 frames it rates 135 (E16) against −66 for our own best. Fine-tuning it on Yoshi data was judged not worth it: it has already seen that data, and HAL's training script is frozen to the full dataset.

### E15 · steering sweep · 2026-11-16

**Question.** Do HAL's return target and temperature move its strength?

**Setup.** `hal:AMSA#0` with return target 40 or 70 and temperature 0.8, 30 league games each, no delay. PR #75.

**Result.**

| Setting | Elo | Wins of 30 |
|---|---|---|
| return target 40 | 561 | 23 |
| return target 40, temperature 0.8 | 529 | 22 |
| temperature 0.8 | 440 | 19 |
| default (20, 1.0) | 403 | — |
| return target 70 | 384 | 17 (0 of 6 against HAL Fox) |

**Verdict.** Return target 40 is the best setting found. It now tops our league, above Faynt 10M (482 on 19 games), so the league needs stronger opponents to measure anything better. Only two return targets were tried.

### E16 · input delay · 2026-11-16

**Question.** What does delay cost HAL-as-aMSa?

**Setup.** `hal:AMSA#0,delay=N`, default steering, 13–18 games each. PR #76.

**Result.**

| Delay | Elo | vs CPU 9 | vs Phillip Platinum | vs the no-delay version |
|---|---|---|---|---|
| 3 | 135 | 4 of 6 | 3 of 6 | 0 of 6 |
| 6 | 87 | 5 of 6 | 0 of 6 | 1 of 6 |
| 10 | 176 | 5 of 6 | 0 of 1 | 1 of 6 |

Five of six delay-10 games against Phillip Platinum died with a Dolphin disconnect (cause not found).

**Verdict.** Most of the loss is already there at 3 frames. Few games; the order of 3, 6 and 10 is noise. Return target 40 was not tested with delay.

### E17 · stomped.dev with HAL-as-aMSa · 2026-11-16, running

**Question.** How does the best setting do against other people's bots at the delay stomped forces on us?

**Setup.** `meleebot-stomped` service: `hal:AMSA#0,return_target=40 --lead 11`, from the home server (130 ms round trip). Live since 22:42.

**Result so far.** First match won, against `entropy`, with decisions at 5 ms median.

## Proposed next

In order. Each becomes an entry above when it starts.

1. **A harder yardstick.** Add stronger opponents to the league (Faynt 75M if its weights are public, Phillip's strongest agents at their native delay) and replay E15 against them. Without this we can't measure a better Yoshi.
2. **Finer steering.** Return targets 30, 50, 60 and one more temperature; return target 40 with delay 3. Hours, no training.
3. **A training loop for HAL's model on the 3090**, checked by reproducing its validation loss on held-out aMSa games before anything is trained. Every later step needs it.
4. **Return-conditioned self-improvement.** Play HAL-as-aMSa in the simulator against HAL imitating other pros, then fine-tune on those games labelled with the returns it really got. This is the cheapest form of RL and fits how HAL was trained.
5. **PPO with a KL penalty toward the clone**, as Faynt and slippi-ai do, against that same pool of pros. Gate every snapshot on the Dolphin league (lesson of E09).
