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
<!-- index:end -->
