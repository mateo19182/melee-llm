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
- **Learned bots don't run in it through our adapter.** They read the raw Slippi event stream (`ConsoleTap`), which the simulator does not produce. Phillip can still play in it through slippi-ai's own `sim_env` (above).

## Playing our agents in it: `--mode sim`

`melee_llm/sim` runs any of our agents in the simulator, with the same contract as `runner.play`. `runner.play(mode="sim")` dispatches to it, so match.py, the bench, the ladders and the arena take it by mode name:

```sh
uv pip install -e vendor/melee-sim-light   # once, into the main venv (setup below)
uv run python -m melee_llm.match --mode sim --p1 baseline:rusher --p2 baseline:laser --char1 FOX --char2 FOX --games 3
```

- **`sim/state.py`** builds the libmelee `GameState` from each observation, field for field as libmelee's Console builds it from Slippi. That includes the action frames re-indexed to start at 1, the moonwalk warning, `off_stage`, `distance`, projectiles and each player's controller state.
- **`sim/controller.py`** is a `melee.Controller` with no pipe. Agents press buttons on it as live. Each frame it converts `current` to the integers the game reads, the way Dolphin converts libmelee's pipe values.
- **`sim/parity.py`** checks both against libmelee. It replays a Dolphin `.slp`'s raw inputs through the simulator and compares every field with libmelee's own parse of the same replay.

**Exactness against libmelee.** 40 random replays of ours between controller-driven players gave 152,375 compared frames. Every field matched except `hitstun_frames_left`:
- Inside hitstun, every value agreed.
- Outside it, libmelee reports whatever Melee keeps in that shared slot (e.g. 32 while shielding or spot-dodging); the simulator reports 0.
- A game stays in sync until the first random choice that comes out differently: 15 of the 40 games never diverged.

**Closed loop.** Bot-writer baselines rusher vs laser (Fox ditto, Battlefield), with the seed of a headless Dolphin game, replayed that Dolphin game input for input and frame for frame for all 28,923 frames. The final state was the same 4–4, 5.7% vs 0%.

**Speed.** That game took 32 s in the simulator and 143 s in headless Dolphin. Most of the 32 s is the bot-writer sandbox: pickling the `GameState` to each bot process each frame (9 s) and waiting for the bots (10 s). Building the state takes 0.23 ms/frame and the simulator 0.12 ms. Two in-process agents (idle vs multishine) run about 4,700 frames/s, an 8-minute game in 6 s.

**Differences from Dolphin.**
- No in-game CPU and no learned bots: `play` refuses both.
- No `.slp` replays (`GameResult.replay` is None).
- No ECB and no powershield flag in the `GameState`: they keep libmelee's defaults.
- `hitstun_frames_left` is 0 outside hitstun.
- The game's RNG is not Dolphin's, so the same seed and inputs repeat exactly here but play out differently on Dolphin.
- Timeouts are scored on the state at the timer, by stocks then percent. There is no Sudden Death.

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

# For --mode sim: the main venv (uv run keeps it; `uv sync` removes it, so reinstall after a sync).
# The replay parity check also needs peppi-py.
cd .. && uv pip install -e vendor/melee-sim-light peppi-py

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
