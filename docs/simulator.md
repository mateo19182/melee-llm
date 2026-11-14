# Decomp-based simulator (melee-sim-light)

[kyhavlov/melee-sim-light](https://github.com/kyhavlov/melee-sim-light) runs Melee's gameplay code from the [doldecomp/melee](https://github.com/doldecomp/melee) decompilation as a C library. It has no emulator, no rendering and no menus. It is a batched Python API with numpy outputs, and it supports save/restore of a whole game.

slippi-ai already ships a bridge to it (`slippi_ai/sim_env`). Phillip's training most likely runs on it: the slippi-ai README thanks Enzyme for a "decomp-based simulator that runs melee even faster than dolphin".

We tested it on 2026-11-14 with upstream commit `eea7b5fb`. It has **no license file**, so we use it locally and don't redistribute it. Its game data is extracted from our ISO.

## Results

**Exactness.** We ran the simulator's own strict validator on 300 random Dolphin replays of ours:
- **287 matched frame for frame**: 2.34M frames, zero mismatches. The sample covered bench, LLM players, coach pilots, learned bots and CPU 9.
- **13 could not be read.** All were replays Dolphin never finalized: the raw length was 0 and there was no Game End, from games that were stopped. None was a mismatch.
- The validator feeds each replay's recorded inputs and RNG observations. So it shows the game logic is identical. It does not show that a freely running simulated game stays in RNG lockstep with Dolphin.
- Upstream's own suite has 524 exact recordings across 148 character/stage pairs, CPU-input replays included.

**Speed.**
- **Simulator alone:** about 17,500 frames/s for one game on one thread, on this machine at load average 45. That is about 100× our headless Dolphin (~170 frames/s for HAL vs CPU 9).
- **Validator:** ran 2.3M frames in 30 s on 12 workers.
- **Upstream's claim:** about 120k frames/s per core, on a quiet Ryzen 9950X3D with batch 256.

**Phillip vs Phillip in the simulator.** slippi-ai's own evaluator played `gm.onnx` vs `gold.onnx` (Fox ditto) to completion: gm won 4-0 on Fountain of Dreams in 5,248 frames.
- Per-frame time: the simulator plus observation conversion took 0.66 ms, and each policy took 8.6 ms.
- That is batch-1 ONNX on a shared, busy GPU. The policy is the bottleneck, not the game.
- Our ONNX exports have a fixed batch of 1. Running many games at once needs batched exports.

## Gaps

- **slippi-ai bug.** slippi-ai @ `5ada33e` looks players up by `present`, which melee_sim clears for an eliminated player. Every game that ends on stocks crashes. `scripts/sim_phillip_eval.py` patches the two lookups at runtime, so the vendored repo stays untouched.
- **No CPU opponents.** The public API exposes no CPU players. CPU-level baselines stay on Dolphin.
- **Rules.** Supported matches are UCF, no items, and frozen Pokémon Stadium, which is what Slippi plays anyway.
- **Not wired to our agents yet.** Our agents consume libmelee `GameState` from the Slippi stream. The simulator returns its own observation structs, and slippi-ai's `sim_env/observations.py` converts them to slippi-ai's `Game`. Bot-writer bots, LLM players and our bot wrappers would need an adapter from observation to libmelee `GameState`.

## Where it would help here

- **Bot-writer ladders and bench games between scripted bots.** Thousands of games instead of dozens. This is the biggest win, since those bots answer in microseconds.
- **Scenario tests.**
  1. Save a state from a real game (ledge, edgeguard, laser pressure).
  2. Restore it hundreds of times.
  3. Measure what an LLM coach or a written bot does next.
  - This is the cheap way to run the Phillip exploit probes from research.md without a modded ISO.
- **Phillip evaluations** at many games per minute once models are exported with a batch size. slippi-ai's evaluator already does this with `--sim_envs --num_envs N`.
- **No gain for LLM players.** They are bound by model latency; `paused` mode already waits for them.

## Setup

```sh
cd vendor
git clone https://github.com/kyhavlov/melee-sim-light
(cd melee-sim-light && uv sync --python 3.12 --all-groups \
  && uv run python -m melee_sim.extract_data --iso ~/melee.iso)   # writes data/ (118 MB)

# A separate venv for slippi-ai + JAX + the simulator. Phillip's own vendor/slippi-ai/.venv
# serves live bots and stays untouched.
uv venv sim-venv --python 3.12
VIRTUAL_ENV=$PWD/sim-venv uv pip install -e "./slippi-ai[onnx-cuda,jax]" -e ./melee-sim-light

# Check our replays against the simulator (strict, frame by frame)
cd melee-sim-light && uv run python -m tools.validation.validate_replay --backend native --workers 12 \
  ../../replays/bench/*/2026-11-Mainline/*.slp

# Phillip vs Phillip
cd ../slippi-ai && MSL_DATA_DIR=../melee-sim-light/data JAX_PLATFORMS=cpu ../sim-venv/bin/python \
  ../../scripts/sim_phillip_eval.py --sim_envs --num_envs=1 --num_games=1 \
  --player.ai.path=models/gm.onnx --player.character=FOX --player.ai.onnx.providers=CUDAExecutionProvider \
  --opponent.ai.path=models/gold.onnx --opponent.character=FOX --opponent.ai.onnx.providers=CUDAExecutionProvider
```

Leave out `--use_gpu`/CUDA providers and onnxruntime takes every CPU core: one game ran for more than 10 minutes at 20 cores.
