# Experiment log: our own Yoshi bot

One file per experiment in this folder. Each records what we asked, what we ran, what happened and what we concluded; [status](../status.md) only says where things stand.

## How to use it

```sh
python scripts/experiments.py new SLUG "Title"   # creates the next EXX-SLUG.md with status planned
python scripts/experiments.py index              # rewrites the table below from the files' headers
python scripts/experiments.py check              # headers complete, index up to date
```

Each file starts with a header: `id`, `title`, `date`, `status` (planned, running, done, abandoned), a one-line `result` and `verdict` for the table, `runs` (directories in `data/train/runs/`), `prs`, and `follows` (the experiments it builds on). The body has five sections: Question, Setup, Judged by, Result, Verdict.

## Rules

1. **Create the file before launching**, with Question, Setup and Judged by filled in. Add the result and verdict when it ends, including when it fails or is abandoned.
2. **The judge is the Dolphin league** (`python -m meleebot.league`, CPU 9 = 0 Elo), not validation loss or simulator win rate. Both have misled us ([E11](E11-fox-20m-check.md), [E09](E09-rl-yoshi-1.md)).
3. **State the delay and the number of games** with every result. Under about 30 games a rating moves by 100 Elo or more.
4. **Name the artifacts.** Run directories are in `data/train/runs/` (not in git); each has `run.json` (settings) and `log.jsonl` (loss curve). League games are in `data/train/league/games.jsonl`. Scripts that produced a result go in the repo, not `/tmp`.
5. **One change per experiment** where possible. If a run changes several things, say so in the verdict.
6. **A planned experiment is a proposal.** The queue of what to do next is the entries with status planned.

## Index

Loss is validation loss, summed over the four controller heads. "vs CPU 9" is wins as Yoshi against the level 9 Fox. Elo is the league's.

<!-- index:start -->
| # | Date | Status | Experiment | Result | Verdict |
|---|---|---|---|---|---|
| [E01](E01-bc-6m-v1.md) | 11-14 | done | First clone of Yoshi players, 5.4M | loss 0.783; 0 of 12 vs CPU 9 | Too small |
| [E02](E02-bc-20m-v2.md) | 11-14 | done | 20.7M clone with rotary positions | loss 0.683; 1 of 12 vs CPU 9 | Bigger helps a little |
| [E03](E03-bc-20m-amsa.md) | 11-14 | done | Clone of aMSa only | loss 0.662; 6 of 36 vs CPU 9 | One pro is not enough data |
| [E04](E04-bc-20m-v3.md) | 11-14 | done | Clone of every Yoshi game in HAL's dataset | loss 0.644; 10 of 36 vs CPU 9; −241 Elo at delay 3 | More data helps |
| [E05](E05-optimiser-bench.md) | 11-15 | done | Optimiser and schedule comparison | Muon 0.710 vs AdamW 0.806 at 5k steps | Use Muon with warmup-stable-decay |
| [E06](E06-pre-20m-all.md) | 11-15 | done | Pretrain on every character | loss 0.632; −433 Elo at delay 3 as Yoshi | A base, not a player |
| [E07](E07-bc-20m-ft.md) | 11-15 | done | Fine-tune the pretrain on Yoshi at netplay delay | loss 0.622; 5 of 6 vs CPU 9; −66 Elo at delay 3 | Best of our own models |
| [E08](E08-stomped-clone.md) | 11-14 | done | stomped.dev with our clone | 8 of 36 finished matches won; 26 disconnects | Too weak at that delay; switched off |
| [E09](E09-rl-yoshi-1.md) | 11-15 | done | Self-play PPO in the simulator | 77% vs teacher, then collapse; −141 and −270 Elo at delay 3 | Simulator gains did not transfer to Dolphin |
| [E10](E10-rl-yoshi-2.md) | 11-16 | done | PPO with stability fixes | no divergence, but 77% → 31% vs teacher | Stability was not the problem |
| [E11](E11-fox-20m-check.md) | 11-16 | done | Does our pipeline reproduce HAL's 20M Fox? | loss 0.661; 2 of 24 vs CPU 9 (HAL: 95%) | No. Own pipeline stopped |
| [E12](E12-fox-diagnosis.md) | 11-16 | done | Why the E11 Fox loses | holds inputs: stick changes on 8.6% of frames, humans 22.9% | Behaviour, not plumbing or polling drift |
| [E13](E13-fox-20m-padfix.md) | 11-16 | abandoned | Fine-tune to break the input holding | crashed at step 1,000 with loss 1.692 | Dropped with the own pipeline |
| [E14](E14-hal-amsa-yoshi.md) | 11-16 | done | HAL's 247M model imitating aMSa | 403 Elo, no delay; HAL as a Master Yoshi 220 | Best Yoshi, with no training |
| [E15](E15-hal-steering.md) | 11-16 | done | Steering sweep: return target and temperature | return target 40: 561 Elo, 23 of 30 | +160 Elo for free; tops the league |
| [E16](E16-hal-delay.md) | 11-16 | done | Input delay 3, 6 and 10 on HAL-as-aMSa | 135, 87, 176 Elo against 403 with no delay | Delay costs 200–300 Elo, most of it by 3 frames |
| [E17](E17-stomped-hal.md) | 11-16 | running | stomped.dev with HAL-as-aMSa | first match won |  |
| [E18](E18-league-opponents.md) | 11-16 | done | Stronger league opponents | our best Yoshi wins 2 of 26 against Phillip's anti-Yoshi agents; Phillip's Yoshi rates 688 against our 402 | yardstick found, and Phillip's Yoshi is a stronger Yoshi than HAL as aMSa |
| [E19](E19-hal-train-loop.md) | 11-16 | done | A training loop for HAL's model on the 3090 | validation 1.0867 bits (HAL: 1.0870); trains at 7 GB and about 40 windows/s; fine-tuned checkpoint 22 of 30 against the released 23 of 30 | the loop is correct and usable on the 3090 |
| [E20](E20-hal-return-finetune.md) | 11-16 | planned | Return-conditioned self-improvement in the simulator |  |  |
| [E21](E21-hal-ppo.md) | 11-16 | planned | PPO on HAL with a KL penalty toward the clone |  |  |
| [E22](E22-hal-delay-offsets.md) | 11-17 | done | HAL under delay: rebalance the action offsets | at 10 frames of delay the fine-tune won 8 of 30, the released weights 10 of 30 | no effect; the offset weighting is not why HAL is weak under delay |
| [E23](E23-hal-dida-delay.md) | 11-17 | abandoned | Delay: imitate the no-delay model on our own delayed games | stopped after 167 of 288 games, before training; no result | superseded by the simulator game farm: the same loss, on games from the simulator and a small student |
| [E24](E24-sim-farm.md) | 11-17 | done | Simulator game farm: speed, and agreement with Dolphin | 1,700 to 1,900 game frames a second at 64 lanes; at delay 10 the simulator gave 20 wins in 192, Dolphin 7 in 60 | the farm replaces Dolphin for generating games and for quick checks; Dolphin stays the judge |
| [E26](E26-yoshi-technique.md) | 11-18 | done | Does HAL execute Yoshi's techniques like aMSa, and what does delay take away? | same aerials, double-jump cancels and L-cancels as aMSa; half his double-jump lands; parries against Fox drop from 0.17 to 0.02 a minute at delay 10 | delay takes Fox parries and some precision; the gap to aMSa in double-jump lands is there without delay too |
| [E27](E27-faynt-roster.md) | 11-18 | done | Faynt 10M across characters: Yoshi, and does Fox RL hurt the rest | Fox-mirror RL lifts every character: Arena beats Expert 32/32 in Fox, Yoshi, Marth and Falco mirrors; Arena as Yoshi beats HAL as aMSa 6/6 but loses 0/6 to Phillip's anti-Yoshi Fox and Yoshi ditto | base our Yoshi on Faynt 10M Arena; Yoshi RL should target Phillip's anti-Yoshi Fox and Yoshi ditto |
| [E28](E28-faynt-farm.md) | 11-18 | done | Faynt in the simulator farm: exactness, agreement with Dolphin, speed | Faynt plays in the farm with inputs identical to Dolphin's (85,260 seat-frames), mirror results match E27, and 8 processes run 6,337 frames a second, about 60 times the Dolphin league | use the farm for Faynt-vs-Faynt evaluation and as the rollout engine for Yoshi RL; opponents other than Faynt still need Dolphin |
| [E29](E29-farm-phillip-hal.md) | 11-18 | done | Phillip and HAL in the farm | Phillip and HAL play in the farm with live-path inputs; 9 of 11 pairings matched Dolphin, and the two Phillip pairings that did not were a Dolphin bug (analog triggers off, E30): with it fixed, Dolphin matches the farm | use the farm for Faynt, Phillip and HAL; it reproduces the game better than our Dolphin did before E30 |
| [E30](E30-exi-triggers.md) | 11-19 | done | Analog triggers were off in headless Dolphin | the ExiAI build read every analog trigger below full as 0 and a full press as 25 of 140; with the fix, HAL beats Phillip gm 3/24 (was 21/71) and Faynt's Yoshi beats the anti-Yoshi Marth 2/24 (was 9/23), matching the simulator farm | every earlier fast and realtime Dolphin result ran without analog shields or airdodges; the simulator was right; fixed in the runner for the headless build |
| [E31](E31-sim-faithful.md) | 11-19 | done | The simulator reproduces Dolphin games frame for frame | given each replay's recorded inputs and random seeds, the simulator reproduces 406 of 411 of our Dolphin bot games and 36 of 40 random human ranked Yoshi games frame for frame to the end; the optimised build plays bit-identical frames | the farm's physics are Dolphin's; what differs is only the random number stream, which changes which games happen, not how likely each outcome is |
| [E32](E32-yoshi-rl.md) | 11-19 | done | Faynt-style RL for a Yoshi | from Faynt 10M Arena, 1,000 PPO steps in the farm took the Yoshi from losing to winning every Phillip anti-Yoshi agent; in Dolphin step 400 won 72 of 78 against ten opponents and step 1000 won 85 of 88, 8 of 8 against step 400. With any input delay it collapses (0 of 48 against the anti-Yoshi Fox from 1 frame); fed its own pads it keeps 42 of 48 at 1 frame but none from 4 | the strongest Yoshi we have, at no delay. It cannot play on stomped.dev (10 frames of delay from this server) until it is trained with the delay: next, the same RL at delay 10 |
| [E33](E33-delay-rl.md) | 11-21 | done | RL under input delay from a no-delay model | PPO in the farm with the delay raised during training took the no-delay Yoshi to 8 frames in 1,800 steps: 5 level changes, about 450 steps a frame from 7 on. At the 10 frames stomped needs it won 3 of 48 against Phillip's Yoshi and 4 of 48 against Faynt Arena Yoshi at step 1600, and 0 against Phillip's Fox and Marth | delay can be learned by RL from a no-delay model, but too slowly to be the route; stopped at step 1799 for a model trained with the delay from the start (E34). The run resumes from its checkpoint if needed |
| [E34](E34-own-gate.md) | 11-24 | running | Our own model: the gate | running | pending |
| [E35](E35-own-pretrain.md) | 11-25 | running | Our own model: all-character pretrain | running | pending |
<!-- index:end -->
