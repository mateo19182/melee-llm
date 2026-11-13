# Learned bots (HAL, Phillip, MIMIC, Faynt)

`melee_llm/bots/` wraps four published Melee policies as `Agent`s, so they can play on the ladder and a coach can steer them.

```sh
uv run match.py --iso ~/melee.iso --p1 hal:MASTER --char1 FOX --p2 phillip:gm --char2 MARTH --mode fast
```

The spec after the colon picks the style or model. Leave it out to use the default:

| Spec | Meaning | Default |
| --- | --- | --- |
| `hal[:identity]` | Imitated player: a connect code from HAL's vocabulary (21,177 codes), or `PLATINUM`/`DIAMOND`/`MASTER` | `IBDW#0`, HAL's own default |
| `phillip[:model]` | ONNX model in `vendor/slippi-ai/models/` | `gm` |
| `mimic[:checkpoint]` | Directory in `vendor/MIMIC/hf_checkpoints/` | Picked from the character |
| `faynt[:variant]` | `10M-Arena`, `10M-Expert`, `10M-Base`, `75M-Arena` or `75M-Expert` | `10M-Arena` |

## How it works

The main process stays light: it loads no torch and no onnxruntime. Each bot runs `melee_llm/bots/server.py` under its own venv in `vendor/<repo>/.venv` and talks over stdin/stdout. The format is defined in `protocol.py`: a 4-byte length prefix, then a pickle.

- **Observation in.** On `setup`, the agent taps its Console. It wraps `controller._console._slippstream.dispatch` (`ConsoleTap` in `agent.py`), so it gets a copy of every raw Slippi event. On each `step`, it sends the child the events from the last frame. The child replays them through **its own** libmelee build into a GameState, then runs the bot's upstream observation code on it. This matters because the libmelees differ. HAL needs fields from its libmelee fork (`to_canonical_dict`: state flags, `misc_as`, L-cancel status, hurtbox state). vladfi1's `melee` 0.47.6, which this project uses, drops those fields. So the bot never sees an approximated state. The child also returns the frame number, and the parent raises an error if it differs from the game's frame.
- **Controller out.** The child returns a full controller state in libmelee convention: sticks in [0, 1], analog L/R, and the names of pressed buttons. The parent applies it with `apply_controller`. The parent's Controller keeps libmelee's default analog fix, which matches the wire conversion each bot expects.
- **Steering.** After `setup`, `agent.steer` is a dict holding every knob at its effective value. Change it whenever you like, e.g. `agent.steer["temperature"] = 0.9`. The change goes out with the next frame. `agent.applied_steer` holds what the bot confirmed. If the bot rejects a value, the step reports the error and the old settings stay.
- **Multiple bots.** Several bots can share one console tap, so a bot-vs-bot match works. Tested with HAL vs Phillip and MIMIC vs Faynt on one replay stream.

Measure a bot without the ISO by streaming a replay through it. Use `--steer-mid` to change knobs halfway through, and `--config` to pass init options:

```sh
uv run python -m melee_llm.bots.bench hal replays/bots-slippi-js-rollbackFrameTest.slp --port 1 --frames 3000 \
    --steer-mid return_target=40 --steer-mid temperature=0.9
uv run python -m melee_llm.bots.bench faynt replays/bots-slippi-js-throwGrab.slp --port 2 --config device=cuda
```

This is open loop: the replay's own inputs stay in the game state. It measures latency, VRAM and pipeline health, not playing strength. It also reports `stick_tilted_frac` and `button_frac`, a quick check that the bot is not stuck at neutral. HAL follows its own recent inputs, which in open loop are the human's. On the mostly idle `throwGrab` Falco it is therefore nearly idle too.

## Bots

Latency below is the parent→child→parent round trip per frame. It comes from 4,000 replay frames on the shared RTX 3090 (another process holds about 10.5 GB) while other agents loaded the CPU (load 3 to 15). "Model" is the time inside the child. VRAM is the child process's own allocation.

| | HAL | Phillip | MIMIC | Faynt |
| --- | --- | --- | --- | --- |
| Source | [ericyuegu/hal](https://github.com/ericyuegu/hal) @ `37045d9` | [vladfi1/slippi-ai](https://github.com/vladfi1/slippi-ai) @ `5ada33e` | [erickfm/MIMIC](https://github.com/erickfm/MIMIC) @ `bdfb629` | [Na00s/Faynt-Tournament](https://github.com/Na00s/Faynt-Tournament) @ `d209617`, plus the HF remote code |
| Code license | **None** (the GitHub repo has no LICENSE file, so all rights are reserved). Used locally, not redistributed | MIT | MIT | MIT. The Slippi Dolphin patch in that repo is GPL-2.0+; we do not use it |
| Weights | HF `ericyuegu/hal-base-250m-rc`, file `hal-250m.hal`, 0.99 GB, MIT | HF `vladfi/phillip-models` (ONNX), MIT. We downloaded 12 of about 190 models (1.8 GB) | HF `erickfm/MIMIC`, MIT. Downloaded: fox, fox-master, falco, marth, sheik, cptfalcon, puff, coach/fox | HF `frisson-labs/Faynt-*`, MIT. 5 of the 6 variants, all but 75M-Base (0.7 GB) |
| Architecture | 247M transformer, 256-frame KV cache, predicts 4-frame action chunks, replans every 2 frames | Recurrent policy; most models are RL-tuned; one decision per frame | 20M transformer over a 180-frame window, recomputed every frame | 10M or 75M transformer, 256-frame ring cache, one step per frame |
| Characters | Any. Trained on all characters in ranked data plus pro replays | Per model: `gm`, `super-gm`, `diamond`, `master`, `plat`, `gold`, `silver` and `bronze` each cover 18 characters. Per-character models such as `fox_d21_v6.2` | One checkpoint per character: Fox, Falco, Marth, Sheik, Falcon and Puff are downloaded. Luigi and Peach exist on HF | 26 characters in one checkpoint. Its RL fine-tuning is Fox only |
| Ports | **Must be ports 1 and 2**: HAL's schema is fixed | Any | Any 2 players | Any 2 players |
| Added delay | 0 | **18 to 24 frames, by design**: a built-in reaction time (`delay_frames` in `info`) | 0 | 0 |
| VRAM | 992 MiB | 822 MiB (`gm`), 532 MiB (per-character) | 468 to 488 MiB | 0 by default (runs on the CPU). 364 MiB (10M) or 646 MiB (75M) on CUDA |
| Latency p50 / p95 / p99 (ms) | 4.35 / 4.7 / 4.9, max 6.2 on replan frames; the other frames take about 0.3 | `gm` 2.2 / 2.9 / 3.5; `fox_d21_v6.2` 2.5 / 3.4 / 4.6; `marth_d21_v6.2` 1.8 / 2.1 / 2.4 | `fox` 3.4 / 5.0 / 7.0; `fox-master` 2.5 / 2.8 / 3.2. The countdown frame −123 takes about 120 because of CUDA-graph setup | 10M on CPU (8 threads): 8.1 / 10.3 / 11.5, max 15. 10M on CUDA: about 16. 75M: about 23 |
| Startup | about 12 s (CUDA-graph capture) | about 2 s | 5 to 13 s (torch.compile with CUDA graphs) | about 3 s |
| Steering | `identity`, `return_target`, `temperature` | `name`, `rating`, `temperature` | `temperature`, `top_k`, `top_p` | `temperature` |

Two bots in one match step one after the other in `runner.play`. HAL plus Phillip takes 6.3 ms p50 and 7.6 ms p99 per frame. MIMIC plus Faynt takes 12.4 ms p50 and 16.6 ms p99, which is too slow for `watch` mode.

### Steering knobs and when they take effect

**HAL**
- `return_target`: the desired 60-frame discounted return. Accepts `"p90"` (19.98, the default), a float in [−20, 140], or `None` for unconditioned play. A higher value asks for more aggressive, higher-reward play. HAL reads it at every replan, so it takes effect within 2 frames.
- `temperature`: [0.8, 1.1]. Takes effect within 2 frames.
- `identity`: a connect code in the checkpoint vocabulary, or a rank. The model embeds it once per KV stream, so a change waits for the **next game**. `applied_steer["identity_active"]` shows the identity in use. Changing it mid-game would mean resetting HAL's context. `info["identities_sample"]` lists some valid codes, and `info["ranks"]` lists the ranks.

**Phillip** (all three are inputs to every ONNX step)
- `rating`: a skill-conditioning scalar. The models were trained around these defaults: `gm` 2500, `diamond` 1950, per-character v6.2 models 3200.
- `name`: a nametag from `info["names"]`. The per-character models know 32 to 54 names, e.g. Cody, Hax, Aklo, Zamu. RL models were tuned on `info["trained_names"]`. The multi-character tier models ignore `name`.
- `temperature`.

The model uses the new values from its next decision, but because of Phillip's built-in delay, the controller shows the change 18 to 24 frames later. To change difficulty, swap between the tier models `bronze` … `super-gm`. Swapping needs a new agent, i.e. a new game.

**MIMIC**: `temperature`, `top_k` and `top_p` apply on the next frame. A different player style or rank needs another checkpoint (`fox-master`, `fox-diamond`, `fox-platinum` on HF), and so a new game.

**Faynt**: `temperature` applies on the next frame. The variant (Base, Expert or Arena) is fixed for the game.

### Known limits

- **HAL**: ports 1 and 2 only. Upstream raises an error if the action seen on the next frame differs from the one HAL sent. Here that check is soft: `_Adapter` counts mismatches and logs the first 3 to stderr. Mismatches can only happen in live play, which is untested; see below.
- **Phillip**: its strength relies on the built-in 18 to 24 frame reaction delay; it is not a zero-delay bot. It acts from frame −123; if a game starts later than that, its parser is never created. Only 12 models are downloaded. Others need `hf download vladfi/phillip-models <name>.onnx --local-dir vendor/slippi-ai/models`.
- **MIMIC**: `puff` and `ice_climbers` use an older schema. MIMIC's own model card says they are incompatible with the current inference code; we did not test them. The bot picks its perspective from port order: it is p1 if its port is the lower one. Its setup script `setup.sh` **downloads a Melee ISO**: never run it. The venv was built by hand instead.
- **Faynt**: its native step spends its time on the host, with about 80 small tensors and many validation syncs per frame. So CPU is the default device, and the 75M variants are for `paused` and `fast` modes only. The parser is slippi-ai HEAD; its `Game` schema matches Faynt's pinned commit `577965a` (checked with `git diff`), but the libmelee is 0.47.6, not the 0.47.3 they pinned.
- **All bots**: they only see in-game frames and leave menus to `MenuHelper`. Old replays (Slippi < 3.0) take libmelee's manual-bookend path, which we have not tested.

### Not verified (no ISO on this machine)

These have only been tested on replays, open loop:
- Closed-loop play in Dolphin.
- Dolphin's base64 event path. The tap decodes it, but only the replay (bytes) path has run.
- Whether the executed controller matches what a bot sent. This matters most for HAL.
- Real-time timing in `watch` mode with Dolphin using CPU.
- Playing strength.

## Setup

Everything lives under `vendor/` (gitignored). Each bot has its own venv; never add these dependencies to the main `pyproject.toml`.

```sh
cd vendor
git clone https://github.com/ericyuegu/hal && git clone https://github.com/vladfi1/slippi-ai \
  && git clone https://github.com/erickfm/MIMIC && git clone https://github.com/Na00s/Faynt-Tournament

# HAL: Python 3.14. The 3.14.0a6 pre-release segfaults while building pyenet, so pin a stable one.
uv python install 3.14 && (cd hal && uv sync --python 3.14.3 \
  && uv run hf download ericyuegu/hal-base-250m-rc hal-250m.hal --local-dir weights)

# Phillip
(cd slippi-ai && uv venv --python 3.12 && uv pip install -e ".[onnx-cuda]" huggingface_hub \
  && .venv/bin/hf download vladfi/phillip-models gm.onnx fox_d21_v6.2.onnx --local-dir models)

# MIMIC (do NOT run setup.sh)
(cd MIMIC && uv venv --python 3.12 && uv pip install torch numpy pandas pyarrow "melee==0.45.1" huggingface_hub \
  && .venv/bin/hf download erickfm/MIMIC --local-dir hf_checkpoints --include "fox/*" "fox-master/*" "marth/*")

# Faynt: installs slippi-ai from ../slippi-ai for its libmelee parser
(cd Faynt-Tournament && uv venv --python 3.12 \
  && uv pip install torch "transformers>=4.57,<5" safetensors PyYAML huggingface_hub -e ../slippi-ai \
  && .venv/bin/hf download frisson-labs/Faynt-10M-Arena --local-dir weights/Faynt-10M-Arena --exclude checkpoint.pt "*.png")
```

Init options go through `**config` on the agent class, e.g. `Faynt(character=..., device="cuda", compile=True)`, `HAL(compile=False, seed=0)`, `MIMIC(compile=False)` or `Phillip(seed=1)`.

## Related

[frisson-labs/Reyn-26C](https://huggingface.co/frisson-labs/Reyn-26C) (MIT) is a **language-steerable** policy for all 26 characters. It takes instructions such as "be more aggressive", "go to the top platform" or "fire fox", and it reports that 81.8% of its test cases met their command-following target. It fits the LLM-coach plan directly. It has not been integrated yet; it would follow the same pattern as Faynt.

## Closed-loop results (2026-11-13, real Dolphin and ISO)

| Match | Mode | Result | Frames / wall time |
| --- | --- | --- | --- |
| HAL (MASTER, Fox) vs CPU 9 Falco, Battlefield | fast | HAL 4-stocks, 0% taken | 3272 / 19 s |
| HAL vs CPU 9 | lockstep | HAL 4-stocks, 0% taken | 3432 / 59 s (≈58 fps) |
| HAL (Fox) vs Phillip gm (Falco) | lockstep | Phillip wins, 1 stock left | 8024 / 136 s (≈59 fps) |
| MIMIC (Fox) vs CPU 9 | fast | MIMIC 4-stocks, 0% taken | 4627 / 36 s |
| Faynt 10M (Fox) vs CPU 9 | fast | Faynt 4-stocks, 1% taken | 11518 / 136 s (CPU-bound) |

- **Use `lockstep` (or `fast`) for learned bots.**
- **`watch` mode crashes the bots:** two runs ended about 20 s in with `EnetDisconnected`, and the cause hasn't been investigated. In `watch`, Dolphin never waits for our input.
- **HAL mismatch warnings:** HAL reports a few "executed action differs" warnings during the countdown (frames −70, −69, −5). They are harmless.
