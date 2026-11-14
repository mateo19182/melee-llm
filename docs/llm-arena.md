# LLM vs LLM arena

Models play each other as [`llm_paused`](llm-player.md) Fox in a Fox ditto, in `fast` mode: the game waits for each decision, so latency never costs a model game time. The arena measures **decision quality** under the standard `llm_paused` prompt, macros and reflexes, not reaction speed. Only a pilot was run here; the untimed track of the [bench](bench.md) later rated the same players over full games.

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

- **Format.** Fox vs Fox, Battlefield and Final Destination, 4 stocks. Each game is **capped at `--cap-frames` game frames** (default 3600, one minute of game time), for cost: see [Cost](#cost). A capped game is scored like a time-out: more stocks wins, then lower percent, else a draw. With `--cap-frames 0` games run to 4 stocks or the 8-minute timer.
- **Schedule.** Round robin only. Every ordered pair plays `--games` games per stage, and each model plays `--anchor-games` games per stage against `cpu:5` and against `cpu:9`, alternating ports. The list is shuffled with a fixed seed, so a run cut short by `--max-tokens` is still roughly balanced.
- **Isolation.** Each game runs in its own process group, with its own Slippi port (51880-51919) and replay dir, on headless display `:98`. A wall timeout (`--timeout`, 3600 s) kills the whole group. The arena never touches `:99` or port 51441.
- **API errors.** A failed call is retried up to `--retries` (4) times; the game is blocked meanwhile, so retries cost wall time only. If all fail, the decision plays the fallback macro (`dash_dance`) and counts as `api_failed`. A game where a side has more than 10% `api_failed` decisions is **void**: not rated, rerun on resume, and never a forfeit, because API trouble is infrastructure.
- **Invalid outputs** (unparseable JSON, unknown action) are the model's own fault and never retried: the fallback plays and the decision counts as `invalid`.
- **Crashes** write an `error` or `timeout` line, and the game is rerun on resume.

## Ratings

Bradley-Terry on the Elo scale from every `ok` game, with **`cpu:9` pinned at 1500** and a draw as half a win (`melee_llm/llm_arena/ratings.py`). `cpu:5` is estimated like a model: CPUs never play each other, so its gap to `cpu:9` comes only through the models. 95% CIs come from 1000 bootstrap resamples of the games, so they include the anchor's uncertainty. Port and stage are not in the model; the schedule balances them.

## Files (`data/llm-arena/<name>/`, gitignored)

| File | What |
|---|---|
| `config.json` | The `run` arguments. |
| `results.jsonl` | Append-only, one line per finished attempt, status `ok`, `void`, `error` or `timeout`. Written by `melee_llm/llm_arena/tournament.py`. |
| `standings.json`, `standings.md` | Ratings, per-model stats and the head-to-head matrix, rewritten by `run` and `standings` (`melee_llm/llm_arena/ratings.py`). |
| `games/<key>/try<N>-<M>/` | Per attempt: the `.slp`, the decision logs `<replay>.p<port>.llm.jsonl` (format in [llm-player.md](llm-player.md#logs)), and `stderr.log`. |

Every game also shows up live on the web UI's All matches page, with `source: "llm-arena"`.

## Cost

Measured in the pilot (1-minute cap, default `llm_paused` options: `interval=30`, JSON mode, `effort=none`). A model decides about every 25-40 frames, and each decision costs about 1.45k (GPT) to 2.4k (Sonnet) prompt tokens, about 900 of them the static system prompt.

| Per game (1 min of game time) | Tokens, mean (min-max) | Wall time |
|---|---|---|
| Model vs model | 366k (254k-523k) | 2.5-10 min, mean 7.7 |
| Model vs CPU | 182k (121k-265k) | mean 4.3 min |

- **Per side:** tokens per game by model are in the [Pilot](#pilot) table.
- **Uncapped:** a game of up to 8 minutes would cost up to about 8 times as much.
- **Parallelism:** Dolphin's CPU use is negligible while it blocks, so 16 parallel games are fine on the shared machine.
- **Full schedule** (`--games 2 --anchor-games 2`, no `--rotate`): with 4 models, 48 model-vs-model and 32 anchor games, about 23M tokens. With 5 models, 80 + 40 games, about 37M.

## Pilot

2026-11-14, run `pilot`: 20 games, 5.84M tokens (5.65M prompt + 0.19M completion), about 11 minutes of wall time at 16 in parallel.

```sh
uv run python -m melee_llm.llm_arena run --name pilot --model claude-sonnet-5-5 --model claude-haiku-4-5-20251001 \
    --model gpt-6-luna --model gpt-6.1-sol --games 1 --anchor-games 1 --rotate --cap-frames 3600 --max-tokens 9000000
```

This is the `--rotate` quarter of the full schedule: every pair of models met twice, once in each port order, and every model played `cpu:5` once and `cpu:9` once.

| # | Player | Elo | 95% CI | W-L | Stock diff | % diff | Decisions/game | Latency | Tokens/game | Invalid |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | gpt-6.1-sol | 1903 | 1599-2265 | 7-1 | +0.75 | +8 | 88 | 2.7 s | 126k | 0 |
| 2 | cpu:5 | 1825 | 1294-2315 | 3-1 | +0.50 | -8 | | | | |
| 3 | gpt-6-luna | 1660 | 1261-2018 | 4-4 | -0.12 | +8 | 117 | 1.6 s | 169k | 0 |
| 4 | claude-sonnet-5-5 | 1587 | 1231-1997 | 3-5 | -0.25 | -4 | 96 | 2.1 s | 230k | 1 |
| 5 | claude-haiku-4-5-20251001 | 1510 | 1009-1835 | 2-6 | -0.50 | +5 | 117 | 1.2 s | 206k | 1 |
| 6 | cpu:9 (anchor) | 1500 | - | 1-3 | -0.25 | -27 | | | | |

**Every CI overlaps every other.** With 8 games per model, the pilot shows that the pipeline works and what it costs. It ranks nothing, and `cpu:5` rating above `cpu:9` is noise. The one suggestive result: gpt-6.1-sol beat every other model in both games, and its only loss was to `cpu:5`.

Observed:

- **Style differs by model.** Sonnet laser-camps: 19% of its decisions are `laser`, against 1% or less for Haiku and Luna. Haiku `wait`s 20% of the time. gpt-6.1-sol makes the fewest decisions, because it picks longer macros (`approach`, `dash_dance`).
- **Self-destructs decide games.** gpt-6-luna lost 3 stocks to `cpu:5` at 7-38%, right after choosing `shine`/wavedash, `dair` or `recover` near the edge.
- **API failures.** gpt-6.1-sol got intermittent `503 auth_unavailable` from the proxy's codex provider: 49 retries, and 8 decisions (1.1% of its decisions) where all retries failed and the fallback macro was played. The Claude models had none.

Files: `data/llm-arena/pilot/{results.jsonl,standings.json,standings.md}`.
