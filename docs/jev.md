# Jev (TypeSafe System One) as player and coach

[Jev](https://typesafe.ai/blog/introducing-system-one-models-and-jev) is a "System One" model: structured state and typed questions in, typed answers with calibrated probabilities out, no free text. Here it replaces the LLM in two places: picking the next macro (`jev_live`, `jev_paused`) and picking Reyn's command (`coach_jev`).

This page covers the client, its measured speed and cost, and the first pilot. Rated results are on the [bench](bench.md), and the [coach deep-dive](coach-deepdive.md) explains why Jev coaches best.

```sh
uv run -m melee_llm.match --iso ~/melee.iso --p1 jev_live --p2 cpu:5 --mode lockstep
uv run -m melee_llm.match --iso ~/melee.iso --p1 "jev_paused:,interval=30" --p2 cpu:5 --mode paused
uv run -m melee_llm.match --iso ~/melee.iso --p1 "coach_jev:,interval=300" --p2 cpu:9 --mode lockstep
uv run pytest -q tests/test_jev.py          # offline
uv run python tests/test_jev_bench.py       # live latency/throughput, about $0.02
```

Specs (the text after `:` is `[model][,key=value...]`; leave the model empty for `jev-latest`, keep the colon):

- `jev_live[:model][,interval=15,max_stale=60,top_k=5,params=all|none,shuffle=1,timeout=1.5,retries=1]`
- `jev_paused[:model][,interval=30,...]` (timeout 5 s, 3 retries)
- `coach_jev[:model][,interval=60,command=<id>,top_k=5,shuffle=1,timeout=3,history=4]` (Reyn body only)

The key is `TYPESAFE_API_KEY` from the environment or `~/.secrets/typesafe.env`; it is never logged.

## API

`POST https://api.typesafe.ai/v1/systemone`, documented at [docs.typesafe.ai](https://docs.typesafe.ai/models). What matters here:

- A request carries a state and named typed questions, all answered in parallel. We use `choice` (up to 255 options, each with a description) and `noul` (a yes/no probability).
- The price is $0.042 per million input tokens, output free. The context is 64k per request, 32k per question.
- Rate limits are per organisation; 429 and 529 mean back off.

Our client is `melee_llm/jev.py` (httpx, no SDK dependency). It retries within a total deadline, so a live player never waits on backoff, and returns errors as a failed reply.

## Design

- **Players** (`agents/jev_player.py`) subclass `LiveLLM` and `PausedLLM`, so the executor, reflexes, rendered state, decision history and the `.llm.jsonl` log are the same. One request asks `action` (a choice over all 33 macros, each with a one-line meaning) and, speculatively, the macro's parameters; this fan-out adds about 600 tokens and no measurable latency. Options are shuffled per call because Jev leans toward the first option.
- **Coach** (`agents/jev_coach.py`) subclasses `CoachedBot`: one choice over Reyn's command ids plus `keep` and `none` (108 options for Fox on Battlefield). The prompt state is the same as `coach:`'s.
- **Logs**: same records as `llm_*` and `coach:`, so the web UI's live panel shows them. `reason`/`why` holds the top probabilities, and each decision adds `probabilities`, `confidence`, `action_p`, `usd` and `attempts`.

## Measured (2026-11-14, from m19182 in Spain)

| Request | Options | Latency p50 / p90 | Input tokens | Cost per call |
|---|---|---|---|---|
| player, action only | 33 | 154 / 185 ms | 1,357 | $0.000057 |
| player, action + 7 parameter questions | 58 | 153 / 202 ms | 1,944 | $0.000082 |
| coach, Reyn menu | 108 | 161 / 200 ms | 2,396 | $0.000101 |

- **Network:** the TLS connect takes 22-41 ms, so most of the latency is the model.
- **Throughput** (player requests): 6.3 decisions/s sequentially, 21 per second with 4 in flight, 28 with 8 and 49 with 16. There were no 429s at 16 in flight, and p90 stayed under 290 ms.
- **In games:** no errors across 211 benchmark calls and 2,131 in-game calls. Live latency was 6-11 frames (Haiku: 68), and staleness when the macro started was 13-21 frames (Haiku: 75-80).
- **Cost per game:**
  - `jev_live`: 140-280 decisions, 0.22-0.64 M input tokens, $0.009-0.027.
  - `coach_jev` at interval 300: about 43 k tokens, $0.002. At interval 60: about 195 k tokens, $0.008.
  - For comparison at list price: `llm_live` Haiku made 89-137 decisions for about $0.17-0.28 per game, and `coach:haiku` cost about $0.035.

## Pilot (2026-11-14)

Fox vs Fox, Battlefield and Final Destination, `lockstep` on :98, 28 games, run before the bench. Stock difference is mean ± SE.

| P1 | vs | n | W-L | Stock diff |
|---|---|---|---|---|
| `jev_live` | CPU 5 | 4 | 3-1 | +0.75 ± 0.63 |
| `llm_live` Haiku 4.5 | CPU 5 | 2 | 0-2 | -3.00 ± 0 |
| `jev_live` | CPU 9 | 4 | 1-3 | -1.50 ± 1.32 |
| `llm_live` Haiku 4.5 | CPU 9 | 2 | 0-2 | -4.00 ± 0 |
| Reyn uncoached | CPU 9 | 4 | 4-0 | +2.25 ± 0.48 |
| `coach:haiku`, interval 300 | CPU 9 | 3 | 3-0 | +3.33 ± 0.33 |
| `coach_jev`, interval 300 | CPU 9 | 5 | 5-0 | +3.60 ± 0.24 |
| `coach_jev`, interval 60 | CPU 9 | 2 | 2-0 | +4.00 ± 0 |

- **Jev player vs Haiku player:** `jev_live` beat Haiku on stock difference (8 games vs 4, Mann-Whitney p = 0.046), not significantly on wins (Fisher p = 0.21). Jev decides about 7 times faster and plays a more active mix: lasers in 5-7% of frames vs 0.1%, aerials in 4-5% vs 0.3%, and about a third of its picks are `shine`.
- **Coach:** `coach_jev` had a larger stock difference than uncoached Reyn (p = 0.05, n = 5 vs 4) and was indistinguishable from `coach:haiku` (p = 0.61). Jev mostly holds one command: it changed command on 12 of 85 calls, Haiku on 26 of 49. Its favourites were `kill_now`, `approach` and `stock_protection`, and Reyn's router abstained on 11 of its picks.
- **Caveats:**
  - The machine was overloaded, so lockstep games ran at 10-57 fps, not 60. The `jev_live` vs CPU 9 games ran at about 10 fps and the Haiku games at about 56, which gives Jev more game time per decision: the player comparison is biased toward Jev against CPU 9, less so against CPU 5 (35-54 fps).
  - Two games hit the 20-minute harness timeout and are excluded. Three Reyn CUDA out-of-memory failures were rerun.
  - With n = 2-5 per cell, these are directions, not results.

## Issues and next steps

- **Action confidence is low:** the mean is 0.26-0.32 and the top option has p ≈ 0.3-0.5. Jev reads the rendered text literally. For the player, a state with named fields (distance bucket, phase, "opponent in endlag: yes/no") computed in code is still untried; for the coach, `features=1` made no measurable difference ([deep-dive](coach-deepdive.md)).
- **Use the probabilities:** sample from them or apply thresholds (for example only `fsmash` if p > 0.5), or ask Nouls like "is the opponent punishable now?" and route in code.
