# Bot-writer track

A coding agent (Claude Code, Codex, or a plain tool loop over an OpenAI-compatible API) gets a sandbox with a bot template, libmelee docs, frame data and practice tools. It iterates on a single-file bot for a fixed wall-clock budget; the final bot is ranked on a ladder against a fixed roster. The track adapts [StarSkirmish](https://starskirmish.com/bench/v0-1/) (LLMs write Brood War bots in one hour) and LLM Skirmish (Screeps) to Melee and libmelee.

Code lives in `melee_llm/botwriter/`:

| file | role |
| --- | --- |
| `host.py` | Child process: loads and steps `bot.py`, returns its controller state as JSON. Holds the audit-hook guard and `FakeController`. |
| `agent.py` | `BotAgent(Agent)`, the parent side: budget, sanitized state, violation counts. |
| `specs.py` | Player specs: `cpu:N`, `idle`, `baseline:NAME`, `bot:PATH`, `agent:MODULE:CLASS[:ARG]` (learned bots). |
| `practice.py` | `play` (real games, needs the ISO) and `check` (offline: recorded replays through the bot). |
| `summary.py` | Per-game replay summary: stocks, damage, hits, deaths with cause, % time offstage, action histogram. |
| `dolphin.py` | Claims a distinct Slippi port per process so Dolphins run in parallel. Finds the ISO. |
| `ladder.py` | Evaluation: jobs, parallel workers, `games.jsonl`, `leaderboard.json`, Bradley-Terry. |
| `session.py`, `toolloop.py` | Sandbox, coding-agent run with a budget, collection of bot, transcript and cost. |
| `batch.py`, `round1.json` | Runs a plan of sessions N at a time with per-slot port ranges and retries; the paused round-1 plan. |
| `template/` | What the agent sees: `README.md` (task, rules, scoring, tools), `bot.py` starter, `docs/`. |
| `baselines/` | Scripted Fox bots (`rusher`, `laser`, `shine`), copied into the sandbox as `opponents/`. |

## Usage

```sh
export MELEE_ISO=~/melee.iso                       # NTSC 1.02; nothing here needs it except real games

# a sandbox by hand (tools/ are wrappers around this repo's venv)
uv run python -m melee_llm.botwriter.session sandbox --dest /tmp/sb --minutes 60
cd /tmp/sb && tools/check-bot && tools/practice --opponent cpu:7 --games 4

# a coding-agent session (output: ~/.local/share/melee-llm/botwriter/sessions/<id>/)
uv run python -m melee_llm.botwriter.session run --harness claude --model opus --minutes 60 \
    --budget-usd 25 --effort high --name opus/run1
uv run python -m melee_llm.botwriter.session run --harness openai --model gpt-6-astra --minutes 60 --name astra/run1
uv run python -m melee_llm.botwriter.session run --harness codex --model gpt-6.1-sol --minutes 60 --name sol-codex/run1
# (codex-cli 0.166 on the ChatGPT login refuses gpt-6-astra; use the openai harness for it)

# a batch of sessions, 3 at a time, each with its own 4-port Slippi range; resumable via the log
uv run python -m melee_llm.botwriter.batch --plan melee_llm/botwriter/round1.json --log runs.jsonl

# ladder: add entrants (sessions/<id>/final/bot.py) to a copy of ladder.example.json
uv run python -m melee_llm.botwriter.ladder run --config ladder.json      # resumable
uv run python -m melee_llm.botwriter.ladder board --config ladder.json    # recompute leaderboard.json
```

## Bot API

One file defines `class Bot` with a `character` attribute and `step(gamestate, controller, port, opp_port)`. An optional `on_game_end(gamestate)` resets per-game state. `BotAgent` wraps the file as an `Agent`:

- **Process isolation.** The bot runs in `python -I -B` with a scrubbed environment (no API keys, `HOME` set to a scratch dir), a 4 GiB address-space limit and its own session, so a crash cannot take down the match.
- **Protocol.** The parent pickles each GameState to the child (about 0.05 ms per frame; reductions in `host.py` skip numpy's and copyreg's slow paths but rebuild the same types). It sends to both bots before reading either answer, so they think at the same time. The child answers with its full controller state as JSON; the parent never unpickles bot output. Only changed inputs reach the Dolphin pipe, with libmelee's analog fixing kept exact. START is dropped.
- **Budget.** 16 ms of wall time per frame by default, measured in the parent, in every mode. Startup gets 20 s.

  | Event | Effect |
  | --- | --- |
  | Late answer | Counted as `late`. The controller keeps its old inputs and the stale answer is dropped. |
  | Frame arrives while the bot is busy | Counted as `skipped`, not queued. |
  | Exception in `step` | Caught and counted. That frame is lost. |
  | Process dies | `crashed`: all buttons are released for the rest of the match. |

- **What the bot sees.** A shallow copy of the GameState with the opponent's (and Nana's) `controller_state` neutral and `cpu_level`, `displayName`, `connectCode` and `nickName` blank.
- **Stats.** Every practice report and ladder game record has per-game frames, answered, late, skipped, exceptions, policy violations, crashed and mean/p99/max ms.

## Practice tools (sandbox)

- `tools/practice` plays in `fast` mode (ExiAI Dolphin, headless, unthrottled), alternating spawn sides. Each game prints a compact block plus a final JSON line; the full report, replays and `bot.log` go to `runs/<ts>/`. Opponents: `cpu:N`, `idle`, `baseline:*`, `bot:PATH` and `self`. `agent:` specs (learned bots) are refused, so the hidden tier stays hidden.
- `tools/check-bot` needs no ISO. It replays the sample `.slp` files through the bot (at real-time pace whenever the bot falls behind) and reports crashes, exceptions, policy violations and frame times.
- `tools/inspect-replay` and `tools/time-left`.

## Ladder and scoring

- **Format v0:** Fox ditto on Final Destination and Battlefield, both spawn sides, `games_per_side` games per (entrant, opponent, stage, side): 2 × 2 × 2 = 8 games per pairing by default. Each job is one `play()` call in its own Dolphin. Workers are `spawn` processes, each holding a Slippi port lock under `/tmp/melee-llm-slippi-ports`. `SIGALRM` kills a job that hangs past `job_timeout_s`.
- **Default roster:** CPU 1-9 plus `baseline:laser`, `baseline:rusher` and `baseline:shine`. Learned bots go in as `agent:melee_llm.bots.<module>:<Class>` once they exist.
- **Primary score:** `roster_score`, the mean over roster opponents of the entrant's win rate (a draw counts ½), with a Wilson 95 % interval. Opponents weigh the same whatever the game counts. Like StarSkirmish v0.2, which dropped Elo for plain win rates against a fixed roster, the score ignores the other entrants: a new bot is scored without replaying the field, and the bar stays comparable across model generations.
- **Secondary:** the project's one Bradley-Terry fit (`melee_llm/ratings.py`: MAP with a Gaussian prior, so undefeated bots stay finite) over all games, on an Elo scale anchored at `cpu:1` = 0. `entrants_play_each_other` and `calibrate_roster` add entrant-vs-entrant and roster-vs-roster games. `cpu_ladder_level` is the highest CPU level beaten at least half the time, with every lower roster CPU beaten too.
- **Per model:** entrants are named `<model>/<run>`. `models` reports the mean and SD of `roster_score` over runs, mean Elo and the best run. Report the mean, not the best: StarSkirmish saw an 18-point spread between runs of one model.
- **Integrity:** each entrant gets totals of late/skipped frames, exceptions, crashes, policy violations and forfeits. Any policy violation or forfeit sets `flagged`. A bot that fails to load or picks a disallowed character forfeits its games. A broken roster opponent is an `error` (excluded from scoring, retried on the next run), not a free win.

## Decisions taken (change freely)

- **Budget per session:** 60 min of wall time by default (`--minutes`), following StarSkirmish. Claude Code also gets `--max-budget-usd`, the tool loop `--max-tokens`. There is no submit tool: `bot.py` is collected at the deadline, with a tarball of the whole sandbox (practice logs, saved versions) for analysis. Claude Code is resumed (`--resume <session-id>`) with "N minutes are left, keep improving" when it ends its turn early, up to 30 times. The tool loop does the same.
- **Harness setup:** Claude Code runs with `--safe-mode` (no user CLAUDE.md, skills, hooks or MCP), `--strict-mcp-config`, WebFetch and WebSearch disallowed, and `bypassPermissions` inside the sandbox. Codex runs with `--ignore-user-config --ephemeral`. API keys are scrubbed from the agent's environment.
- **Allowed in bots:** one file, using the standard library, `melee` and `numpy`. Reads only from the interpreter, the `melee_llm` package and the scratch dir. Writes only to scratch.
- **Anti-cheat (bot runtime):** the `Guard` audit hook in `host.py` blocks sockets, subprocesses and exec, fork, ctypes `dlopen`, `kill`, reads under `/home`, `/tmp`, `/root`, `/mnt` and `/proc/<other>`, and writes outside scratch. Each attempt raises inside the bot and is counted. With the sanitized GameState, a bot sees what a player sees on screen. **This is a tripwire, not a security boundary**: CPython audit hooks can be bypassed (for example `_posixsubprocess.fork_exec`, or C extensions already loaded). Leaderboard-grade runs need the bot host inside `docker run --network none --read-only` with only the bot file mounted, which the stdin/stdout protocol already supports. `docker` works on this host; bubblewrap and unprivileged user namespaces do not (AppArmor blocks them).
- **Anti-cheat (coding agent):** isolation is soft. The sandbox is a random directory under `$BOTWRITER_HOME/sandboxes/`, separate from the session records, but the agent runs as `mateo` and could `cat` this repo, other sessions or the hidden roster. Mitigations so far: the README rule, and transcripts to audit (grep for paths outside the sandbox).
- **Practice vs evaluation conditions:** same `BotAgent`, budget and sanitization. Only the opponents and the number of games differ.

## Testing status

Verified offline (before the ISO was available):

- The starter bot and all three baselines run over 4.9k recorded frames with 0 exceptions, p99 below 1 ms and inputs on every frame.
- Adversarial bots:

  | Bot | Outcome |
  | --- | --- |
  | Sleeps 50 ms every 100 frames | `late` and `skipped` counts; keeps playing |
  | `os._exit` mid-game | Reported as `crashed` |
  | Raises every frame | Exceptions counted and logged; its prints stay out of the protocol |
  | Hangs at import | Fails to load after the 20 s startup limit |
  | No `Bot` class | Fails to load with a traceback |
  | Cheats | Blocked on 7 of 7 attempts: reading `~/.hermes/.env`, connecting to a socket, running a subprocess, `os.system`, reading `/proc/<parent>/environ`, reading the repo README, writing to `/tmp`. It sees the opponent's controller as neutral |

- The command stream written to the pipe uses libmelee's exact command format.
- The replay summary, checked on the sample replays: on itemExport it reports a kill at 84.9 % through the bottom blast zone.
- Bradley-Terry recovers simulated 75 % / 75 % strengths (≈ +190 Elo per step). The leaderboard was built from synthetic games, and the ladder ran end to end through the process pool, port locks and JSONL with forfeiting entrants (no Dolphin needed).
- Claude Code smoke session (Haiku, 3 min, $0.003): the sandbox was built, the agent read the README and ran `tools/check-bot` and `tools/time-left`, and the final bot was collected and validated. Haiku stopped after 10 s, hence the continuation nudges. They work: in round 1 Opus was resumed 7 times and Sonnet 31 times.
- OpenAI-compatible tool loop, 5 turns of Haiku through CLIProxy: bash, read and edit all worked.

Verified with the ISO (pilot and round 1, below):

- Practice and ladder games end to end, up to 10 ladder Dolphins plus 12 practice Dolphins in parallel on distinct ports.
- The baselines in real games.
- Real sessions under the `claude` and `openai` harnesses: 3-minute smokes with Haiku and gpt-6-astra, then the 30-minute round-1 runs.

Still unverified: the Codex harness. codex-cli 0.166 on the ChatGPT login refuses `gpt-6-astra` ("not supported when using Codex with a ChatGPT account"), so astra needs the `openai` tool loop. `gpt-6.1-sol` should work there, but no session has been run.

## Round 1 results (2026-11-14)

**Paused after one run per Claude model.** The plan was 3 × 30-minute runs each of Opus 5.5, Sonnet 5.5 and Haiku 4.5 (Claude Code) and gpt-6-astra and gpt-6.1-sol (tool loop over CLIProxy). Mateo paused it after the first wave to save Claude subscription usage. To resume the 12 remaining runs (in `melee_llm/botwriter/round1.json`), 3 at a time on ports 51560-51571:

```sh
systemd-run --user --unit melee-ladder-r1-sessions --working-directory="$PWD" \
  --setenv=PATH="$HOME/.local/bin:/usr/bin:/bin" --setenv=DISPLAY=:98 --setenv=MELEE_ISO=$HOME/melee.iso \
  .venv/bin/python -m melee_llm.botwriter.batch --plan melee_llm/botwriter/round1.json \
  --log ~/.local/share/melee-llm/botwriter/rounds/r1/runs.jsonl
```

Then add each `sessions/<id>/final/bot.py` to `~/.local/share/melee-llm/botwriter/ladders/v1.json` and re-run `ladder run` on it; it only plays the new games.

**Ladder v1:** format v0 with two tiers.

| Tier | Opponents | Games per (opponent, stage, side) | Games per bot |
| --- | --- | --- | --- |
| Main roster | CPU 1-9 plus the 3 scripted baselines | 3 | 144 |
| Hard tier | HAL, Phillip, MIMIC and Faynt | 1 | 16 |

- 640 games: 112 reused from the pilot ladder, the rest played in about 2 h on 10 Dolphins.
- 9 hard-tier jobs first died of CUDA OOM, because other processes held 17 GB of the GPU. They were re-run with 3 workers.
- Across all bots, 188 of about 7.6 M frames were late and 15 were skipped. No bot had exceptions, crashes or policy violations.
- Draws are 8-minute timeouts, mostly against `laser` and `shine`.

| model | harness | runs | main score (95 % CI) | hard tier | CPU level | Elo | cost | wall | LoC | practice games | SmashBot overlap |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Sonnet 5.5 (run1) | Claude Code | 1 | **83.0** (76.0-88.2) | 0 / 16 | 9 | 461 | $0.45 | 28.5 min | 135 | 38 | 0.084 |
| Haiku 4.5 (run1) | Claude Code | 1 | **83.0** (76.0-88.2) | 6.2 (1 win vs MIMIC) | 7 | 469 | $0.44 | 30.0 min | 108 | 18 | 0.071 |
| Opus 5.5 (run1) | Claude Code | 1 | 76.4 (68.8-82.6) | 0 / 16 | 8 | 384 | $1.82 | 29.1 min | 303 | 32 | 0.035 |
| Sonnet 5.5 (pilot1) | Claude Code | 1 | 17.7 (12.3-24.8) | 0 / 16 | 0 | -170 | $0.32 | 29.5 min | 148 | n/a | 0.115 |
| gpt-6-astra, gpt-6.1-sol | tool loop | 0 | paused | | | | | | | | |

Notes on the table:

- With one run each, Sonnet, Haiku and Opus are not separable: the CIs overlap, and the two Sonnet runs differ by 65 points (per model, Sonnet is 50.4 ± 32.6 over 2 runs).
- Cost is Claude Code's API-equivalent `total_cost_usd`; usage was billed to the subscription. Earlier records summed this cumulative value over `--resume` calls, inflating Sonnet run1 to $10.96 and Opus to $13.22. Fixed in `session.py`; the old values are kept as `cost_usd_summed_bug` in those `meta.json` files.
- Overlap is `similarity.py`'s renamed 12-token-shingle overlap. The baselines and the starter template score 0.08-0.11, and the flag threshold is 0.25. No bot is flagged.
- Reference Elo (CPU 1 = 0): CPU 9 441, `rusher` 423, `laser` 258, `shine` 236, MIMIC 763, HAL, Phillip and Faynt 894. Hard-tier Elos rest on very few non-wins. The Elo column and these values were recomputed on 2026-11-14 with the shared fit. The ladder's own fit gave 470, 479, 391 and -171 for the four bots, in the same order.

**What each model built**

- **Sonnet run1** (`shiner`, 135 lines): compact, reactive and stateless. In range on the ground it shines and jump-cancels with a tapped jump (frame 3 or later). It grabs a shielding opponent, forward-smashes above 110 %, fires periodic lasers at range and spams nair in the air. It recovers with a double jump, then a firefox aimed at a point above the ledge. Practice: 13/18 against CPU 9, 0/6 against the baselines. After about 21 minutes it declared the bot final and answered the next ~25 "keep improving" nudges with one-line replies.
- **Sonnet pilot1**: the same skeleton (`shiner`, the same helpers), but it holds B instead of tapping it, so its shine rarely comes out. Its recovery self-destructs off the bottom about twice a game, and it loses even to CPU 1. A few lines of input timing and recovery explain most of the gap between the Sonnet runs.
- **Haiku run1** (108 lines): the simplest bot. At close range it calls libmelee's built-in `melee.techskill.multishine`, a little further out it up-smashes, at mid range it dashes in and jabs, and otherwise it walks toward the opponent without passing the ledge. Its firefox recovery aims at the ledge. Best against the scripted baselines (0.75 against each), and the only hard-tier win. One invocation; it never stopped early.
- **Opus run1** (303 lines): the most engineered bot, yet the weakest of the three against `rusher` (0.25) and CPU 8-9 (0.5 and 0.33). More machinery did not pay off in 30 minutes.
  - A macro queue (frame-by-frame input sequences).
  - Reactive defence from `FrameData.in_range`: shield, or shine if the hit is ≥ 2 frames away.
  - Punishes cooldown frames read from `attack_state`, then chains grab into up-throw or down-throw by percent, shine into jump-cancel into up-air, and dash grab or short-hop nair.
  - Mixes ledge getup, ledge jump and roll at random, DIs in, fast-falls and lasers an offstage opponent.
  - It wrote its own frame-by-frame replay dumper in `/tmp/dbg` with the repo's venv Python, which it found in `tools/`. Legitimate, but outside the sandbox.
- **Common pattern:** all bots except the pilot beat CPU 1-6 almost every time, and all lose every game to HAL, Phillip and Faynt. `rusher` is the hardest scripted baseline. The main score saturates near 83, because 9/12 of the roster is CPUs.

**Harness observations**

- **Tool loop:** 3 idle replies in a row end the loop whatever time is left, so a 30-minute GPT run could quit early (not tested with sessions yet). The 3-minute astra smoke ended with `model_stopped` for a benign reason: the model went idle in the last 6 s, after a "0 minutes left" nudge.
- **Reasoning:** CLIProxy reported 0-8 reasoning tokens whether or not `reasoning_effort` was set, so the GPT runs may be running with little reasoning.
- **Sandboxing:** agents write to `/tmp` (Opus as above, astra `/tmp/rusher.txt`), and Opus used the repo's venv directly. No transcript shows reads of repo source, other sessions or the ladder.

## Needed changes outside botwriter/ (not made: other owners)

1. `runner.play()` should accept `slippi_port` (or `**console_kwargs`). `dolphin.claim_slippi_port` currently rebinds `melee.Console` with `functools.partial` inside each worker process: a hack, safe only because each worker is a single process.
2. `play()` should return each game's replay path in `GameResult`. Pairing replays by sorted filename assumes one `.slp` per finished game.
3. Live (`watch`) matches with two `BotAgent`s step them one after the other, so the worst case is 2 × 16 ms per frame. A split `begin_step` / `end_step` in the Agent contract would let the runner send both frames before waiting. Fast mode is unaffected, because the game blocks on input.
4. `play()` needs a game-level timeout or stall detector. The ladder covers this with `SIGALRM` for now.

## Open questions for Mateo

- **Isolation level.** Is soft isolation enough for v0, or should agents and bots run in Docker from the start? A containerized coding agent also needs its CLI auth mounted.
- **Wall time and runs.** 60 min × 5 runs per model, as in StarSkirmish? Is 30 min enough for cheaper sweeps? Practice throughput also limits the budget: fast-mode game length is unmeasured here (my unverified guess is 1-2 min of wall time). Should practice run several games in parallel? `practice` already claims its own port, so concurrent calls work.
- **Roster for v0 scoring.** Which CPU levels? All 9 means CPUs make up 9/12 of the score. Should the learned bots (HAL, Faynt, MIMIC) count in `roster_score` or stay a separate "hard tier" column? Should SmashBot itself be wrapped as an `agent:`?
- **Characters and stages.** Fox only on FD and BF for now. When do other characters open up, and should the bot choose its own?
- **Contamination.** SmashBot, libmelee examples and Phillip/slippi-ai are public and in training data. Allow porting SmashBot logic, or forbid it and check for near-copies?
- **Budget fairness.** Should the 16 ms be wall time on a shared 32-core machine, or CPU time? Pin bot processes to cores during ladder runs?
- **Leaking roster identity.** Bots cannot read `cpu_level`, but they can infer CPUs from behaviour. That is fine as skill, but should CPUs stay in the hidden evaluation tier?
