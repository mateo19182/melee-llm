# Learned bots (HAL, Phillip, MIMIC, Faynt, Reyn)

`melee_llm/bots/` wraps five published Melee policies, and our own m19182-yoshi, as `Agent`s, so they can play on the ladder and be steered by a coach.

```sh
uv run -m melee_llm.match --iso ~/melee.iso --p1 hal:MASTER --char1 FOX --p2 phillip:gm --char2 MARTH --mode fast
```

The spec after the colon picks the style or model:

| Spec | Meaning | Default |
| --- | --- | --- |
| `hal[:identity]` | Imitated player: a connect code from HAL's vocabulary (21,177 codes), or `PLATINUM`/`DIAMOND`/`MASTER` | `IBDW#0`, HAL's own default |
| `phillip[:model]` | ONNX model in `vendor/slippi-ai/models/` | `gm` |
| `mimic[:checkpoint]` | Directory in `vendor/MIMIC/hf_checkpoints/` | Picked from the character |
| `faynt[:variant]` | `10M-Arena`, `10M-Expert`, `10M-Base`, `75M-Arena` or `75M-Expert` | `10M-Arena` |
| `reyn[:command]` | Initial language command, e.g. `reyn:Be more aggressive.` | No command (unsteered) |
| `meleebot[:run]` | Run directory in `data/train/runs/` | `bc-6m-v1` |

## How it works

The main process loads no torch and no onnxruntime. Each bot runs `melee_llm/bots/server.py` under its own venv in `vendor/<repo>/.venv` and talks over stdin/stdout (`protocol.py`: a 4-byte length prefix, then a pickle).

- **Observation in.** The agent taps its Console (`ConsoleTap` in `agent.py`) and sends the child each frame's raw Slippi events. The child replays them through **its own** libmelee build and runs the bot's upstream observation code, so the bot never sees an approximated state. This matters because the libmelees differ: HAL needs fields from its fork that vladfi1's `melee` 0.47.6, which this project uses, drops. The parent raises an error if the child's frame number differs from the game's.
- **Controller out.** The child returns a full controller state in libmelee convention (sticks in [0, 1], analog L/R, names of pressed buttons), which the parent applies with `apply_controller`.
- **Steering.** After `setup`, `agent.steer` is a dict of every knob at its effective value. Change it at any time, e.g. `agent.steer["temperature"] = 0.9`; the change goes out with the next frame. `agent.applied_steer` holds what the bot confirmed. If the bot rejects a value, the step reports the error and the old settings stay.
- **Multiple bots** can share one console tap, so bot-vs-bot matches work.

To measure a bot without the ISO, stream a replay through it. `--steer-mid` changes knobs halfway through, and `--config` passes init options:

```sh
uv run python -m melee_llm.bots.bench hal replays/bots-slippi-js-rollbackFrameTest.slp --port 1 --frames 3000 \
    --steer-mid return_target=40 --steer-mid temperature=0.9
uv run python -m melee_llm.bots.bench faynt replays/bots-slippi-js-throwGrab.slp --port 2 --config device=cuda
```

This is open loop: the replay's own inputs stay in the game state. It measures latency, VRAM and pipeline health, not playing strength. `stick_tilted_frac` and `button_frac` are a quick check that the bot is not stuck at neutral. HAL follows its own recent inputs, which in open loop are the human's, so on a mostly idle replay it is nearly idle too.

## Bots

Latency is the per-frame round trip from parent to child and back, over 4,000 replay frames on the shared RTX 3090 (another process holds about 10.5 GB) while other agents loaded the CPU (load 3 to 15). VRAM is the child process's own allocation.

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

`runner.play` gives both bots the frame before reading either answer, so a frame with two bots costs about the slower one ([performance.md](performance.md)).

### Steering knobs and when they take effect

**HAL**
- `return_target`: the desired 60-frame discounted return. Accepts `"p90"` (19.98, the default), a float in [−20, 140], or `None` for unconditioned play. Higher asks for more aggressive, higher-reward play. Takes effect within 2 frames (the next replan).
- `temperature`: [0.8, 1.1]. Takes effect within 2 frames.
- `identity`: a connect code in the checkpoint vocabulary, or a rank. The model embeds it once per game, so a change waits for the **next game**. `applied_steer["identity_active"]` shows the identity in use. `info["identities_sample"]` lists some valid codes and `info["ranks"]` the ranks.

**Phillip** (all three are inputs to every ONNX step)
- `rating`: a skill-conditioning scalar. The models were trained around these defaults: `gm` 2500, `diamond` 1950, per-character v6.2 models 3200.
- `name`: a nametag from `info["names"]`. The per-character models know 32 to 54 names, e.g. Cody, Hax, Aklo, Zamu. RL models were tuned on `info["trained_names"]`. The multi-character tier models ignore `name`.
- `temperature`.

The model uses new values from its next decision, but the built-in delay means the controller shows the change 18 to 24 frames later. To change difficulty, swap between the tier models `bronze` … `super-gm`. That needs a new agent, i.e. a new game.

**MIMIC**: `temperature`, `top_k` and `top_p` apply on the next frame. Another player style or rank needs another checkpoint (`fox-master`, `fox-diamond`, `fox-platinum` on HF), and so a new game.

**Faynt**: `temperature` applies on the next frame. The variant (Base, Expert or Arena) is fixed for the game.

### Known limits

- **HAL**: ports 1 and 2 only. Upstream raises an error if the action seen on the next frame differs from the one HAL sent. Here the check is soft: `_Adapter` counts mismatches and logs the first 3 to stderr. Real games show a few harmless warnings during the countdown (frames −70, −69, −5).
- **Phillip**: its strength relies on the built-in reaction delay; it is not a zero-delay bot. It acts from frame −123; if a game starts later, its parser is never created. Only 12 models are downloaded. Others need `hf download vladfi/phillip-models <name>.onnx --local-dir vendor/slippi-ai/models`.
- **MIMIC**: `puff` and `ice_climbers` use an older schema that MIMIC's own model card calls incompatible with the current inference code; we did not test them. The bot picks its perspective from port order: it is p1 if its port is the lower one. Its `setup.sh` **downloads a Melee ISO**: never run it. The venv was built by hand instead.
- **Faynt**: its native step is host-bound, so CPU is the default device, and the 75M variants are for `paused` and `fast` modes only. The parser is slippi-ai HEAD; its `Game` schema matches Faynt's pinned commit `577965a`, but the libmelee is 0.47.6, not the 0.47.3 they pinned.
- **All bots**: they see only in-game frames and leave menus to `MenuHelper`. Old replays (Slippi < 3.0) take libmelee's manual-bookend path, which is untested. `watch` mode crashes them (see [closed-loop results](#closed-loop-results-2026-11-13-real-dolphin-and-iso)).

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

# Reyn: also uses ../slippi-ai's parser
git clone https://github.com/frisson-labs/Reyn && (cd Reyn && uv venv --python 3.12 \
  && uv pip install torch -e . -e ../slippi-ai huggingface_hub \
  && .venv/bin/hf download frisson-labs/Reyn-26C --local-dir model-files)
```

Init options go through `**config` on the agent class, e.g. `Faynt(character=..., device="cuda", compile=True)`, `HAL(compile=False, seed=0)`, `MIMIC(compile=False)` or `Phillip(seed=1)`.

## m19182-yoshi (our own, lane B)

`meleebot[:run]` plays the checkpoint `data/train/runs/<run>/last.pt` (default `bc-6m-v1`), trained by `train/meleebot` on 23k ranked Yoshi replays. It runs under `train/.venv` with cwd `train/`.

- **Model:** 5.4M causal transformer over the last 256 frames, recomputed every frame.
- **Inputs:** read from the raw Slippi bytes with the dataset's own field definitions (`meleebot.play.RawFrames`), not from libmelee's rounded fields. `replay_check` matched every field of 3 replays (54,909 frames) against the dataset.
- **Steering** (next frame): `delay` 0-12 (frames of pretended reaction delay, default 0), `rank` (UNKNOWN, PLATINUM, DIAMOND, MASTER, PRO; default MASTER), `win` (1, 0 or None), `temperature`.
- **Speed:** 2.1 ms per frame on the 3090. On the CPU with 8 threads, 6.3 ms p50 and 9.4 ms p95.
- **First game** (2026-11-14, Yoshi vs CPU 9 Fox on Battlefield, fast mode): lost 0-3. It took one stock and lost four, all below the stage, at 21-125%.
- **On stomped.dev:** `uv run python -m meleebot.stomped CHECKPOINT --url https://HOST/SECRET --lead 11` serves the [match socket](https://docs.stomped.dev/llms-full.txt): `/ping`, the signed WebSocket, picks Yoshi, reads the raw `.slp` stream and sends a 12-byte pad per frame.
  - Pads are aimed `lead` frames ahead, and the model plays with `delay = lead - 1`, the setting it was trained for. Without `--lead` it picks one from the measured round trip and raises it when the stream shows pads read late.
  - From this server the round trip to the arena (Ashburn) is ~135 ms, so lead 11 (10 frames behind). In the local arena with a simulated 135 ms trip, lead 10 lost 4% of pads and lead 9 nearly all.
  - `meleebot.stomped_arena REPLAY URL [--rtt-ms N]` streams a recorded game the way stomped does and counts pads that arrive before their frame is polled. `tests/test_stomped.py` checks the stream reader against the dataset builder (3 replays, every field equal).
- **Setup:** `cd train && uv sync`. On a machine without NVIDIA, `uv venv && uv pip install --torch-backend cpu torch numpy "melee>=0.47.6" "peppi-py>=0.8"` avoids the CUDA wheels. Copy the run's `last.pt` (21 MB).

## Reyn (language-steerable)

[frisson-labs/Reyn-26C](https://huggingface.co/frisson-labs/Reyn-26C) (MIT, code [frisson-labs/Reyn](https://github.com/frisson-labs/Reyn) @ `93fa527`) is a 33M-parameter policy for all 26 characters, from the Faynt authors, steered by English commands. It is the default body of the LLM coach ([coach.md](coach.md)). Zero added delay, 256-frame KV cache, one step per frame, same observation parser as Faynt.

- **Steering**: `steer["command"]` is a phrase or `None` (clear); `steer["temperature"]`. A changed phrase goes through Reyn's neural router (`model.say`) inside the child on the next frame. `applied_steer["reply"]` is the router's answer (`outcome`, `row`, `name`, `score`) and `applied_steer["active"]` the command row actually held. An `abstain` keeps the previous command. The command survives the next game's reset.
- **Commands**: `vendor/Reyn/docs/commands.md` lists about 100 general meanings and `commands.csv` 104 character specials; `melee_llm.agents.coach.reyn_commands()` turns them into a per-character, per-stage menu.
- **Router**: about 3 ms per `say` on CUDA (10-20 ms on a loaded CPU), only when the command changes. It almost never abstains: `xyzzy nonsense` routes to "Fox Illusion" at 0.96. Only send phrases from the menu.
- **Fast step** (`melee_llm/bots/reyn_step.py`): upstream `Reyn.predict` took 10 ms p50 on a quiet CPU, 20-40 ms with four games in parallel and 26 ms on CUDA. `FastStep` runs the same weights as one CUDA-graph replay per frame, about 1.7 ms. `scripts/reyn_agreement.py` checks it against upstream: 100% identical actions on 2,000 frames each for four commands, on CUDA and CPU. Only the random stream differs, not the distribution.
- **Config**: `device` (default `cuda` when available, else `cpu`), `cuda_graph` (default true), `fast` (false runs upstream `Reyn.predict`, for comparison), `threads` (CPU, default 4), `seed`.
- **Latency** (round trip, CUDA graph, machine load 20-40): 1.9 / 2.2 / 2.4 ms p50/p95/p99 on 3,000 replay frames; in real lockstep games against CPU 9 (two games in parallel), 2.2 / 3.7 / 4.6 ms, 58-59 fps, coached or not. On the CPU the fast step is no faster than upstream (10 ms p50; 1 thread 7.6 ms but p99 22 ms under load). Startup about 4 s. 524 MiB VRAM.

## Closed-loop results (2026-11-13, real Dolphin and ISO)

| Match | Mode | Result | Frames / wall time |
| --- | --- | --- | --- |
| HAL (MASTER, Fox) vs CPU 9 Falco, Battlefield | fast | HAL 4-stocks, 0% taken | 3272 / 19 s |
| HAL vs CPU 9 | lockstep | HAL 4-stocks, 0% taken | 3432 / 59 s (≈58 fps) |
| HAL (Fox) vs Phillip gm (Falco) | lockstep | Phillip wins, 1 stock left | 8024 / 136 s (≈59 fps) |
| MIMIC (Fox) vs CPU 9 | fast | MIMIC 4-stocks, 0% taken | 4627 / 36 s |
| Faynt 10M (Fox) vs CPU 9 | fast | Faynt 4-stocks, 1% taken | 11518 / 136 s (CPU-bound) |

- **Use `lockstep` (or `fast`) for learned bots.**
- **`watch` mode crashes the bots:** two runs ended about 20 s in with `EnetDisconnected`; the cause is not investigated. In `watch`, Dolphin never waits for our input.
