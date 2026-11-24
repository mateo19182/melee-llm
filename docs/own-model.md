# Our own model: plan

A plan for training a Melee model from scratch with our own code: an all-character base, a Yoshi specialisation, then RL, at no delay and at 12 frames. Written on 2026-11-24. Nothing here is built yet. **[measured]** marks numbers counted on this machine, **[estimate]** marks numbers inferred and not yet benchmarked. Background: [delay.md](delay.md), [research.md](research.md).

## 1. What we want

| Decision | Choice |
|---|---|
| End product | One base model that plays every character; Yoshi is the first specialisation |
| Delays | Two final models: 0 frames and 12 frames. Another delay must be a short retrain, not a new pretrain |
| Code | Our own, with Faynt's architecture and controller encoding, borrowing from slippi-ai, HAL and ExPhil |
| Objective | Win, against humans as well as bots, so no tuning to one opponent |
| Compute | The 3090 first; rental is fine when it is not wasted (cost estimate before each spend) |

A 12-frame model serves any connection at or below 12 frames by padding. stomped from this server needs 10. Firoiu gives 12 as the lowest human-plausible delay.

## 2. Data

### What is on disk [measured]

The HAL dataset (`/mnt/data/melee/hal-mds`), train split, counted from its manifests:

- 1,295,370 games, 13.1 billion frames; each game gives two player perspectives.
- 821,525 ranked games (Platinum 770k perspectives, Diamond 427k, Master 447k) and 473,845 games from 38 pro folders.
- No ranked data below Platinum.

| Character | Perspectives | Frames |
|---|---|---|
| Fox | 619k | 5.8B |
| Falco | 465k | 4.4B |
| Marth | 297k | 3.0B |
| Captain Falcon | 208k | 1.9B |
| Sheik | 193k | 2.1B |
| Peach | 125k | 1.4B |
| Jigglypuff | 118k | 1.3B |
| Samus, Luigi, Ice Climbers | 77–81k each | 0.85–1.0B each |
| **Yoshi** | **73.5k** | **0.74B** |
| Pikachu, Doc, Ganondorf, DK, Link | 22–42k each | 0.25–0.46B each |
| The other ten | 2–12k each | under 0.14B each |

Yoshi's 73.5k perspectives: 50.7k from pro folders (22.2k of them aMSa's), 8.7k Master, 3.3k Diamond, 10.8k Platinum. Most are against Fox (21.5k), Falco (12.8k) and Marth (7.3k).

Faynt trained on about 840k ranked replays. We have those plus the pro set, and our earlier pretrain used about 10% of it. **The first gain is using all of what we have.**

### Consent

slippi-ai's opt-out list (`slippi_ai/nametags.py`, `BANNED_NAMES`) names Mang0, Wizzrobe, Hungrybox, M2K and OkayP as asking not to be included, and Plup and Medz as not yet asked. HAL's pro set has `mang0` and `m2k` folders. We follow slippi-ai: drop an opted-out player's own perspective, keep them as an opponent.

### More replays

Searched on 2026-11-24 (Hugging Face, Kaggle, Zenodo, Internet Archive, project READMEs):

| Source | Size | New to us | Access |
|---|---|---|---|
| Ranked dumps on Hugging Face (`erickfm/melee-ranked-replays` and copies) | 850k | No: the same six dumps | Download |
| altf4 Public SLP Dataset v3.7 | 94,482 unique tournament replays, CC0 | Yes, older tournament play; 1,781 Yoshi files | Download from Hugging Face |
| [Lucky Stats](https://luckystats.gg/matches) | 56,361 tournament sets, mostly locals | Yes | Per set after sign-in; bulk access would have to be requested |
| A seventh ranked dump, lower ranks | Unknown | Would be | Only in the Slippi Discord, which the search could not read; ask Fizzi or vladfi1 |
| Pro replays (aMSa for Yoshi) | Unknown | Would be | By request to the players or xpilot |
| stomped.dev matches | Every bot match as `.slp` | Yes, but bot games | Public URL per match |

**Human replays are close to exhausted publicly.** The realistic human additions are the tournament set (about 7% more games) and whatever a request in the Discords yields.

Three ways to get more out of the data that do not need new human games:

1. **Mirroring.** Flip every game left to right. It doubles the data for free on symmetric stages; Pokémon Stadium's transformations and Randall on Yoshi's Story are not symmetric and need a check or exclusion. Untested by any published bot that we know of.
2. **Bot games from the simulator farm.** The farm plays about 60 times faster than Dolphin and reproduces it frame for frame ([E31](experiments/E31-sim-faithful.md)). Games by Phillip's 18-frame agents are examples of strong play under delay, which human replays lack; games by Faynt and our RL Yoshi are strong no-delay play. Tag each game's source as an input so the model can tell bot play from human play.
3. **Labels as inputs.** Rank, winner and player identity (HAL steers with these, Faynt's "winner curriculum" ends on 90% Master-winner data), so weak play teaches the game without being imitated at play time.

## 3. Model and training

### Stage 0: the gate

Our earlier from-scratch models reached good loss and then held inputs too long in real games, changing the stick on 8.6% of frames against 22.9% for humans, and lost to CPU 9 ([E11](experiments/E11-fox-20m-check.md)–[E13](experiments/E13-fox-20m-padfix.md)). That was never solved. Feeding the model its own past inputs, which delay needs, is what invites it; Faynt and slippi-ai do so and work.

So before any scale:

- A 10M model on about 1 billion frames.
- Passes when Fox beats CPU 9 on Dolphin at no delay (HAL's 20M Fox wins 95%) and the stick-change rate in closed loop is near the human one.
- Run twice: delay 0 only, and delay 0 and 12 mixed. Comparing both at delay 0 measures what the delay input costs. If mixing hurts, pretrain once per delay.
- The first step of this stage is a real throughput benchmark for the 10M and 75M sizes.

### Stage 1: all-character pretrain

- **Architecture:** Faynt's (transformer, 256-frame context, slippi-ai's 728-way buttons and 85-way stick head). The farm, the RL code and the released Faynt weights stay usable as tools and yardsticks.
- **Delay as an input:** each sequence gets a delay D of 0 or 12. At frame t the model sees the game at t and the input it last committed (the one for t + D), and predicts the input for t + D + 1. This is slippi-ai's alignment with D told to the model, as in ExPhil. D = 0 is Faynt's setup.
- **Other inputs:** character, rank, winner, source (human or which bot).
- **Size:** 10M first. Faynt's 10M is the strongest bot in our league (1193 Elo), and HAL found larger models lost more to slower reactions than they gained. 75M only if the 10M result says size is the limit.

### Stage 2: Yoshi

Fine-tune on the 73.5k Yoshi perspectives, weighted toward winners, Masters and aMSa, at both delays. Other characters follow the same step later.

### Stage 3: RL, one branch per delay

PPO in the farm from the stage 2 model, once at 0 and once at 12:

- A light KL penalty toward the stage 2 model. "Just win" means it is loose, but it stays, to keep answers to human habits that bots never show.
- Train at the target delay from the first step. The frame-by-frame ladder of `yoshi-rl-3-ladder` exists only because Faynt's weights start with no delay.
- The value network sees the present state, and the reward is shifted by the delay (both from slippi-ai; our current RL does neither).
- Opponents: itself, its past versions, and every outside bot we have.
- **Against overfitting:** some bots are held out of training and only used for evaluation. A win rate that rises against training opponents and not against those is overfitting.
- Humans are the real test. Slippi ranked and unranked ban bots, so that means direct-connect games.

## 4. Cost [estimate]

From the RL updates of the running job, the 10M model does roughly 25,000 frames a second forward and backward on the 3090 while sharing it. On that figure:

| Job | Frames | Time on the 3090 |
|---|---|---|
| Stage 0, one gate run | 1B | about half a day |
| Stage 1, one pass over everything, 10M model | 26B perspective-frames | about 12 days |
| Stage 1, 75M model | 26B | several times longer; rental territory |

These decide whether stage 1 runs here or on a rented GPU, so the benchmark in stage 0 comes before any spend. HAL trained its 247M model in 16 hours on one B200.

## 5. What the current run teaches

`yoshi-rl-3-ladder` (Faynt's Yoshi, delay raised from 3 to 10 during RL) continues as the baseline. So far:

- Delay can be learned by RL alone, but slowly: about 450 steps per extra frame from 7 on.
- A win-rate target for moving up can stall the run; 50% against Phillip at 6 frames was never reached, 30% was.
- At 10 frames the first wins against a Phillip agent came at step 1600.

The new 12-frame model has to beat this run's final checkpoint at the same delay.

## 6. Open points

1. Ask in the Slippi Discord for a seventh dump and lower ranks, and ask for aMSa's replays? These are messages only Mateo sends.
2. Add the tournament set (94k games) to stage 1?
3. Mirroring and bot games are untested ideas; each gets its own small comparison in stage 0 before going into stage 1.
