# Melee Bench

One leaderboard where every kind of player gets one rating on one scale: built-in CPUs, learned bots, scripted and LLM-written bots, LLMs playing directly, Jev, and LLM coaches of Reyn. Later, Mateo himself over netplay. The web UI's **Bench** page (`/bench`) shows it, with a page per entrant.

```sh
uv run python -m melee_llm.bench entrants                 # the registry
uv run python -m melee_llm.bench imports                  # which older games count, and why the others don't
uv run python -m melee_llm.bench standings                # recompute data/bench/standings.json (1000 bootstraps)
uv run python -m melee_llm.bench run --budget 100 --target 125    # the fill (resumable); runs as unit melee-bench
```

## The standard game

Fox vs Fox, Battlefield or Final Destination (stages and ports alternate per pairing), 4 stocks, 8-minute timer, a full game. A timed-out game goes to the player with more stocks, then lower percent. Other characters and stages are future variants: they would be separate boards, not mixed into this one.

## Two tracks

| Track | Who | How the game runs |
|---|---|---|
| **Real time** | `llm_live:<model>`, `jev_live`, `coach:<model>`, `coach_jev`, `coach:random` | `realtime` mode: headless ExiAI Dolphin capped at 60 fps, in lockstep. The game never waits for a decision: live players and coaches think on a background thread, and their latency costs game time, as for a human. |
| **Untimed** | `llm_paused:<model>`, `jev_paused` | `fast` mode: headless, and the game waits for every decision. Measures decision quality only. |
| **Both** | CPUs, learned bots, scripted and LLM-written bots | Token-free players. They step every frame synchronously, so they play identically in both modes; their games run in `fast` mode and count on **both** boards. |

The shared games tie the two scales together: `cpu:9` is 1500 on both boards, and every CPU and bot has (nearly) the same rating on both. A live and a paused LLM can then be compared through those anchors, even though they never meet.

**Real-time validity.** `realtime` is a mode added to `runner.play()` for the bench: the ExiAI build with the Null renderer and `emulation_speed=1`, blocking on input. It holds 60 fps headless on the loaded machine (measured 59.6-60.4), without the GPU rendering `lockstep` uses. The runner still waits if a bot is late, so if the machine is overloaded the game slows down, which hands a wall-clock player extra game time per decision. So every real-time game records its mean fps, and one below **50 fps** is marked `slow`: kept in the results, not rated, and the pairing stays available. The same rule filters imported games.

**Written bots** keep their 16 ms per-frame wall budget (`BotAgent`) in every mode, so they are token-free "both" entrants.

## Entrants

`melee_llm/bench/entrants.py` holds the registry: id, label, category, track, run spec, one-line description, who pays (provider), and aliases for importing older results.

| Category | Entrants | Notes |
|---|---|---|
| CPU | `cpu:1,3,5,7,9` scheduled; `cpu:2,4,6,8` from imports only | `cpu:9` is the anchor, 1500 |
| Learned bot | `phillip:silver`, `phillip:plat`, `phillip:gm`, `hal:MASTER`, `mimic`, `faynt` (10M-Arena), `reyn` (no command) | Phillip tiers give graded anchors above the CPUs |
| Scripted bot | `baseline:laser`, `rusher`, `shine` | The bot-writer's reference bots |
| LLM-written bot | `written:<session name>`: every bot-writer session of 10+ minutes with a `final/bot.py` | Picked up automatically from `~/.local/share/melee-llm/botwriter/sessions/` |
| LLM player | `llm_live:<m>` and `llm_paused:<m>` for Haiku 4.5, Sonnet 5.5, gpt-6-luna, gpt-6.1-sol | Default options (`interval=30`, JSON, `effort=none`) |
| Jev player | `jev_live`, `jev_paused` | Default options |
| Coach → Reyn | `coach:<m>` for the four models, `coach_jev`, `coach:random` (control) | `interval=300` (one call per 5 s), as in the coach and Jev pilots |
| Human | `human:mateo` | Reserved slot, see below |

## Rating method

`melee_llm/bench/ratings.py`. Per track, a Bradley-Terry fit by MAP (llm_arena's `fit`: Newton's method, Gaussian prior with sd 2 per log-strength so undefeated records stay finite, a draw is half a win), on the Elo scale (400 points ≈ 10:1 odds), **`cpu:9` pinned at 1500**. A track's games are all `ok` games whose two players both play that track.

The 95% interval shown is the wider of two estimates: the 2.5/97.5 percentiles of bootstrap resamples of games (refit and re-anchored each time), and the Laplace estimate (±1.96 sd from the inverse Hessian). The bootstrap alone is too narrow for a perfect record: every resample is also perfect. An entrant is "converged" when that half-width is at most the target (default ±125).

Port and stage are not in the model; the scheduler balances them per pairing.

## Imported games

`melee_llm/bench/imports.py` reads older results in place and tags them `imported`. A game counts only if it is the standard game (Fox ditto, BF/FD, full game) between two bench entrants with the bench's spec options, and, with a wall-clock player, ran at 50+ fps. Sources:

- bot-writer ladders (`ladders/*/games.jsonl`, fast mode): most of the imported games; forfeits and self-play are excluded.
- coach and Jev pilots (`replays/{coach,jev}-pilot/*/results.jsonl`, lockstep): most coach games ran at 15-45 fps on the overloaded machine and are excluded; uncoached Reyn games count (a bot is unaffected by fps). Fixed-command Reyn and `interval=60` coaches are not bench entrants.
- the LLM arena (`data/llm-arena/*/results.jsonl`): games were capped at one minute, so only the few that ended before the cap count.
- the learned-bot arena (`arena/results.jsonl`): random characters and stages, so only its Fox dittos on BF/FD.

The page lists the excluded counts by reason under "Older games not imported".

## Scheduler: active sampling under a budget

`melee_llm/bench/scheduler.py`, unit `melee-bench`. Every few seconds, if a slot is free:

1. Per track, fit the current games (bench + imported) and take the Laplace covariance Σ. Games still running are added to the precision as if already played, so one pairing is not started six times at once.
2. For each pairing (a, b) with win probability p, one more game adds Fisher information w = p(1−p) along d = e_a − e_b. By Sherman-Morrison the anchored variance of entrant k drops by w·(c_kᵀΣd)² / (1 + w·dᵀΣd). The pairing's value is the sum of those drops over entrants still wider than the target (converged ones weigh 2%), summed over both boards for shared pairings.
3. Divide by the expected cost: each side's mean CLIProxy tokens per game so far (priors until it has games: 900k for `llm_paused`, 350k for `llm_live`, 80k for a coach, 0 for Jev and bots), plus 60k token-equivalents of machine time per game. Close ratings and wide intervals win; free games are played often; expensive LLMs play where they still need games and against opponents near their level.
4. Skip pairings that do not fit the free resources, then start the best one (with ±15% jitter).

Resources (defaults, `run --help`): at most 14 games; 3 unthrottled token-free games, 6 real-time and 8 untimed-LLM games at once; 6 LLM sides in flight per provider (`claude`, `gpt`) and 4 for Jev, which spreads load across the two subscriptions; 6 GPU bot processes and 1.5 GB free VRAM per GPU bot (Reyn, HAL, MIMIC, Phillip); a new game only when the 1-minute load is under 36 (but always at least 2 running, since other services set most of the load) and 20 s after the previous start. While the `melee-llm-arena` unit runs, at most 3 token-spending games. Unthrottled bot games run under `nice`.

It stops when every active entrant is converged, when the CLIProxy token budget is spent (games in flight count against it at their estimate), or when nothing fits and nothing runs for 30 minutes. An entrant whose last three bench games all failed (crash, CUDA OOM, API outage) sits out for an hour. Restarting resumes from `results.jsonl`, budget included.

**Budget.** Only CLIProxy tokens (Claude and GPT models) count toward `--budget`; Jev is billed to its own TypeSafe key at about a cent per game and reported in USD. The page shows spend per provider and per entrant (tokens and list-price USD per game, where a price is known).

## Isolation and files

Each game is `python -m melee_llm.bench one` in its own process group, with its own Slippi port (51920-51999) and replay dir `replays/bench/<game id>/` (replay, decision logs, `stderr.log`), on the headless display `:98`. It never touches `:99` or port 51441. A wall timeout (25 min, 3 h for untimed LLM games) kills the group, Dolphin included. `llm_paused` sides are wrapped in llm_arena's `ArenaLLM` for its transport retries (no frame cap). A game where a side's calls failed more than 10% of the time is `void`: kept, not rated.

| File (`data/bench/`, gitignored) | What |
|---|---|
| `results.jsonl` | Append-only, one line per finished game: entrant ids and specs, stage, mode, track, status (`ok`, `void`, `slow`, `error`, `timeout`), winner, stocks, percent, frames, fps, wall time, `sides` (per LLM port: decisions, calls, errors, tokens, USD, mean latency, log path), `bot_stats` for written bots |
| `standings.json` | Both boards, spend per entrant, the registry, import counts. Rewritten by the scheduler at most every 2 min |
| `status.json` | Scheduler progress: phase, spend, running games, unconverged entrants, recent log lines |

Bench games also appear on All matches (source `bench`) and in Games, where the replay page plays them with their decision logs.

## Adding an entrant

Add an `Entrant` to `registry()` in `entrants.py` with an id, category, track and spec, and restart the unit; the scheduler sees a player with a wide interval and plays it first against opponents near the board's middle. Examples:

```python
# a janky variant of the live player: decides every 10 frames, drops replies older than 40
Entrant("llm_live:claude-haiku-4-5-20251001,interval=10", "Haiku 4.5 live (jumpy)", "llm", "realtime",
        "llm_live:claude-haiku-4-5-20251001,interval=10,max_stale=40", "Haiku live with a short leash.",
        provider="claude"),
# a fixed-command Reyn
Entrant("reyn:lasers", "Reyn lasers", "learned", "both", "reyn:Keep your distance and shoot lasers.",
        "Reyn holding one command all game.", gpu=True),
```

Any spec `match.py` understands works, plus the bot-writer's `bot:PATH` and `baseline:NAME`. A wall-clock kind (`llm_live`, `jev_live`, `coach`, `coach_jev`) makes the entrant real-time automatically. New bot-writer sessions show up as `written:` entrants on the next start.

## Mateo via netplay

`human:mateo` is reserved (inactive, no spec). To rate a human, games have to be played against bench entrants over Slippi Direct Connect ([netplay.md](netplay.md)) under the standard rules, and appended to `results.jsonl` with `p1`/`p2` ids, `mode: "netplay"`, `track: "realtime"` and the result; the fit takes them like any other game. The natural opponents are entrants with known ratings near his level (a CPU or Phillip tier first, then whatever the scheduler would pick). Netplay adds input delay and rollback, so these games are real-time by nature; the scheduler does not start them.

## Results

See the Bench page for live standings. The overnight run of 2026-11-14 is summarised below once it finishes.
