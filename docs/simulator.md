# Decomp-based simulator (melee-sim-light)

[kyhavlov/melee-sim-light](https://github.com/kyhavlov/melee-sim-light) runs Melee's gameplay code from the [doldecomp/melee](https://github.com/doldecomp/melee) decompilation as a C library. It has no emulator, no rendering and no menus. It is a batched Python API with numpy outputs, and it supports save/restore of a whole game.

slippi-ai already ships a bridge to it (`slippi_ai/sim_env`). Phillip's training most likely runs on it: the slippi-ai README thanks Enzyme for a "decomp-based simulator that runs melee even faster than dolphin".

We tested it on 2026-11-14 with upstream commit `eea7b5fb`. It has **no license file**, so we don't redistribute it: `pyproject.toml` pins that commit as a git dependency, so `uv sync` builds it from GitHub on each machine (about a minute, once). Its game data is extracted from our ISO and stays local.

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
- **Learned bots** read the raw Slippi event stream, so `sim/slippi.py` writes one from the simulator (below).

## Playing our agents in it: `--mode sim`

`melee_llm/sim` runs any of our agents in the simulator, with the same contract as `runner.play`. `runner.play(mode="sim")` dispatches to it, so match.py, the bench, the ladders and the arena take it by mode name:

```sh
uv run python -m melee_llm.match --mode sim --p1 baseline:rusher --p2 baseline:laser --char1 FOX --char2 FOX --games 3
```

- **`sim/state.py`** builds the libmelee `GameState` from each observation, field for field as libmelee's Console builds it from Slippi. That includes the action frames re-indexed to start at 1, the moonwalk warning, `off_stage`, `distance`, projectiles and each player's controller state.
- **`sim/controller.py`** is a `melee.Controller` with no pipe. Agents press buttons on it as live. Each frame it converts `current` to the integers the game reads, the way Dolphin converts libmelee's pipe values.
- **`sim/world.py`** steps one match frame by frame (controllers in, `GameState` out) with `save()`/`restore()`; the runner plays whole games on it.
- **`sim/scenes.py`** reaches situations with plain inputs and saves them: standing mid-stage, dashing, hanging on the ledge. `tests/test_macros.py` runs the LLM player's input macros from them in the real game (it replaced a hand-written toy physics model, and caught a ledge macro that did nothing when the stick was still held from the grab).
- **`sim/parity.py`** checks both against libmelee. It replays a Dolphin `.slp`'s raw inputs through the simulator and compares every field with libmelee's own parse of the same replay.

**Exactness against libmelee.** 40 random replays of ours between controller-driven players gave 152,375 compared frames. Every field matched except `hitstun_frames_left`:
- Inside hitstun, every value agreed.
- Outside it, libmelee reports whatever Melee keeps in that shared slot (e.g. 32 while shielding or spot-dodging); the simulator reports 0.
- A game stays in sync until the first random choice that comes out differently: 15 of the 40 games never diverged.

**Learned bots in it.** They parse the raw Slippi event stream with their own libmelee build, so `sim/slippi.py` writes Slippi 3.19 events (what our Dolphin writes) from each simulator frame. `World` publishes them to the bots through `controller.slippi_tap`, the way `ConsoleTap` forwards Dolphin's.
- **Against Dolphin, field by field** (`python -m melee_llm.sim.slippi REPLAY.slp`): 10 replays, 30,735 frames before divergence. Every field libmelee or HAL reads is exact: sticks, triggers, physical buttons, raw stick, action, position, facing, percent, shield, stocks, airborne, jumps, hurtbox, speeds, hitlag and items.
- **Written as 0**, because the simulator doesn't report them: last attack, combo count, last hit by, ground id, L-cancel status, animation index, instance ids, most state bit flags, and the stick direction bits of the processed buttons (stateful; nothing we feed reads them).
- **Approximated:** hitstun outside hitstun, fractional action frames, and the pre-frame position and action (taken from the previous post-frame).
- **Processed sticks:** Melee clamps the raw stick to radius 80, truncates, then zeroes any axis at |raw| ≤ 22. HAL's own readback check uses the same rule. `StateBuilder` now fills `main_stick`, `c_stick`, `l_shoulder` and `processed_button` that way too, and the libmelee parity check (which now covers them) matches on all 30,725 frames, except 2 trigger frames with Z and a digital L/R held together.
- **HAL vs Phillip gm** (Battlefield, a 1-minute game): no errors, and HAL's executed-action check never fired. About 4–6 ms per frame, which is the two models thinking in parallel; the simulator is 0.3 ms of that. So learned-bot games are bounded by the models, not the game. The saving is no Dolphin process or display per game, so many can run side by side, up to what the GPU holds.

**Closed loop.** Bot-writer baselines rusher vs laser (Fox ditto, Battlefield), with the seed of a headless Dolphin game, replayed that Dolphin game input for input and frame for frame for all 28,923 frames. The final state was the same 4–4, 5.7% vs 0%.

**Speed.** That game took 32 s in the simulator and 143 s in headless Dolphin. Most of the 32 s is the bot-writer sandbox: pickling the `GameState` to each bot process each frame (9 s) and waiting for the bots (10 s). Building the state takes 0.23 ms/frame and the simulator 0.12 ms. Two in-process agents (idle vs multishine) run about 4,700 frames/s, an 8-minute game in 6 s.

**Differences from Dolphin.**
- No in-game CPU: `play` refuses it.
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

# The main venv gets melee-sim-light (and peppi-py, for the parity check) from `uv sync`;
# --mode sim and the simulator tests need only the data/ extracted above (or MSL_DATA_DIR).

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
