# Bot-writer track

A coding agent (Claude Code, Codex, or a plain tool loop over an OpenAI-compatible API) gets a
sandbox with a bot template, libmelee docs, frame data and tools to play practice games. It
iterates on a single-file bot for a fixed wall-clock budget. Its final bot is then ranked on a
ladder against a fixed roster. The track follows [StarSkirmish](https://starskirmish.com/bench/v0-1/)
(LLMs write Brood War bots in one hour) and LLM Skirmish (Screeps), adapted to Melee and libmelee.

Code lives in `melee_llm/botwriter/`:

| file | role |
| --- | --- |
| `host.py` | Child process that loads `bot.py`, steps it and returns its controller state as JSON. Also has the audit-hook guard and `FakeController`. |
| `agent.py` | `BotAgent(Agent)`: the parent side. Enforces the per-frame budget, hides the opponent's inputs and identity, counts violations. |
| `specs.py` | Player specs: `cpu:N`, `idle`, `baseline:NAME`, `bot:PATH`, `agent:MODULE:CLASS[:ARG]` (learned bots). |
| `practice.py` | `play` (real games, needs the ISO) and `check` (offline: recorded replays through the bot). |
| `summary.py` | Per-game replay summary: stocks, damage, hits, deaths with cause, % time offstage, action histogram. |
| `dolphin.py` | Claims a distinct Slippi port per process so Dolphins run in parallel. Also finds the ISO. |
| `ladder.py` | Evaluation: jobs, parallel workers, `games.jsonl`, `leaderboard.json`, Bradley-Terry. |
| `session.py`, `toolloop.py` | Build a sandbox, run a coding agent with a budget, and collect the bot, transcript and cost. |
| `batch.py`, `round1.json` | Run a plan of sessions N at a time with per-slot port ranges and retries; `round1.json` holds the paused round-1 runs. |
| `template/` | What the agent sees: `README.md` (task, rules, scoring, tools), `bot.py` starter, `docs/`. |
| `baselines/` | Scripted Fox bots (`rusher`, `laser`, `shine`). They are copied into the sandbox as `opponents/`. |

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

One file defines `class Bot` with a `character` attribute and
`step(gamestate, controller, port, opp_port)`. An optional `on_game_end(gamestate)` resets
per-game state. `BotAgent` wraps the file as an `Agent`:

- **Process isolation.** The bot runs in `python -I -B` with a scrubbed environment (no API keys,
  `HOME` set to a scratch dir), a 4 GiB address-space limit and its own session. A crash cannot
  take down the match.
- **Protocol.** The parent pickles each GameState down to the child (about 0.05 ms per frame, with
  reductions in `host.py` that skip numpy's and copyreg's slow paths but rebuild the same types). It
  sends to both bots before reading either answer, so they think at the same time. The child
  answers with JSON: the bot's full controller state. The parent never unpickles anything
  the bot produces. Only the inputs that changed are written to the real Dolphin pipe, with
  libmelee's analog fixing kept exact. START is dropped.
- **Budget.** The default is 16 ms per frame of wall time, measured in the parent, in every mode.
  A late answer is recorded as `late`. The controller keeps its old inputs, frames that arrive
  while the bot is still busy are `skipped` (not queued), and the stale answer is dropped. An
  exception in `step` is caught and counted, and that frame is lost. If the process dies, all
  buttons are released for the rest of the match (`crashed`). Startup gets 20 s.
- **What the bot sees.** A shallow copy of the GameState in which the opponent's (and Nana's)
  `controller_state` is neutral, and `cpu_level`, `displayName`, `connectCode` and `nickName`
  are blank.
- Per-game stats (frames, answered, late, skipped, exceptions, policy violations, crashed,
  mean/p99/max ms) are written to every practice report and ladder game record.

## Practice tools (sandbox)

`tools/practice` plays in `fast` mode (ExiAI Dolphin, headless, unthrottled). Games alternate
spawn sides. Each game prints a compact block plus a final JSON line. The full report, replays and
`bot.log` go to `runs/<ts>/`. Practice opponents are `cpu:N`, `idle`, `baseline:*`, `bot:PATH`
and `self`. `agent:` specs (learned bots) are refused, so the hidden tier stays hidden.
`tools/check-bot` needs no ISO: it replays the sample `.slp` files through the bot, at real-time
pace whenever the bot falls behind, and reports crashes, exceptions, policy violations and frame
times. `tools/inspect-replay` and `tools/time-left` round out the set.

## Ladder and scoring

- **Format v0:** Fox ditto on Final Destination and Battlefield, both spawn sides,
  `games_per_side` games per (entrant, opponent, stage, side), so 2 × 2 × 2 = 8 games per pairing
  by default. Each job is one `play()` call in its own Dolphin. Workers are `spawn` processes,
  each holding a Slippi port lock under `/tmp/melee-llm-slippi-ports`. A job that hangs is killed
  by `SIGALRM` after `job_timeout_s`.
- **Default roster:** CPU 1-9 plus `baseline:laser`, `baseline:rusher` and `baseline:shine`.
  Learned bots go in as `agent:melee_llm.bots.<module>:<Class>` once they exist.
- **Primary score:** `roster_score` is the mean, over roster opponents, of the entrant's win rate
  (a draw counts ½). Every opponent weighs the same, whatever the game counts. This follows
  StarSkirmish v0.2, which dropped Elo for plain win rates against a fixed roster. Because the
  score doesn't depend on the other entrants, a new bot can be scored without replaying the field,
  and the bar stays comparable across model generations. A Wilson 95 % interval is reported.
- **Secondary:** the project's one Bradley-Terry fit (`melee_llm/ratings.py`: MAP with a Gaussian prior, so
  undefeated bots stay finite) over all games, on an Elo scale anchored at `cpu:1` = 0. Turn on
  `entrants_play_each_other` and `calibrate_roster` to add entrant-vs-entrant and roster-vs-roster
  games. `cpu_ladder_level` is the highest CPU level beaten at least half the time, with every
  lower roster CPU beaten too.
- **Per model:** entrants are named `<model>/<run>`. `models` reports the mean and SD of
  `roster_score` over runs, mean Elo and the best run. Report the mean, not the best. StarSkirmish
  saw an 18-point spread between runs of one model.
- **Integrity:** each entrant gets totals of late/skipped frames, exceptions, crashes, policy
  violations and forfeits. Any policy violation or forfeit sets `flagged`. A bot that fails to
  load or picks a disallowed character forfeits its games. A broken roster opponent is an `error`
  (excluded from scoring and retried on the next run), not a free win.

## Decisions taken (change freely)

- **Budget per session:** 60 min of wall time by default (`--minutes`), following StarSkirmish.
  Claude Code also gets `--max-budget-usd`, and the tool loop gets `--max-tokens`. There is no
  submit tool. Whatever is in `bot.py` at the deadline is collected, along with a tarball of the
  whole sandbox (practice logs, saved versions) for analysis. If Claude Code ends its turn early,
  it is resumed (`--resume <session-id>`) with "N minutes are left, keep improving", up to 30
  times. The tool loop does the same.
- **Harness setup:** Claude Code runs with `--safe-mode` (no user CLAUDE.md, skills, hooks or MCP),
  `--strict-mcp-config`, WebFetch and WebSearch disallowed, and `bypassPermissions` inside the
  sandbox. Codex runs with `--ignore-user-config --ephemeral`. API keys are scrubbed from the
  agent's environment.
- **Allowed in bots:** the standard library, `melee` and `numpy`. One file. Reads only from the
  interpreter, the `melee_llm` package and the scratch dir. Writes only to scratch.
- **Anti-cheat (bot runtime):** the `Guard` audit hook in `host.py` blocks sockets, subprocesses
  and exec, fork, ctypes `dlopen`, `kill`, reads under `/home`, `/tmp`, `/root`, `/mnt` and
  `/proc/<other>`, and writes outside scratch. Each attempt raises inside the bot and is counted.
  Combined with the sanitized GameState, a bot sees the same thing a player sees on screen.
  **This is a tripwire, not a security boundary**: CPython audit hooks can be bypassed (for example
  `_posixsubprocess.fork_exec`, or C extensions already loaded). For leaderboard-grade runs, run
  the bot host inside `docker run --network none --read-only` with only the bot file mounted. The
  protocol over stdin/stdout already supports that (`docker` works on this host; bubblewrap and
  unprivileged user namespaces do not, because AppArmor blocks them).
- **Anti-cheat (coding agent):** isolation is soft. The sandbox is a random directory under
  `$BOTWRITER_HOME/sandboxes/`, separate from the session records, and practice cannot reach
  `agent:` opponents. But the agent runs as `mateo` and could `cat` this repo, other sessions or
  the hidden roster. Mitigations so far: the README rule, and transcripts to audit (grep for paths
  outside the sandbox). See open questions.
- **Practice vs evaluation conditions:** both use the same `BotAgent`, budget and sanitization.
  The only differences are the opponents and the number of games.

## Testing status

Verified offline (before the ISO was available):

- The starter bot and all three baselines load and run over 4.9k recorded frames with 0
  exceptions, p99 below 1 ms and inputs on every frame.
- Adversarial bots behave as intended:
  - A bot sleeping 50 ms every 100 frames gets `late` and `skipped` counts and keeps playing.
  - `os._exit` mid-game is reported as `crashed`.
  - A bot raising every frame has its exceptions counted and logged, and its prints stay out of
    the protocol.
  - A bot hanging at import fails to load after the 20 s startup limit.
  - A missing `Bot` class fails to load with a traceback.
  - A cheat bot is blocked on 7 of 7 attempts: reading `~/.hermes/.env`, connecting to a socket,
    running a subprocess, `os.system`, reading `/proc/<parent>/environ`, reading the repo README
    and writing to `/tmp`. It sees the opponent's controller as neutral.
- The controller command stream written to the pipe uses libmelee's exact command format.
- The replay summary was checked on the sample replays. On itemExport it reports a kill at
  84.9 % through the bottom blast zone.
- Bradley-Terry recovers simulated 75 % / 75 % strengths (≈ +190 Elo per step). The leaderboard
  was built from synthetic games. The ladder ran end to end through the process pool, port locks
  and JSONL, with forfeiting entrants (no Dolphin needed).
- Sessions:
  - Claude Code smoke session (Haiku, 3 min, $0.003): the sandbox was built, the agent read the
    README, ran `tools/check-bot` and `tools/time-left`, and the final bot was collected and
    validated. Haiku stopped after 10 s, which is why continuation nudges now exist. They work
    (round 1: Opus was resumed 7 times, Sonnet 31 times).
  - The OpenAI-compatible tool loop was tested with 5 turns of Haiku through CLIProxy: bash,
    read and edit all worked.

Verified with the ISO (pilot and round 1, below): practice games and ladder games end to end,
up to 10 ladder Dolphins plus 12 practice Dolphins in parallel on distinct ports, and the
baselines in real games. Real sessions under both the `claude` and `openai` harnesses work
(3-minute smokes with Haiku and gpt-6-astra, then the 30-minute round-1 runs).

Still unverified: the Codex harness. codex-cli 0.166 on the ChatGPT login refuses
`gpt-6-astra` ("not supported when using Codex with a ChatGPT account"); `gpt-6.1-sol` should
work there but no session has been run.

## Round 1 results (2026-11-14)

**Paused after one run per Claude model.** The planned study was 3 × 30-minute runs each of Opus 5.5,
Sonnet 5.5 and Haiku 4.5 (Claude Code) and gpt-6-astra and gpt-6.1-sol (tool loop over CLIProxy).
After the first wave Mateo paused it to save Claude subscription usage. The 12 remaining runs are in
`melee_llm/botwriter/round1.json`. Resume them, 3 at a time on ports 51560-51571, with:

```sh
systemd-run --user --unit melee-ladder-r1-sessions --working-directory="$PWD" \
  --setenv=PATH="$HOME/.local/bin:/usr/bin:/bin" --setenv=DISPLAY=:98 --setenv=MELEE_ISO=$HOME/melee.iso \
  .venv/bin/python -m melee_llm.botwriter.batch --plan melee_llm/botwriter/round1.json \
  --log ~/.local/share/melee-llm/botwriter/rounds/r1/runs.jsonl
```

Then add each `sessions/<id>/final/bot.py` to `~/.local/share/melee-llm/botwriter/ladders/v1.json` and
re-run `ladder run` on it. It only plays the new games.

**Ladder v1:** Fox ditto on FD and BF, both ports. The main roster is CPU 1-9 plus the 3 scripted
baselines, at 3 games per (opponent, stage, side), so 144 games per bot. The hard tier is HAL,
Phillip, MIMIC and Faynt, at 1 game per (opponent, stage, side), so 16 games per bot. That makes
640 games: 112 reused from the pilot ladder, and the rest in about 2 h on 10 Dolphins. 9 hard-tier jobs first died of CUDA OOM, because other
processes held 17 GB of the GPU, and were re-run with 3 workers. Across all bots, 188 of about
7.6 M frames were late and 15 were skipped. No bot had exceptions, crashes or policy
violations. Draws (8-minute timeouts, mostly against `laser` and `shine`) count ½.

| model | harness | runs | main score (95 % CI) | hard tier | CPU level | Elo | cost | wall | LoC | practice games | SmashBot overlap |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Sonnet 5.5 (run1) | Claude Code | 1 | **83.0** (76.0-88.2) | 0 / 16 | 9 | 461 | $0.45 | 28.5 min | 135 | 38 | 0.084 |
| Haiku 4.5 (run1) | Claude Code | 1 | **83.0** (76.0-88.2) | 6.2 (1 win vs MIMIC) | 7 | 469 | $0.44 | 30.0 min | 108 | 18 | 0.071 |
| Opus 5.5 (run1) | Claude Code | 1 | 76.4 (68.8-82.6) | 0 / 16 | 8 | 384 | $1.82 | 29.1 min | 303 | 32 | 0.035 |
| Sonnet 5.5 (pilot1) | Claude Code | 1 | 17.7 (12.3-24.8) | 0 / 16 | 0 | -170 | $0.32 | 29.5 min | 148 | n/a | 0.115 |
| gpt-6-astra, gpt-6.1-sol | tool loop | 0 | paused | | | | | | | | |

Notes on the table:

- Per model, Sonnet is 50.4 ± 32.6 over 2 runs. With one run each, Sonnet, Haiku and Opus are not
  separable: the CIs overlap, and the two Sonnet runs differ by 65 points.
- Cost is Claude Code's API-equivalent `total_cost_usd`; usage was billed to the subscription.
  Earlier records summed it over `--resume` calls, but the value is cumulative. That inflated
  Sonnet run1 to $10.96 and Opus to $13.22. It is fixed in `session.py`, and the old values are
  kept as `cost_usd_summed_bug` in those `meta.json` files.
- Overlap is `similarity.py`'s renamed 12-token-shingle overlap. The baselines and the starter
  template score 0.08-0.11, and the flag threshold is 0.25. No bot is flagged.
- Reference Elo (CPU 1 = 0): CPU 9 441, `rusher` 423, `laser` 258, `shine` 236, MIMIC 763, HAL,
  Phillip and Faynt 894. Hard-tier Elos rest on very few non-wins. The Elo column and these values were
  recomputed on 2026-11-14 with the shared fit; the ladder's own fit gave 470, 479, 391 and -171 for the
  four bots, and the order is unchanged.

**What each model built**

- **Sonnet run1** (`shiner`, 135 lines): a compact, reactive, stateless bot. On the ground in range
  it shines and jump-cancels the shine with a tapped jump (frame 3 or later). It grabs a shielding
  opponent, forward-smashes above 110 %, fires periodic lasers at range and spams nair in the air.
  It recovers with a double jump, then a firefox aimed at a point above the ledge. Practice: 13/18
  against CPU 9, 0/6 against the baselines. After about 21 minutes it declared the bot final and
  ignored the next ~25 "keep improving" nudges with one-line replies (31 resumes in total).
- **Sonnet pilot1** has the same skeleton (`shiner`, the same helpers) but holds B instead of
  tapping it, so its shine rarely comes out. Its recovery also self-destructs off the bottom about
  twice a game, and it loses even to CPU 1. Most of the 65-point gap between the Sonnet runs comes
  from a few lines of input timing and recovery.
- **Haiku run1** (108 lines): the simplest bot. At close range it calls libmelee's built-in
  `melee.techskill.multishine`. A little further out it up-smashes, at mid range it dashes in and
  jabs, otherwise it walks toward the opponent without passing the ledge. Its firefox recovery is
  aimed at the ledge. It is the best against the scripted baselines (0.75 against each) and took
  the only hard-tier win (1 game against MIMIC). One invocation, and it never stopped early.
- **Opus run1** (303 lines): the most engineered bot. It has a macro queue (frame-by-frame input
  sequences) and reactive defence from `FrameData.in_range` (shield, or shine if the hit is ≥ 2
  frames away). It punishes cooldown frames read from `attack_state`, then chains grab into up-throw
  or down-throw by percent, shine into jump-cancel into up-air, and dash grab or short-hop nair.
  It also mixes ledge getup, ledge jump and roll at random, DIs in, fast-falls and lasers an
  offstage opponent. It wrote its own frame-by-frame replay dumper in `/tmp/dbg` using the repo's
  venv Python, which it found in `tools/`. That is legitimate, but it wrote outside the sandbox.
  It is the weakest of the three against `rusher` (0.25) and CPU 8-9 (0.5 and 0.33). More
  machinery did not pay off in 30 minutes.
- Common pattern: all bots beat CPU 1-6 almost every time (except the pilot) and lose every game
  to HAL, Phillip and Faynt. `rusher` is the hardest scripted baseline. The main score saturates
  near 83, because 9/12 of the roster is CPUs.

**Harness observations**

- Codex: codex-cli 0.166 on the ChatGPT login refuses `gpt-6-astra`, so astra needs the `openai`
  tool loop.
- Tool loop: in the 3-minute astra smoke it ended with `model_stopped`. This was not a bug. The
  model went idle in the last 6 s, after a "0 minutes left" nudge. The real weakness is that 3
  idle replies in a row end the loop whatever time is left, so a 30-minute GPT run could quit
  early. Not tested with sessions yet. Also, CLIProxy reported 0-8 reasoning tokens whether or
  not `reasoning_effort` was set, so the GPT runs may be running with little reasoning.
- Sandboxing: agents write to `/tmp` (Opus `/tmp/dbg`, astra `/tmp/rusher.txt`), and Opus used
  the repo's venv directly. No transcript shows reads of repo source, other sessions or the
  ladder.

## Needed changes outside botwriter/ (not made: other owners)

1. `runner.play()` should accept `slippi_port` (or `**console_kwargs`). `dolphin.claim_slippi_port`
   currently rebinds `melee.Console` with `functools.partial` inside each worker process. That
   is safe because each worker is a single process, but it is a hack.
2. `play()` should return each game's replay path in `GameResult`. Pairing replays by sorted
   filename assumes one `.slp` per finished game.
3. Live (`watch`) matches with two `BotAgent`s step them one after the other, so the worst case is
   2 × 16 ms per frame. A split `begin_step` / `end_step` in the Agent contract would let the
   runner send both frames before waiting. Fast mode is unaffected, because the game blocks on
   input.
4. A game-level timeout or stall detector in `play()`. The ladder covers this with `SIGALRM` for
   now.

## Open questions for Mateo

- **Isolation level.** Is soft isolation enough for v0, or should agents and bots run in Docker
  from the start? Running the coding agent in a container also needs its CLI auth mounted.
- **Wall time and runs.** 60 min × 5 runs per model, as in StarSkirmish? Is 30 min enough for
  cheaper sweeps? The budget is also limited by practice throughput. Fast-mode game length
  hasn't been measured here yet (my unverified guess is 1-2 min of wall time). Should practice run several games in parallel? `practice` already
  claims its own port, so concurrent calls work.
- **Roster for v0 scoring.** Which CPU levels? All 9 means CPUs make up 9/12 of the score. Should
  the learned bots (HAL, Faynt, MIMIC) count in `roster_score` or be reported as a separate
  "hard tier" column? And should SmashBot itself be wrapped as an `agent:`?
- **Characters and stages.** Fox only on FD and BF for now. When should other characters open up,
  and should the bot choose its own?
- **Contamination.** SmashBot, libmelee examples and Phillip/slippi-ai are public and in training
  data. Allow porting SmashBot logic, or forbid it and check for near-copies?
- **Budget fairness.** Should the 16 ms be wall time on a shared 32-core machine, or CPU time? Pin
  bot processes to cores during ladder runs?
- **Leaking roster identity.** Bots cannot read `cpu_level`, but they can infer CPUs from behaviour.
  That's fine as skill, but should CPUs stay in the hidden evaluation tier?
