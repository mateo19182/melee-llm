# LLM vs LLM arena

Models play each other as [`llm_paused`](llm-player.md) Fox in a Fox ditto, in `fast` mode: headless, with Dolphin blocking on every input. The game waits for each decision, so latency never costs a model game time. The arena measures **decision quality** under the standard `llm_paused` prompt, macros and reflexes, not reaction speed.

```sh
# round robin: 2 games per ordered pair (so both port orders) per stage, plus 2 games per model vs cpu:5 and cpu:9 per stage
uv run python -m melee_llm.llm_arena run --name pilot \
    --model claude-haiku-4-5-20251001 --model claude-sonnet-5-5 --model gpt-6-luna --model gpt-6.1-sol \
    --games 2 --anchor-games 2 --parallel 16 --cap-frames 3600 --max-tokens 6000000
uv run python -m melee_llm.llm_arena schedule --name pilot --model ... # print the game list, run nothing
uv run python -m melee_llm.llm_arena standings --name pilot           # recompute standings.{json,md}
```

- **Resume:** rerunning the same `run` command skips games with an `ok` result and retries the others until they have `--max-attempts` (2) result lines.
- `--max-tokens` stops starting new games once the run's total spend reaches the limit; running games finish.
- `--opts` appends `llm_paused` spec options to every model (for example `interval=30,history=6`).
- `--rotate` makes the counts per pairing instead of per stage, with the stage rotating: a quarter of the games, still balanced over ports and stages.
- Model ids are whatever `melee_llm.llm.list_models()` returns.
- Offline tests: `uv run --with pytest pytest -q tests/test_llm_arena.py`.

## Rules

- **Format.** Fox vs Fox, Battlefield and Final Destination, 4 stocks. Each game is **capped at `--cap-frames` game frames** (default 3600, one minute of game time), for cost: see [Cost](#cost). At the cap both models stop being asked, and the port 1 LLM pauses and quits with L+R+A+START. The game is scored from its last frame like a time-out: more stocks wins, then lower percent, else a draw. With `--cap-frames 0` games run to 4 stocks or the 8-minute timer.
- **Schedule.** Every ordered pair (A on port 1 vs B on port 2, and the reverse) plays `--games` games per stage. As anchors, each model plays `--anchor-games` games per stage against `cpu:5` and against `cpu:9`, alternating ports (game 0: model on port 1). The game list is shuffled per repetition with a fixed seed, so a run cut short by `--max-tokens` is still roughly balanced. Only round robin is implemented, no Swiss.
- **Isolation.** Each game is `python -m melee_llm.llm_arena one` in its own process group, with its own Slippi port (51880-51919) and replay dir, on headless display `:98`. A wall timeout (`--timeout`, 3600 s) kills the whole group, Dolphin included. First-wave starts are staggered by 6 s. The arena never touches `:99` or port 51441.
- **API errors.** A failed call (timeout, HTTP error, rate limit) is retried up to `--retries` (4) times, after 3, 6, 12 and 24 s. The game is blocked meanwhile, so retries cost wall time only. If all fail, the decision plays `llm_paused`'s fallback macro (`dash_dance`) and counts as `api_failed`. A game where a side has more than 10% `api_failed` decisions is **void**: not rated, rerun on resume, and never a forfeit, because API trouble is infrastructure.
- **Invalid outputs** (unparseable JSON, unknown action) are the model's own fault and never retried: the game plays `llm_paused`'s fallback (`dash_dance` for unparseable, `wait` for an unknown action), and the decision counts as `invalid`.
- **Crashes.** If Dolphin does not connect, the game is retried once, immediately. Any other crash or timeout writes an `error` or `timeout` line, and the game is rerun on resume.

## Ratings

Bradley-Terry by MAP (Newton's method) on the Elo scale (400/ln 10 per natural unit), from every `ok` game, with **`cpu:9` pinned at 1500**. A draw counts as half a win for each side. Each log-strength has a Gaussian prior with sd 2 (≈350 Elo), so a perfect record stays finite. `cpu:5` is estimated like a model: CPUs never play each other, so its gap to `cpu:9` comes only through the models. 95% CIs are the 2.5 and 97.5 percentiles of 1000 bootstrap resamples of the games, refit and re-anchored each time, so they include the anchor's uncertainty.

Port and stage are not in the model. The schedule balances them, and the head-to-head matrix and the per-game lines show them.

## Files (`data/llm-arena/<name>/`, gitignored)

| File | What |
|---|---|
| `config.json` | The `run` arguments. |
| `results.jsonl` | Append-only, one line per finished attempt. |
| `standings.json` | Ratings and per-model stats, rewritten by `run` and `standings`. |
| `standings.md` | The same as tables. |
| `games/<key>/try<N>-<M>/` | Per attempt: the `.slp` (in Slippi's dated subfolder), the decision logs `<replay>.p<port>.llm.jsonl` (format in [llm-player.md](llm-player.md#logs)), and `stderr.log`. |

Every game also shows up live on the web UI's All matches page, with `source: "llm-arena"`, an `arena_key` and the specs.

### `results.jsonl` line

```jsonc
{
  "key": "BATTLEFIELD|claude-sonnet-5-5|gpt-6-luna|0",   // stage|p1 name|p2 name|rep; unique per scheduled game
  "kind": "llm",                 // "llm" (model vs model) or "anchor" (model vs CPU)
  "stage": "BATTLEFIELD", "rep": 0,
  "p1": "llm_paused:claude-sonnet-5-5", "p2": "llm_paused:gpt-6-luna",   // full specs; "cpu:9" for CPUs
  "status": "ok",                // ok | void | error | timeout; only ok is rated
  "port": 51883, "dir": "data/llm-arena/<name>/games/<key>/try0-0", "cap_frames": 3600, "ts": 1794620055.1,
  // ok and void only (from runner.GameResult):
  "winner": 1,                   // 1, 2 or null for a draw
  "stocks": {"1": 4, "2": 3}, "percent": {"1": 37.0, "2": 81.0},
  "frames": 3726,                // in-game frames, including the 123-frame countdown
  "seconds": 702.3, "wall_s": 731.0,   // in-game wall time; whole process (Dolphin boot included)
  "agents": {"1": "llm_paused:claude-sonnet-5-5", "2": "llm_paused:gpt-6-luna"},
  "replay": ".../Game_20261114T023417.slp",
  "sides": {                     // one entry per LLM port ("1" and/or "2")
    "1": {"decisions": 240, "invalid": 0, "api_failed": 0, "api_retries": 1,
          "mean_latency_s": 1.52,      // per successful call
          "mean_think_s": 1.55,        // per decision, retries and backoff included
          "prompt_tokens": 512000, "completion_tokens": 14000,
          "capped_at": 3600,           // frame at which the cap stopped the model, null if the game ended first
          "actions": {"laser": 61, "shine": 40},   // macro started per decision, descending
          "log": ".../Game_20261114T023417.p1.llm.jsonl"}
  },
  // error and timeout only:
  "error": "last stderr line, or \"timeout\""
}
```

### `standings.json`

```jsonc
{
  "generated": 1794621000.0,
  "anchor": {"player": "cpu:9", "elo": 1500},
  "method": "Bradley-Terry MAP ...",
  "games": {"ok": 60, "void": 0, "error": 1, "timeout": 0},     // result lines by status
  "tokens": {"prompt": 5400000, "completion": 160000},          // every attempt, void ones included
  "players": [                                                   // sorted by elo, descending
    {"player": "claude-sonnet-5-5", "kind": "llm",              // model id, or "cpu:5" / "cpu:9" with kind "cpu"
     "elo": 1612, "elo_lo": 1480, "elo_hi": 1790,               // point estimate and 95% bootstrap CI
     "games": 16, "wins": 11, "losses": 5, "draws": 0, "score": 0.688,
     "stock_diff": 0.75,       // mean own minus opponent stocks at the end
     "percent_diff": 22.4,     // mean opponent minus own percent at the end
     "stats": {                // null for CPUs; over every finished game, void ones included
       "games": 16, "decisions_per_game": 231.5, "mean_latency_s": 1.6, "mean_think_s": 1.62,
       "tokens_per_game": 470000, "prompt_tokens": 7300000, "completion_tokens": 220000,
       "invalid": 2, "invalid_rate": 0.0005, "api_failed": 0, "api_retries": 3,
       "actions": {"laser": 0.26, "shine": 0.17}}}            // share of decisions per macro
  ],
  "matrix": {"claude-sonnet-5-5": {"gpt-6-luna": {"w": 3, "l": 1, "d": 0}}}   // row's record against column
}
```

## Cost

Measured in the pilot (Fox ditto, 1-minute cap, default `llm_paused` options: `interval=30`, JSON mode, `effort=none`). A model decides about every 25-40 frames, because most macros end before the 30-frame interval. Each decision costs about 1.45k (GPT) to 2.4k (Sonnet) prompt tokens, about 900 of them the static system prompt.

| Per game (1 min of game time) | Tokens, mean (min-max) | Wall time |
|---|---|---|
| Model vs model | 366k (254k-523k) | 2.5-10 min, mean 7.7 |
| Model vs CPU | 182k (121k-265k) | mean 4.3 min |

- **Per side:** tokens per game by model are in the [Pilot](#pilot) table; gpt-6.1-sol is cheapest because it picks fewer, longer macros.
- **Uncapped:** a game of up to 8 minutes would cost up to about 8 times as much.
- **Wall time** is the two models' calls, made one after the other. Dolphin's CPU use is negligible while it blocks, so 16 parallel games are fine on the shared machine.
- **Full schedule** (`--games 2 --anchor-games 2`, no `--rotate`): with 4 models, 48 model-vs-model and 32 anchor games, about 23M tokens. With 5 models, 80 + 40 games, about 37M.

## Pilot

2026-11-14, run `pilot`: 20 games, 5.84M tokens (5.65M prompt + 0.19M completion), about 11 minutes of wall time at 16 in parallel. Two estimate games came first, then the rest:

```sh
uv run python -m melee_llm.llm_arena run --name pilot --model claude-sonnet-5-5 --model claude-haiku-4-5-20251001 \
    --model gpt-6-luna --model gpt-6.1-sol --games 1 --anchor-games 1 --rotate --cap-frames 3600 --max-tokens 9000000
```

This is the `--rotate` quarter of the full schedule: every pair of models met twice, once in each port order, each time on a different stage, and every model played `cpu:5` once and `cpu:9` once, one on each stage and port.

| # | Player | Elo | 95% CI | W-L | Stock diff | % diff | Decisions/game | Latency | Tokens/game | Invalid |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | gpt-6.1-sol | 1903 | 1599-2265 | 7-1 | +0.75 | +8 | 88 | 2.7 s | 126k | 0 |
| 2 | cpu:5 | 1825 | 1294-2315 | 3-1 | +0.50 | -8 | | | | |
| 3 | gpt-6-luna | 1660 | 1261-2018 | 4-4 | -0.12 | +8 | 117 | 1.6 s | 169k | 0 |
| 4 | claude-sonnet-5-5 | 1587 | 1231-1997 | 3-5 | -0.25 | -4 | 96 | 2.1 s | 230k | 1 |
| 5 | claude-haiku-4-5-20251001 | 1510 | 1009-1835 | 2-6 | -0.50 | +5 | 117 | 1.2 s | 206k | 1 |
| 6 | cpu:9 (anchor) | 1500 | - | 1-3 | -0.25 | -27 | | | | |

**Every CI overlaps every other.** With 8 games per model, the pilot shows that the pipeline works and what it costs. It ranks nothing.

- The one suggestive result: gpt-6.1-sol beat every other model in both games, and its only loss was to `cpu:5`.
- `cpu:5` rating above `cpu:9` is noise on 4 games each.
- CIs of about ±150 Elo need about 4 times the games: the full schedule.

Observed:

- **Style differs by model.** Sonnet laser-camps: 19% of its decisions are `laser`, against 1% or less for Haiku and Luna. Haiku `wait`s 20% of the time. gpt-6.1-sol makes the fewest decisions, because it picks longer macros (`approach`, `dash_dance`). Every model reasons about respawn and ledge invulnerability ("retreat until the respawn protection expires").
- **Self-destructs decide games.** gpt-6-luna lost 3 stocks to `cpu:5` at 7-38%, right after choosing `shine`/wavedash, `dair` or `recover` near the edge.
- **Invalid outputs are rare:** 2 in about 3,300 decisions.
- **API failures.** gpt-6.1-sol got intermittent `503 auth_unavailable` from the proxy's codex provider: 49 retries, and 8 decisions where all retries failed and the fallback macro was played (1.1% of its decisions, under the 10% void threshold). The Claude models had none.

Files: `data/llm-arena/pilot/{results.jsonl,standings.json,standings.md}`.
