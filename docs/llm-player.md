# LLM player

An LLM picks **macro-actions** from structured state, and a deterministic frame-level executor turns them into controller inputs. The LLM never presses buttons. This follows what worked in earlier projects (reflex, LLM Colosseum), which also favoured small fast models.

```sh
uv run -m melee_llm.match --iso ~/melee.iso --mode paused --p1 llm_paused:claude-haiku-4-5-20251001 --p2 cpu:3
uv run -m melee_llm.match --iso ~/melee.iso --p1 llm_live:claude-haiku-4-5-20251001,interval=20 --p2 cpu:3
```

The spec format is `<kind>:<model>[,key=value...]`. Keys: `interval` (frames between forced decisions, default 30), `history` (past decisions in the prompt, default 6), `mode` (`json`, the default, or `tool` for function calling), `effort` (`reasoning_effort`, default `none`), `base_url` (a local vLLM or llama.cpp server), `timeout`, `reflexes` and `max_stale` (live only). `MELEE_LLM_BASE_URL` and `MELEE_LLM_API_KEY` override the CLIProxy defaults. Otherwise the key comes from `CLIPROXY_API_KEY` in `~/.hermes/.env` and is never logged.

## Modules

| File | Role |
|---|---|
| `melee_llm/state.py` | Builds the observation and renders it as about 100-170 tokens of text; `EventTracker` summarises hits, stocks, ledge grabs, techs, grabs and shield breaks. |
| `melee_llm/actions.py` | The macros, and the `Executor` that runs one at a time and runs reflexes. |
| `melee_llm/llm.py` | OpenAI-compatible client: tool or JSON mode, tolerant JSON parsing, latency and token accounting. |
| `melee_llm/agents/llm_common.py` | System prompt, decision history and the JSONL log, shared by both agents. |
| `melee_llm/agents/llm_paused.py` | `PausedLLM` decides when the macro ends, or every `interval` frames if the macro is interruptible. It blocks while thinking, so use it only in `--mode paused`. |
| `melee_llm/agents/llm_live.py` | `LiveLLM` asks a background thread and never blocks. Until a reply arrives the executor keeps running the last macro or a default (dash dance, or shield when the opponent is close). Replies older than `max_stale` frames are dropped. |

## Sample rendering (Falco vs Samus replay)

```
f1370 time 7:38
YOU FALCO 58% 4stk | pos (-36,38) vel (+0.0,-2.0) face L air | nair f19 [ACTIVE] | jumps 1, busy | 33 from edge
OPP SAMUS 60% 4stk | pos (-25,0) vel (+0.9,+0.0) face R ground | walk_fast f15 | jumps 2, actionable | 44 from edge
REL opp is right+below: dx +11 dy -38 dist 40; you face AWAY from opp; opp faces away from you
EVENTS you hit opp 10x +27%
RECENT DECISIONS:
f1230 laser(short,1) → laser: fired 1, landed
```

## Actions

- **Movement:** `wait`, `approach`, `retreat`, `dash_dance`, `crouch`, `drop_platform`, `short_hop`, `full_hop` and `wavedash`.
- **Aerials:** `nair|fair|bair|uair|dair`, with `jump` (short, full or double), `dir` and `fastfall`. The executor L-cancels automatically.
- **Grounded attacks:** `jab`, `ftilt`, `utilt`, `dtilt`, `fsmash`, `usmash`, `dsmash` and `dash_attack`.
- **Grabs:** `grab` with `throw` (f, b, u or d).
- **Specials:** `shine` with `then` (jump, wavedash or hold), `laser` (short-hop laser by default), `side_b`, `up_b` (aimed at the ledge) and `recover` (character-aware: double jump, side-B, then up-B).
- **Defence:** `shield`, `roll`, `spot_dodge`, `ledge` (getup, roll, jump, attack or drop) and `tech`.

Reflexes take over without asking the LLM:

- **Hit:** survival DI toward the stage centre and up, then tech when landing is 4 or fewer frames away.
- **Grabbed:** mash.
- **Offstage below y=-15 (or far out):** `recover`.
- **Idle and offstage:** drift toward the stage.

## Logs

Each game writes a JSONL file to `replays/`, renamed at game end to `<replay>.p<port>.llm.jsonl`:

- A `game_start` record: model, characters, stage and the full system prompt.
- One `decision` record per decision: frame, the observation, the decision and its reason, latency, tokens, and any error.
- `dropped` records for live replies that were too stale.
- A `game_end` summary.

The exact fields are in `melee_llm/agents/llm_common.py`.

## Offline testing (no ISO)

```sh
uv run pytest -q     # rendering on 5 replays, events, macro timing on a toy sim, schema
uv run python tests/test_llm_layer.py      # prints renderings + frame-by-frame macro traces
uv run python scripts/llm_dryrun.py replays/sample-slippi-js-itemExport.slp llm_live:claude-haiku-4-5-20251001 --decisions 5 --realtime
```

`tests/fakesim.py` is a toy version of Fox's physics that checks inputs land on the intended frames; it is not Melee. Replay states ignore our inputs, so dry runs measure prompts, parsing and latency, not play quality.

## Measured (2026-11-13, Falco replay, JSON mode, effort=none)

Dry-run figures from before the first real games. Ratings from real games are on the [bench](bench.md).

| Model | Latency per decision | Prompt / completion tokens | Parsed |
|---|---|---|---|
| claude-haiku-4-5-20251001 | 0.95-1.2 s (≈60-70 frames) | ≈1.6k / 50-65 | 15/15 |
| claude-sonnet-5-5 | 1.8-2.4 s | ≈2.1k / 45-120 | 3/3 |
| gpt-6-luna | 1.6-2.6 s | ≈1.3k / 31-35 | 3/3 |
| haiku, `mode=tool` | 1.0-1.1 s | ≈2.3k / 80 | 2/2 |

- **Live Haiku at 60 fps:** reply latency was 61-73 frames (mean 69) and state staleness when the macro started was 69-107 frames (mean 85). `step()` took p99 0.5 ms.
- **Keep `effort=none`.** With `effort=low`, Haiku spent its whole 400-token budget thinking and returned nothing parseable, and Sonnet's answers were truncated about half the time.

## Open problems

- **Live latency.** One decision per second is too slow for neutral. Untried mitigations: macros that react to state while running, a local small model via `base_url`, or an LLM that sets a *policy* (for example "camp lasers, punish landings") for a fast scripted layer.
- **Prompt size.** About 900 of the tokens are the static system prompt. Prompt caching through the proxy is untested.
- **Macro fidelity.** Fox and Falco have the most detail. Other characters get generic up-B and neutral-B handling, and `UPB_REACH` and `JUMPSQUAT` are rough tables.
- **No platform awareness** in `approach` or `retreat`, and no edgeguard-specific macros (for example ledge-hog or drop-down bair).

## Needs the ISO to validate

This list predates the first real games, and no frame-by-frame check is recorded here. The macros were written against a toy sim, so these remain unverified in detail: frame timing (wavedash, shine jump-cancel, L-cancel, fast-fall), stick and tap-jump thresholds, the Fox and Falco special action IDs (`state._SPACIE_SPECIALS`, `SHINE_IDS`, `UPB_IDS`, taken from the action-state table, not observed), and recovery aiming, including whether the recovery reflex triggers too eagerly while edgeguarding.
