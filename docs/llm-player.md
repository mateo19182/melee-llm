# LLM player

An LLM picks **macro-actions** from structured state, and a frame-level executor turns them into controller inputs. The LLM never presses buttons. This follows what worked in earlier projects (reflex, LLM Colosseum): give the model structured state, have it choose macros, keep the motor layer deterministic, and favour small fast models.

```sh
uv run -m melee_llm.match --iso ~/melee.iso --mode paused --p1 llm_paused:claude-haiku-4-5-20251001 --p2 cpu:3
uv run -m melee_llm.match --iso ~/melee.iso --p1 llm_live:claude-haiku-4-5-20251001,interval=20 --p2 cpu:3
```

The spec format is `<kind>:<model>[,key=value...]`. Keys: `interval` (frames between forced decisions, default 30), `history` (past decisions in the prompt, default 6), `mode` (`json`, the default, or `tool` for function calling), `effort` (`reasoning_effort`, default `none`), `base_url` (a local vLLM or llama.cpp server), `timeout`, `reflexes` and `max_stale` (live only). `MELEE_LLM_BASE_URL` and `MELEE_LLM_API_KEY` override the CLIProxy defaults. Otherwise the key comes from `CLIPROXY_API_KEY` in `~/.hermes/.env` and is never logged.

## Modules

| File | Role |
|---|---|
| `melee_llm/state.py` | `observe(gs, port, opp)` builds a JSON-able dict. `render(obs, events)` turns it into about 100-170 tokens of text. `EventTracker` summarises hits, stocks, ledge grabs, techs, grabs and shield breaks. It also provides the actionability, hitstun and stage geometry helpers. |
| `melee_llm/actions.py` | Macros as generators: each `yield` is the next frame's `Input` and each `return` is the outcome. `Executor` runs one macro at a time, writes only input diffs to the controller, enforces `max_frames` and runs reflexes. `ACTIONS` is the registry, `tool_schema()` the single `act` tool and `RecordingController` a stand-in controller for tests. |
| `melee_llm/llm.py` | OpenAI-compatible client: tool or JSON mode, tolerant JSON parsing, latency and token accounting. Errors come back as failed `Reply`s instead of raising. |
| `melee_llm/agents/llm_common.py` | Shared code for both agents: system prompt (Melee basics, stage geometry, character tips, action list), decision history and the JSONL log. |
| `melee_llm/agents/llm_paused.py` | `PausedLLM` decides when the macro ends, or every `interval` frames if the macro is interruptible. It blocks while thinking, so use it only in `--mode paused`. |
| `melee_llm/agents/llm_live.py` | `LiveLLM` asks a background thread, and `step()` never blocks. Until a reply arrives the executor keeps running the last macro or a default (dash dance, or shield when the opponent is close). Replies older than `max_stale` frames are dropped. |

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

The list covers movement, aerials, grounded attacks, grabs, specials (spacie shine, laser and recovery included) and defence:

- `wait`, `approach`, `retreat`, `dash_dance`, `crouch`, `drop_platform`, `short_hop`, `full_hop` and `wavedash`.
- `nair|fair|bair|uair|dair`, with `jump` (short, full or double), `dir` and `fastfall`. The executor L-cancels automatically.
- `jab`, `ftilt`, `utilt`, `dtilt`, `fsmash`, `usmash`, `dsmash` and `dash_attack`.
- `grab` with `throw` (f, b, u or d).
- `shine` with `then` (jump, wavedash or hold), `laser` (short-hop laser by default), `side_b`, `up_b` (aimed at the ledge) and `recover`. `recover` is character-aware: double jump, then side-B for spacies near ledge height, then up-B with a per-character reach estimate.
- `shield`, `roll`, `spot_dodge`, `ledge` (getup, roll, jump, attack or drop) and `tech`.

Reflexes take over without asking the LLM:

- **Hit:** survival DI toward the stage centre and up, then tech when landing is 4 or fewer frames away.
- **Grabbed:** mash.
- **Offstage below y=-15 (or far out):** `recover`.
- **Idle and offstage:** drift toward the stage.

## Logs

Each game writes a JSONL file to `replays/`, renamed at game end to `<replay>.p<port>.llm.jsonl`. It contains:

- A `game_start` record: model, characters, stage and the full system prompt.
- One `decision` record per decision: frame, asked_frame, obs_text, obs, decision, reason, latency_s, prompt and completion tokens, reply mode, error and the raw text when parsing failed. Paused records add `think_s`. Live records add `latency_frames` and `stale_frames`.
- `dropped` records for live replies that were too stale.
- A `game_end` summary.

## Offline testing (no ISO)

```sh
uv run pytest -q     # rendering on 5 replays, events, macro timing on a toy sim, schema
uv run python tests/test_llm_layer.py      # prints renderings + frame-by-frame macro traces
uv run python scripts/llm_dryrun.py replays/sample-slippi-js-itemExport.slp llm_live:claude-haiku-4-5-20251001 --decisions 5 --realtime
```

`tests/fakesim.py` is a toy version of Fox's physics that reacts to inputs: jumpsquat, short and full hop, fast-fall, aerials with L-cancel, airdodge into wavedash, shield, roll, grab, shine jump-cancel and ledge. It checks that inputs land on the intended frames. It is not Melee. Replay states ignore our inputs, so dry runs measure prompts, parsing and latency, not play quality.

## Measured (2026-11-13, Falco replay, JSON mode, effort=none)

| Model | Latency per decision | Prompt / completion tokens | Parsed |
|---|---|---|---|
| claude-haiku-4-5-20251001 | 0.95-1.2 s (≈60-70 frames) | ≈1.6k / 50-65 | 15/15 |
| claude-sonnet-5-5 | 1.8-2.4 s | ≈2.1k / 45-120 | 3/3 |
| gpt-6-luna | 1.6-2.6 s | ≈1.3k / 31-35 | 3/3 |
| haiku, `mode=tool` | 1.0-1.1 s | ≈2.3k / 80 | 2/2 |

- **Live Haiku at 60 fps:** reply latency was 61-73 frames (mean 69) and state staleness when the macro started was 69-107 frames (mean 85). `step()` took p99 0.5 ms.
- **`effort=low`:** Haiku spent its whole 400-token budget thinking and returned nothing parseable, and Sonnet's answers were truncated about half the time. Keep `effort=none`.

## Open problems

- **Live latency.** One decision per second is too slow for neutral. Mitigations: make macros more conditional (react to state while running), use a local small model via `base_url`, or have the LLM set a *policy* (for example "camp lasers, punish landings") that a fast scripted layer executes. The paused mode works but plays in slow motion, about 1 s of thinking per 0.3-1 s of game.
- **Prompt size.** About 900 of the tokens are the static system prompt. Prompt caching through the proxy is untested.
- **Macro fidelity.** Fox and Falco have the most detail. Other characters get generic up-B and neutral-B handling, and `UPB_REACH` and `JUMPSQUAT` are rough tables.
- **No platform awareness** in `approach` or `retreat`, and no edgeguard-specific macros (for example ledge-hog or drop-down bair).

## Needs the ISO to validate

1. **Frame timing.** The wavedash airdodge press on the last jumpsquat frame, shine jump-cancel on frame 3 or 4, L-cancel timing from `frames_to_land`, and fast-fall triggering.
2. **Stick and tap-jump thresholds.** Tilt vs smash magnitudes (utilt uses 0.5 up to avoid tap-jump), the soft turnaround (0.5), and roll and spot dodge out of a 1-frame shield.
3. **Fox and Falco special action IDs** (`state._SPACIE_SPECIALS`, `SHINE_IDS`, `UPB_IDS`). These are taken from the spacie action-state table, not observed.
4. **Recovery behaviour.** Firefox angle aiming at the ledge, illusion or phantasm distance thresholds, and whether the recovery reflex triggers too eagerly while edgeguarding.
5. **Paused mode.** Dolphin `blocking_input` must tolerate step() calls of several seconds, and the JSONL rename must match the Slippi `.slp`.
