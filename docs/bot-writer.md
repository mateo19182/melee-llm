# Bot-writer track

A coding agent (Claude Code, Codex, or a plain tool loop over an OpenAI-compatible API) gets a sandbox with a bot template, libmelee docs, frame data and practice tools. It iterates on a single-file bot for a fixed wall-clock budget; the final bot is ranked on a ladder against a fixed roster. The track adapts [StarSkirmish](https://starskirmish.com/bench/v0-1/) (LLMs write Brood War bots in one hour) and LLM Skirmish (Screeps) to Melee and libmelee.

Code lives in `melee_llm/botwriter/`:

| file | role |
| --- | --- |
| `host.py` | Child process: loads and steps `bot.py`, returns its controller state as JSON. Holds the audit-hook guard. |
| `agent.py` | `BotAgent(Agent)`, the parent side: per-frame budget, sanitized game state, violation counts. |
| `specs.py` | Player specs: `cpu:N`, `idle`, `baseline:NAME`, `bot:PATH`, `agent:MODULE:CLASS[:ARG]` (learned bots). |
| `practice.py` | `play` (real games, needs the ISO) and `check` (offline: recorded replays through the bot). |
| `summary.py` | Per-game replay summary: stocks, damage, hits, deaths with cause, % time offstage, action histogram. |
| `dolphin.py` | Claims a distinct Slippi port per process so Dolphins run in parallel. Finds the ISO. |
| `ladder.py`, `ladder.example.json` | Evaluation: jobs, parallel workers, `games.jsonl`, `leaderboard.json`, ratings. |
| `session.py`, `toolloop.py` | Build a sandbox, run a coding agent with a budget, collect the bot, transcript and cost. |
| `batch.py`, `round1.json` | Run a plan of sessions N at a time with per-slot port ranges and retries; the paused round-1 plan. |
| `similarity.py` | Near-copy check of a bot against public SmashBot. |
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

Other `session run` flags: `--slippi-ports` (the session's practice port range, default `51590-51593`), `--base-url` (the `openai` harness endpoint, default `http://127.0.0.1:8317/v1`) and `--max-tokens` (its total token budget, default 5,000,000). `ladder run --dry-run` lists the jobs without playing.

## Bot API

One file defines `class Bot` with a `character` attribute and `step(gamestate, controller, port, opp_port)`. An optional `on_game_end(gamestate)` resets per-game state. `BotAgent` wraps the file as an `Agent`:

- **Process isolation.** The bot runs in `python -I -B` with a scrubbed environment (no API keys, `HOME` set to a scratch dir), a 4 GiB address-space limit and its own session, so a crash cannot take down the match.
- **Protocol.** The parent pickles each GameState to the child (about 0.05 ms per frame) and sends to both bots before reading either answer, so they think at the same time. The child answers with its full controller state as JSON; the parent never unpickles bot output. START is dropped.
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

- `tools/practice` plays in `fast` mode (headless, unthrottled), alternating spawn sides. Each game prints a compact block plus a final JSON line; the full report, replays and `bot.log` go to `runs/<ts>/`. Opponents: `cpu:N`, `idle`, `baseline:*`, `bot:PATH` and `self`. `agent:` specs (learned bots) are refused, so the hidden tier stays hidden. `--sim` plays in the simulator instead of Dolphin ([simulator.md](simulator.md)).
- `tools/check-bot` needs no ISO. It replays the sample `.slp` files through the bot and reports crashes, exceptions, policy violations and frame times.
- `tools/inspect-replay` and `tools/time-left`.

## Ladder and scoring

- **Format v0:** Fox ditto on Final Destination and Battlefield, both spawn sides, `games_per_side` games per (entrant, opponent, stage, side): 2 × 2 × 2 = 8 games per pairing by default. Each job is one `play()` call in its own Dolphin. `SIGALRM` kills a job that hangs past `job_timeout_s` (default 1800).
- **Default roster:** CPU 1-9 plus `baseline:laser`, `baseline:rusher` and `baseline:shine`. Learned bots go in as `agent:melee_llm.bots.<module>:<Class>`, in a separate hard tier (`hard_tier`, `hard_games_per_side`).
- **Primary score:** `roster_score`, the mean over roster opponents of the entrant's win rate (a draw counts ½), with a Wilson 95 % interval. Opponents weigh the same whatever the game counts. Like StarSkirmish v0.2, which dropped Elo for plain win rates against a fixed roster, the score ignores the other entrants: a new bot is scored without replaying the field, and the bar stays comparable across model generations.
- **Secondary:** Elo from the project's shared Bradley-Terry fit (`melee_llm/ratings.py`, see [architecture.md](architecture.md#tracks)) over all games, anchored at `cpu:1` = 0. `entrants_play_each_other` and `calibrate_roster` add entrant-vs-entrant and roster-vs-roster games. `cpu_ladder_level` is the highest CPU level beaten at least half the time, with every lower roster CPU beaten too.
- **Per model:** entrants are named `<model>/<run>`. `models` reports the mean and SD of `roster_score` over runs, mean Elo and the best run. Report the mean, not the best: StarSkirmish saw an 18-point spread between runs of one model.
- **Integrity:** each entrant gets totals of late/skipped frames, exceptions, crashes, policy violations and forfeits. Any policy violation or forfeit sets `flagged`. A bot that fails to load or picks a disallowed character forfeits its games. A broken roster opponent is an `error` (excluded from scoring, retried on the next run), not a free win.

## Decisions taken (change freely)

- **Budget per session:** 60 min of wall time by default (`--minutes`), following StarSkirmish. Claude Code also gets `--max-budget-usd`, the tool loop `--max-tokens`. There is no submit tool: `bot.py` is collected at the deadline, with a tarball of the whole sandbox for analysis. Claude Code is resumed (`--resume <session-id>`) with "N minutes are left, keep improving" when it ends its turn early, up to 30 times. The tool loop nudges the same way.
- **Harness setup:** Claude Code runs with `--safe-mode` (no user CLAUDE.md, skills, hooks or MCP), `--strict-mcp-config`, WebFetch and WebSearch disallowed, and `bypassPermissions` inside the sandbox. Codex runs with `--ignore-user-config --ephemeral`. API keys are scrubbed from the agent's environment.
- **Allowed in bots:** one file, using the standard library, `melee` and `numpy`. Reads only from the interpreter, the `melee_llm` package and the scratch dir. Writes only to scratch. The sandbox README forbids porting or copying SmashBot and other public bots; `similarity.py` checks entries for near-copies of SmashBot.
- **Anti-cheat (bot runtime):** the `Guard` audit hook in `host.py` blocks sockets, subprocesses and exec, fork, ctypes `dlopen`, `kill`, writes outside scratch, and reads under `/home`, `/root`, `/tmp`, `/var/tmp`, `/dev/shm`, `/mnt`, `/media`, `/srv`, `/run`, `/opt` and `/proc/<other>`. Each attempt raises inside the bot and is counted. With the sanitized GameState, a bot sees what a player sees on screen. **This is a tripwire, not a security boundary**: CPython audit hooks can be bypassed (for example `_posixsubprocess.fork_exec`, or C extensions already loaded). Leaderboard-grade runs need the bot host inside `docker run --network none --read-only` with only the bot file mounted, which the stdin/stdout protocol already supports. `docker` works on this host; bubblewrap and unprivileged user namespaces do not (AppArmor blocks them).
- **Anti-cheat (coding agent):** isolation is soft. The sandbox is a random directory under `$BOTWRITER_HOME/sandboxes/`, separate from the session records, but the agent runs as `mateo` and could `cat` this repo, other sessions or the hidden roster. Mitigations so far: the README rule, and transcripts to audit (grep for paths outside the sandbox).
- **Practice vs evaluation conditions:** same `BotAgent`, budget and sanitization. Only the opponents and the number of games differ.

## Testing status

- **Offline tests:** `tests/test_botwriter_wire.py` covers what a bot receives (the sanitized GameState) and the begin/step split.
- **With the ISO** (pilot and round 1, below): practice and ladder games end to end, up to 10 ladder Dolphins plus 12 practice Dolphins in parallel on distinct ports, and real sessions under the `claude` and `openai` harnesses.
- **Unverified:** the Codex harness. codex-cli 0.166 on the ChatGPT login refuses `gpt-6-astra` ("not supported when using Codex with a ChatGPT account"), so astra needs the `openai` tool loop. `gpt-6.1-sol` should work there, but no session has been run.

## Round 1 results (2026-11-14)

**Paused after one run per Claude model.** The plan was 3 × 30-minute runs each of Opus 5.5, Sonnet 5.5 and Haiku 4.5 (Claude Code) and gpt-6-astra and gpt-6.1-sol (tool loop over CLIProxy). Mateo paused it after the first wave to save Claude subscription usage. To resume the 12 remaining runs (in `melee_llm/botwriter/round1.json`), 3 at a time on ports 51560-51571:

```sh
systemd-run --user --unit melee-ladder-r1-sessions --working-directory="$PWD" \
  --setenv=PATH="$HOME/.local/bin:/usr/bin:/bin" --setenv=DISPLAY=:98 --setenv=MELEE_ISO=$HOME/melee.iso \
  .venv/bin/python -m melee_llm.botwriter.batch --plan melee_llm/botwriter/round1.json \
  --log ~/.local/share/melee-llm/botwriter/rounds/r1/runs.jsonl
```

Then add each `sessions/<id>/final/bot.py` to `~/.local/share/melee-llm/botwriter/ladders/v1.json` and re-run `ladder run` on it; it only plays the new games.

**Ladder v1:** format v0 with two tiers, 640 games in total.

| Tier | Opponents | Games per (opponent, stage, side) | Games per bot |
| --- | --- | --- | --- |
| Main roster | CPU 1-9 plus the 3 scripted baselines | 3 | 144 |
| Hard tier | HAL, Phillip, MIMIC and Faynt | 1 | 16 |

Across all bots, 188 of about 7.6 M frames were late and 15 were skipped. No bot had exceptions, crashes or policy violations. Draws are 8-minute timeouts, mostly against `laser` and `shine`. The new games took about 2 h on 10 Dolphins. 9 hard-tier jobs died of CUDA OOM while other processes held 17 GB of the GPU, and passed when re-run with 3 workers.

| model | harness | runs | main score (95 % CI) | hard tier | CPU level | Elo | cost | wall | LoC | practice games | SmashBot overlap |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Sonnet 5.5 (run1) | Claude Code | 1 | **83.0** (76.0-88.2) | 0 / 16 | 9 | 461 | $0.45 | 28.5 min | 135 | 38 | 0.084 |
| Haiku 4.5 (run1) | Claude Code | 1 | **83.0** (76.0-88.2) | 6.2 (1 win vs MIMIC) | 7 | 469 | $0.44 | 30.0 min | 108 | 18 | 0.071 |
| Opus 5.5 (run1) | Claude Code | 1 | 76.4 (68.8-82.6) | 0 / 16 | 8 | 384 | $1.82 | 29.1 min | 303 | 32 | 0.035 |
| Sonnet 5.5 (pilot1) | Claude Code | 1 | 17.7 (12.3-24.8) | 0 / 16 | 0 | -170 | $0.32 | 29.5 min | 148 | n/a | 0.115 |
| gpt-6-astra, gpt-6.1-sol | tool loop | 0 | paused | | | | | | | | |

Notes on the table:

- With one run each, Sonnet, Haiku and Opus are not separable: the CIs overlap, and the two Sonnet runs differ by 65 points (per model, Sonnet is 50.4 ± 32.6 over 2 runs).
- Cost is Claude Code's API-equivalent `total_cost_usd`; usage was billed to the subscription. `cost_usd_summed_bug` in the Sonnet run1 and Opus `meta.json` files is an older, inflated value ($10.96 and $13.22) from a since-fixed bug.
- Overlap is `similarity.py`'s renamed 12-token-shingle overlap. The baselines and the starter template score 0.08-0.11, and the flag threshold is 0.25. No bot is flagged.
- Reference Elo (CPU 1 = 0): CPU 9 441, `rusher` 423, `laser` 258, `shine` 236, MIMIC 763, HAL, Phillip and Faynt 894. Hard-tier Elos rest on very few non-wins.

**What each model built** (the bots are in `sessions/<id>/final/bot.py`)

- **Sonnet run1:** a compact, stateless bot built on shine with a tapped jump-cancel, plus grab, forward smash, lasers and a firefox recovery. Practice: 13/18 against CPU 9, 0/6 against the baselines. After about 21 minutes it declared the bot final and answered the next ~25 nudges with one-line replies.
- **Sonnet pilot1:** the same skeleton, but it holds B instead of tapping it, so its shine rarely comes out, and its recovery self-destructs about twice a game. It loses even to CPU 1. A few lines of input timing and recovery explain most of the gap between the Sonnet runs.
- **Haiku run1:** the simplest bot. It calls libmelee's built-in `melee.techskill.multishine` at close range, with an up-smash, a dash-in jab and a firefox recovery around it. Best against the scripted baselines (0.75 against each), and the only hard-tier win.
- **Opus run1:** the most engineered bot (macro queue, reactive defence from `FrameData.in_range`, punishes, throw and shine combos, ledge mix-ups), yet the weakest of the three against `rusher` (0.25) and CPU 8-9 (0.5 and 0.33). More machinery did not pay off in 30 minutes.
- **Common pattern:** all bots except the pilot beat CPU 1-6 almost every time, and all lose every game to HAL, Phillip and Faynt. `rusher` is the hardest scripted baseline. The main score saturates near 83, because 9/12 of the roster is CPUs.

**Harness observations**

- **Tool loop:** 3 idle replies in a row end the loop (`model_stopped`) whatever time is left, so a 30-minute GPT run could quit early. Not tested with full sessions yet.
- **Reasoning:** CLIProxy reported 0-8 reasoning tokens whether or not `reasoning_effort` was set, so the GPT runs may be running with little reasoning.
- **Sandboxing:** agents write to `/tmp` (Opus a replay dumper in `/tmp/dbg`, astra `/tmp/rusher.txt`), and Opus ran the repo's venv Python directly, which it found in `tools/`. No transcript shows reads of repo source, other sessions or the ladder.

## Needed changes outside botwriter/ (not made: other owners)

- `play()` needs a game-level timeout or stall detector. The ladder covers this with `SIGALRM` for now.

## Open questions for Mateo

- **Isolation level.** Is soft isolation enough, or should agents and bots run in Docker? A containerized coding agent also needs its CLI auth mounted.
- **Wall time and runs.** 60 min × 5 runs per model, as in StarSkirmish, or 30 min for cheaper sweeps?
- **Roster.** All 9 CPU levels make up 9/12 of the main score, which saturates. Drop the low levels? Count the hard tier in `roster_score`? Wrap SmashBot as an `agent:`?
- **Characters and stages.** Fox only on FD and BF for now. When do other characters open up, and should the bot choose its own?
- **Budget fairness.** Should the 16 ms be wall time on a shared 32-core machine, or CPU time? Pin bot processes to cores during ladder runs?
- **Leaking roster identity.** Bots cannot read `cpu_level` but can infer CPUs from behaviour. Should CPUs stay in the hidden evaluation tier?
