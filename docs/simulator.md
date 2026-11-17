# Decomp-based simulator (melee-sim-light)

[kyhavlov/melee-sim-light](https://github.com/kyhavlov/melee-sim-light) runs Melee's gameplay code from the [doldecomp/melee](https://github.com/doldecomp/melee) decompilation as a C library: no emulator, rendering or menus, a batched Python API with numpy outputs, and save/restore of a whole game.

slippi-ai ships a bridge to it (`slippi_ai/sim_env`), and Phillip's training most likely runs on it: the slippi-ai README thanks Enzyme for a "decomp-based simulator that runs melee even faster than dolphin".

Tested on 2026-11-14 at upstream commit `eea7b5fb`. It has **no license file**, so we don't redistribute it: `pyproject.toml` pins that commit as a git dependency, and `uv sync` builds it from GitHub on each machine (about a minute, once). Its game data is extracted from our ISO and stays local.

## Results

**Exactness.** The simulator's own strict validator on 300 random Dolphin replays of ours:
- **287 matched frame for frame**: 2.34M frames, zero mismatches, across bench, LLM players, coach pilots, learned bots and CPU 9.
- **13 could not be read**: replays of stopped games that Dolphin never finalized. None was a mismatch.
- The validator feeds each replay's recorded inputs and RNG observations, so it shows identical game logic, not that a freely running simulated game stays in RNG lockstep with Dolphin.

**Speed.**

| What | Speed | Conditions |
|---|---|---|
| Simulator alone | about 17,500 frames/s | one game, one thread, this machine at load average 45. About 100× our headless Dolphin (~170 frames/s for HAL vs CPU 9) |
| Validator | 2.3M frames in 30 s | 12 workers |
| Upstream's claim | about 120k frames/s per core | a quiet Ryzen 9950X3D, batch 256 |

**Phillip vs Phillip in the simulator.** slippi-ai's own evaluator played `gm.onnx` vs `gold.onnx` (Fox ditto) to completion: gm won 4-0 on Fountain of Dreams in 5,248 frames. Per frame, the simulator plus observation conversion took 0.66 ms and each policy 8.6 ms (batch-1 ONNX on a shared, busy GPU), so the policy is the bottleneck. Our ONNX exports have a fixed batch of 1; many games at once need batched exports.

## Our patch: in-place checkpoint and rollback

melee-llm installs our fork [melee-brute](https://github.com/mateo19182/melee-brute) instead of upstream melee-sim-light (`pyproject.toml`), built with upstream's optimised `python-release` profile. melee-brute adds exact take-back to the simulator (write-protected memory, about 5 µs a checkpoint or rollback against 300 µs for the library's lane copy) and a forced-win search in C; `melee_llm/solver/takeback.py` is the small wrapper our Python searches use. Details and the search built on it: [optimal-play.md](optimal-play.md), section 11.

## Gaps

- **slippi-ai bug.** slippi-ai @ `5ada33e` looks players up by `present`, which melee_sim clears for an eliminated player, so every game that ends on stocks crashes. `scripts/sim_phillip_eval.py` patches the two lookups at runtime; the vendored repo stays untouched.
- **No CPU opponents.** The public API exposes none, so CPU-level baselines stay on Dolphin.
- **Rules.** Supported matches are UCF, no items, and frozen Pokémon Stadium, which is what Slippi plays anyway.

## Playing our agents in it: `--mode sim`

`melee_llm/sim` runs any of our agents, learned bots included, in the simulator with the same contract as `runner.play`. `runner.play(mode="sim")` dispatches to it, so match.py, the bench, the ladders and the arena take it by mode name:

```sh
uv run python -m melee_llm.match --mode sim --p1 baseline:rusher --p2 baseline:laser --char1 FOX --char2 FOX --games 3
```

| File | Role |
|---|---|
| `sim/state.py` | Builds the libmelee `GameState` from each observation, field for field as libmelee's Console builds it from Slippi |
| `sim/controller.py` | A `melee.Controller` with no pipe; agents press buttons on it as they do live |
| `sim/world.py` | Steps one match frame by frame, with `save()`/`restore()`; the runner plays whole games on it |
| `sim/scenes.py` | Saved situations reached with plain inputs (standing mid-stage, dashing, hanging on the ledge). `tests/test_macros.py` runs the LLM player's input macros from them |
| `sim/slippi.py` | Writes Slippi 3.19 events from each simulator frame, because learned bots parse the raw event stream with their own libmelee build |
| `sim/parity.py` | Replays a Dolphin `.slp`'s raw inputs through the simulator and compares every field with libmelee's own parse |

**Exactness against libmelee** (`sim/parity.py`). 40 random replays of ours between controller-driven players gave 152,375 compared frames. Every field matched except `hitstun_frames_left`: outside hitstun, libmelee reports whatever Melee keeps in that shared slot and the simulator reports 0. A game stays in sync until the first random choice that comes out differently: 15 of the 40 games never diverged.

**Learned bots in it.**
- **Events against Dolphin** (`python -m melee_llm.sim.slippi REPLAY.slp`): 10 replays, 30,735 frames before divergence, and every field libmelee or HAL reads is exact.
- **Not exact:** fields the simulator doesn't report are written as 0 (last attack, combo count, L-cancel status, animation index and others), and a few are approximated; `sim/slippi.py` lists them. Nothing we feed reads them.
- **Processed sticks and triggers** match libmelee on all 30,725 compared frames except 2 trigger frames with Z and a digital L/R held together.
- **HAL vs Phillip gm** (Battlefield, a 1-minute game): no errors, and HAL's executed-action check never fired. A frame takes about 4–6 ms, of which the simulator is 0.3 ms, so the models bound learned-bot games. The saving is no Dolphin process or display per game, so many can run side by side, up to what the GPU holds.

**Closed loop.** Bot-writer baselines rusher vs laser (Fox ditto, Battlefield), given the seed of a headless Dolphin game, replayed that game input for input and frame for frame for all 28,923 frames, to the same final state.

**Speed.** That game takes 25 s in the simulator against 143 s in headless Dolphin. Most of the 25 s is the bot-writer sandbox's round-trip to each bot process (about 0.35 ms); building the state takes 0.23 ms/frame and the simulator 0.12 ms. Two in-process agents (idle vs multishine) run at about 4,700 frames/s: an 8-minute game in 6 s.

**Differences from Dolphin.**
- No in-game CPU: `play` refuses it.
- No `.slp` replays (`GameResult.replay` is None).
- No ECB and no powershield flag in the `GameState`: they keep libmelee's defaults.
- `hitstun_frames_left` is 0 outside hitstun.
- The game's RNG is not Dolphin's, so the same seed and inputs repeat exactly here but play out differently on Dolphin.
- Timeouts are scored on the state at the timer, by stocks then percent. There is no Sudden Death.

## Next work

Done: `--mode sim` for our agents and the learned bots, macro tests in the real game (`tests/test_macros.py`), and bot-writer practice in the simulator (`python -m melee_llm.botwriter.practice play ... --sim`, opt-in). Not started, roughly in order of value for effort:

1. **Scenario probes for our agents.** `python -m melee_llm.sim.probe --agent bot:x.py --scene ledge --trials N`: restore a saved scene and report what the agent does next and how often it survives or gets hit. Needs more scenes in `sim/scenes.py` (offstage recovery, being edgeguarded, laser pressure, opponent crouching in the corner). Written bots and baselines are deterministic, so one trial per scene is enough for them; LLM players need several.
2. **Every macro from every scene.** `test_macros.py` runs each macro from one scene. The ledge bug it caught (Melee ignores the stick on the ledge until it has been neutral) came from the state the macro *starts* in, so more start states would catch more of that kind.
3. **Phillip exploit probes** ([research.md](research.md)): Puff Rollout, crouching in the corner, Marth vs lasers. Phillip can't play through our adapter, so this needs slippi-ai's own `sim_env` in `sim-venv` (setup below), with save/restore and scripted exploit players. Bigger and riskier than 1.
4. **Ladder in the simulator** for non-CPU pairings. Left out on purpose: no CPUs and a different RNG make its scores incomparable with Dolphin ladders.
5. **Bot-writer round-trip**: pickle the shared part of the state once per frame instead of per bot, or use shared memory.
6. **Missing GameState fields** (ECB, powershield flag). Bots tested here that read the ECB may behave differently on Dolphin.
7. **Phillip evaluations** at many games per minute, once models are exported with a batch dimension (slippi-ai's evaluator does `--sim_envs --num_envs N`).

Not worth it: LLM players. Model latency bounds them, and `paused` mode already waits for them.

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
