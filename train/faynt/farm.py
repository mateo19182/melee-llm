"""Many Faynt games at once in the simulator: one batch of matches, one batched model step per Faynt variant.

    vendor/Faynt-Tournament/.venv/bin/python -m faynt.farm faynt:10M-Arena/YOSHI faynt:10M-Expert/YOSHI \\
        --games 64 [--lanes 64] [--workers 1] [--out DIR] [--ucf]

Run from train/ with PYTHONPATH=. (melee_llm comes from this checkout, the simulator from $MELEE_SIM). A player
is `faynt:VARIANT[,temperature=T]/CHARACTER` (default Yoshi). The first player takes port 1 on even lanes and port 2 on odd ones; stages cycle over the six
legal ones. Rules: 4 stocks, 8 minutes, no items; UCF off unless --ucf (Slippi and our Dolphin have it on).

Each seat sees exactly what the live Faynt bot (melee_llm/bots/bot_faynt.py) sees in Dolphin: the simulator row
becomes a libmelee GameState (melee_llm.sim.state, checked field for field against libmelee), slippi-ai's Parser
turns that into a Game, and the bot's chosen controller goes back through SimController, which reproduces the
integers Dolphin would read. Only the model step is batched; --workers splits the games over processes.
"""
import argparse
import dataclasses
import json
import os
import sys
import time
from pathlib import Path

import numpy as np
import torch

REPO = Path(__file__).resolve().parents[2]  # melee_llm comes from the checkout this file is in
LIVE = Path.home() / "projects/ai/melee-llm"  # vendor/ (weights, simulator data) lives in the main checkout
SIM = Path(os.environ.get("MELEE_SIM", "/mnt/data/melee/native/melee-brute"))
DATA = Path(os.environ.get("MSL_DATA_DIR", LIVE / "vendor/melee-sim-light/data"))
WEIGHTS = LIVE / "vendor/Faynt-Tournament/weights"
STAGES = ["BATTLEFIELD", "FINAL_DESTINATION", "YOSHIS_STORY", "DREAMLAND", "FOUNTAIN_OF_DREAMS", "POKEMON_STADIUM"]
TIMER = 8 * 60 * 60  # frames; Slippi's 8-minute timer
RING = 1024  # simulator frames per buffer pass; the cursor wraps
BUTTONS = ("A", "B", "X", "Y", "Z", "L", "R", "D_UP")
sys.path[:0] = [str(SIM), str(REPO)]


@dataclasses.dataclass(frozen=True)
class Player:
    name: str
    variant: str
    character: str
    temperature: float

    @classmethod
    def parse(cls, name):
        spec, _, character = name.partition("/")
        kind, _, arg = spec.partition(":")
        if kind != "faynt":
            raise ValueError(f"{name}: only faynt: players run in this farm")
        variant, *options = arg.split(",")
        o = dict(x.split("=", 1) for x in options)
        return cls(name, variant or "10M-Arena", character or "YOSHI", float(o.get("temperature", 1.0)))


@dataclasses.dataclass
class Seat:
    lane: int
    port: int  # libmelee port, 1 or 2; the simulator's source player is port - 1
    player: Player
    controller: object = None
    parser: object = None
    game: object = None


def batched_cache(model):
    """Replace Faynt's cached attention, which loops over the batch in Python (two .item() syncs and a gather per
    row per layer), with one indexed write and a mask. Keys carry their RoPE positions and softmax attention does not
    depend on key order, so attending to the ring in slot order instead of chronological order is the same function
    up to float summation order. After a reset slots fill from 0, so the live slots are those below the length."""

    cls = type(model.policy.backbone.layers[0].attention)
    if getattr(cls, "_batched", False):
        return

    def forward_cached(self, normalized_inputs, positions, cache, valid_mask):
        queries, keys, values = self._project(normalized_inputs, positions)
        valid = valid_mask.to(device=cache.keys.device, dtype=torch.bool)
        rows = torch.arange(cache.batch_size, device=cache.keys.device)
        write = cache.write_position.long()
        layer_k, layer_v = cache.keys[self.layer_index], cache.values[self.layer_index]
        layer_k[rows, write] = torch.where(valid[:, None, None], keys[:, :, 0].to(layer_k.dtype), layer_k[rows, write])
        layer_v[rows, write] = torch.where(valid[:, None, None], values[:, :, 0].to(layer_v.dtype), layer_v[rows, write])
        lengths = torch.clamp(cache.valid_length + valid.long(), max=cache.capacity)
        key_valid = torch.arange(cache.capacity, device=cache.keys.device)[None] < lengths[:, None]
        mask = key_valid[:, None, None, :] & valid[:, None, None, None]
        head_output = self._sdpa(queries, layer_k.permute(0, 2, 1, 3).to(queries.dtype),
                                 layer_v.permute(0, 2, 1, 3).to(queries.dtype), attention_mask=mask, is_causal=False)
        head_output = torch.where(valid[:, None, None, None], head_output, 0.0)
        return self._apply_output_gate(head_output, normalized_inputs)

    cls.forward_cached, cls._batched = forward_cached, True


def _leaves(tree, path=()):
    """(path, tensor) for every tensor in a tensor_batch dataclass tree."""
    if dataclasses.is_dataclass(tree):
        for f in dataclasses.fields(tree):
            yield from _leaves(getattr(tree, f.name), (*path, f.name))
    else:
        yield path, tree


def _column(games, path):
    """One input field for every seat, from slippi-ai Games (self as p0), as a numpy array."""
    if path[0] == "items":
        return np.array([[getattr(getattr(g.items, f"item_{i}"), path[1]) for i in range(15)] for g in games])
    values = []
    for g in games:
        v = g
        for name in path:
            v = getattr(v, name)
        values.append(v)
    return np.array(values)


class GraphStep:
    """Faynt's batched step recorded once as a CUDA graph and replayed every frame.

    The model checks its inputs with Python-side reads of GPU tensors (`bool(x.any())`), which a graph cannot
    contain. A warm-up step runs those checks for real on valid inputs and records their answers; while recording
    the graph, tensor truth values replay those answers in order. Every such check guards a `raise` (and the cache
    reset is replaced by a masked one), so control flow does not depend on the data and the recorded graph is the
    model's arithmetic alone. The constant tables the codec builds with `torch.tensor` each step are likewise
    the warm-up's, kept alive for the graph. Sampling draws from the default CUDA generator, which graphs support."""

    def __init__(self, model, batch, temperature, seed=0):

        batched_cache(model)
        kv = type(model.init_cache(1, device="cuda"))
        if not getattr(kv, "_masked_reset", False):
            def reset_slots(self, reset_mask):
                reset = reset_mask.to(device=self.keys.device, dtype=torch.bool)
                self.keys.masked_fill_(reset.view(1, -1, 1, 1, 1), 0)
                self.values.masked_fill_(reset.view(1, -1, 1, 1, 1), 0)
                for t in (self.valid_length, self.write_position, self.next_position):
                    t.masked_fill_(reset, 0)
            kv.reset_slots, kv._masked_reset = reset_slots, True
        self.model, self.temperature = model, temperature
        example = model.example_inputs(batch, None, device="cuda")
        self.state = example["game_state_t"]
        self.inputs = list(_leaves(self.state))
        self.reset = torch.zeros(batch, dtype=torch.bool, device="cuda")
        self.cache = model.init_cache(batch, device="cuda")
        torch.cuda.manual_seed(seed)

        def run():
            with torch.inference_mode():
                out = model.step(game_state_t=self.state, controller_t=self.state.p0.controller, cache=self.cache,
                                 reset_mask=self.reset, temperature=temperature)
            self.button_logits = out.logits["buttons"]
            return out.controller.as_packed_tensor().reshape(batch, -1)

        truth, build, answers, constants = torch.Tensor.__bool__, torch.tensor, [], []

        def recording_truth(t):
            answers.append(truth(t))
            return answers[-1]

        def recording_build(*args, **kwargs):
            constants.append(build(*args, **kwargs))
            return constants[-1]

        side = torch.cuda.Stream()
        side.wait_stream(torch.cuda.current_stream())
        with torch.cuda.stream(side):
            run()
            torch.Tensor.__bool__, torch.tensor = recording_truth, recording_build
            try:
                run()
            finally:
                torch.Tensor.__bool__, torch.tensor = truth, build
        torch.cuda.current_stream().wait_stream(side)
        replay_truth, replay_build = iter(answers), iter(constants)
        self.constants = constants  # the graph reads them: keep them alive
        self.graph = torch.cuda.CUDAGraph()
        torch.Tensor.__bool__ = lambda t: next(replay_truth)
        torch.tensor = lambda *args, **kwargs: next(replay_build)
        try:
            with torch.cuda.graph(self.graph):
                self.out = run()
        finally:
            torch.Tensor.__bool__, torch.tensor = truth, build
        if next(replay_truth, None) is not None or next(replay_build, None) is not None:
            raise RuntimeError("the recorded step took a different path from the warm-up step")
        self.fresh = True  # the warm-up wrote history: the first real frame restarts every row

    def load(self, games):
        """Copy one frame of inputs (slippi-ai Games, one per seat) into the recorded input tensors."""

        for path, tensor in self.inputs:
            tensor.copy_(torch.from_numpy(_column(games, path)).to(tensor.dtype), non_blocking=True)

    def step(self, reset):
        """Advance every row one frame; rows with `reset` start a new game. Returns the packed controllers on the
        GPU: main x/y, c x/y, shoulder, A B X Y Z L R D_UP."""

        self.reset.copy_(torch.from_numpy(np.asarray(reset, dtype=bool) | self.fresh), non_blocking=True)
        self.fresh = False
        self.graph.replay()
        return self.out

    def __call__(self, games, reset):
        self.load(games)
        return self.step(reset).float().cpu().numpy()


class Brain:
    """One Faynt checkpoint playing all its seats in one batched step a frame (a CUDA graph unless graph=False)."""

    def __init__(self, variant, seats, seed=0, graph=True):
        from transformers import AutoModel

        self.model = AutoModel.from_pretrained(str(WEIGHTS / f"Faynt-{variant}"), trust_remote_code=True).eval().cuda()
        self.seats, self.temperature = seats, seats[0].player.temperature
        if any(s.player.temperature != self.temperature for s in seats):
            raise ValueError("one temperature per variant")
        if graph:
            self.step = GraphStep(self.model, len(seats), self.temperature, seed)
        else:
            batched_cache(self.model)
            self.step = EagerStep(self.model, len(seats), self.temperature, seed)

    def act(self, games, reset):
        """games: one slippi-ai Game per seat, self as p0. Returns packed controllers, one row per seat:
        main x/y, c x/y, shoulder, A B X Y Z L R D_UP."""
        return self.step(games, reset)


class EagerStep:
    """The same step without a graph: for checking GraphStep, and a fallback if capture fails."""

    def __init__(self, model, batch, temperature, seed=0):

        self.model, self.temperature = model, temperature
        self.state = model.example_inputs(batch, None, device="cuda")["game_state_t"]
        self.inputs = list(_leaves(self.state))
        self.cache = model.init_cache(batch, device="cuda")
        self.generator = torch.Generator(device="cuda").manual_seed(seed)

    def __call__(self, games, reset):

        for path, tensor in self.inputs:
            tensor.copy_(torch.from_numpy(_column(games, path)).to(tensor.dtype), non_blocking=True)
        with torch.inference_mode():
            out = self.model.step(game_state_t=self.state, controller_t=self.state.p0.controller, cache=self.cache,
                                  reset_mask=torch.as_tensor(np.asarray(reset, dtype=bool)).cuda(),
                                  temperature=self.temperature, generator=self.generator)
        return out.controller.as_packed_tensor().reshape(len(reset), -1).float().cpu().numpy()


def press(controller, c):
    import melee

    B = melee.enums.Button
    controller.tilt_analog(B.BUTTON_MAIN, c[0], c[1])
    controller.tilt_analog(B.BUTTON_C, c[2], c[3])
    controller.press_shoulder(B.BUTTON_L, c[4])
    for name, v in zip(BUTTONS, c[5:]):
        (controller.press_button if v > 0.5 else controller.release_button)(B[f"BUTTON_{name}"])


def play(a, b, games, lanes=64, out=None, seed=0, ucf=False, on_frame=None, first=0, quiet=False, graph=True):
    """Play `games` games of a against b. Returns the result rows; a's score is 1 for a win, 0.5 for a draw.
    on_frame(lane, obs, inputs, games), if given, sees each live lane every frame: the simulator row, the raw input row
    that produced it (None on a game's first frame) and the slippi-ai Game each seat played from, by port.
    Games are numbered from `first` (a game's number picks its stage and seed), so workers can split a run."""
    import melee
    import melee_sim as msl
    from slippi_db.parse_libmelee import Parser

    from melee_llm.sim.controller import SimController
    from melee_llm.sim.state import SIM_STAGE, StateBuilder

    lanes = min(lanes, games)
    a_port = [1 + lane % 2 for lane in range(lanes)]
    seats = [Seat(lane, port, a if port == a_port[lane] else b) for lane in range(lanes) for port in (1, 2)]
    by_variant = {}
    for s in seats:
        by_variant.setdefault(s.player.variant, []).append(s)
    brains = [Brain(v, ss, seed + first, graph) for v, ss in by_variant.items()]

    env = msl.EnvBatch(batch_size=lanes, length=RING, action_format="raw", data_dir=str(DATA),
                       ucf_cardinals_1_0_enabled=ucf)
    game = list(range(first, first + lanes))
    builders = [None] * lanes

    def configure(lane):
        chars = (a.character, b.character) if a_port[lane] == 1 else (b.character, a.character)
        stage = melee.Stage[STAGES[game[lane] % len(STAGES)]]
        env.configure_matches([msl.MatchConfig(
            stage=SIM_STAGE[stage], seed=(seed + game[lane]) % 2**32, max_frame=TIMER, ucf_cardinals_1_0_enabled=ucf,
            players=tuple(msl.PlayerConfig(melee.Character[c].value, controller_port=i) for i, c in enumerate(chars)))],
            env_ids=[lane])
        builders[lane] = StateBuilder(stage, [1, 2])
        for s in seats[2 * lane:2 * lane + 2]:
            s.controller, s.parser = SimController(s.port), Parser(ports=(s.port, 3 - s.port))

    for lane in range(lanes):
        configure(lane)
    env.reset_all()
    active, fresh = np.ones(lanes, bool), np.ones(lanes, bool)
    rows = [None] * lanes  # the raw input row that produced each lane's current frame
    next_game, frames, results, started = first + lanes, 0, [], time.monotonic()
    if out:
        Path(out).mkdir(parents=True, exist_ok=True)

    while active.any():
        obs = env.current_frame
        states = [builders[lane].build(obs[lane], rows[lane]) if active[lane] else None for lane in range(lanes)]
        for brain in brains:
            live = [s for s in brain.seats if active[s.lane]]
            if not live:
                continue
            for s in live:
                s.game = s.parser.get_game(states[s.lane])
            gs_list = [s.game for s in brain.seats]  # finished lanes repeat their last frame: the batch stays fixed
            actions = brain.act(gs_list, np.array([bool(fresh[s.lane]) for s in brain.seats]))
            for i, s in enumerate(brain.seats):
                if active[s.lane]:
                    press(s.controller, actions[i])
        if on_frame:
            for lane in np.flatnonzero(active):
                on_frame(int(lane), obs[lane], rows[lane], {s.port: s.game for s in seats[2 * lane:2 * lane + 2]})
        if env.t >= env.length:
            env.reset_cursor()
        raw = env.raw_action_view[env.t]
        for s in seats:
            if active[s.lane]:
                s.controller.raw_input(raw[s.lane]["players"][s.port - 1])
                s.controller.flush()
        t = env.t
        env.step(active.astype(np.uint8))
        frames += int(active.sum())
        fresh[:] = False
        for lane in np.flatnonzero(active):
            rows[lane] = raw[lane].copy()
        done = active & env.terminal_view[t]["done"].astype(bool)
        if not done.any():
            continue
        obs = env.current_frame
        restart = []
        for lane in np.flatnonzero(done):
            slots = {int(s["source_player"]): s for s in obs[lane]["slots"] if s["source_player"] < 2}
            mine, theirs = (0, 1) if a_port[lane] == 1 else (1, 0)
            stocks = [int(slots[p]["stocks"]) for p in (mine, theirs)]
            percent = [float(slots[p]["percent"]) for p in (mine, theirs)]
            lead = (stocks[0] - stocks[1]) or (percent[1] - percent[0])  # timer: stocks, then the lower percent
            frame_id = int(obs[lane]["frame_id"])
            row = dict(time=time.time(), a=a.name, b=b.name, a_char=a.character, b_char=b.character,
                       stage=STAGES[game[lane] % len(STAGES)], score=0.5 if lead == 0 else float(lead > 0),
                       stocks_a=stocks[0], stocks_b=stocks[1], frames=frame_id + 123, a_port=mine + 1,
                       seed=seed + game[lane], timeout=bool(env.terminal_view[t][lane]["max_frame_reached"]),
                       sim=True, ucf=ucf)
            results.append(row)
            if out:
                with open(Path(out) / "results.jsonl", "a") as f:
                    f.write(json.dumps(row) + "\n")
            quiet or print(f"{a.name} vs {b.name} on {row['stage']}: {row['score']} ({stocks[0]}-{stocks[1]} stocks, "
                  f"{row['frames']} frames)", flush=True)
            if next_game < first + games:
                game[lane], next_game = next_game, next_game + 1
                configure(lane)
                restart.append(lane)
            else:
                active[lane] = False
        if restart:
            env.reset_matches(restart)
            for lane in restart:
                rows[lane], fresh[lane] = None, True
    env.close()
    if not quiet:
        summary(a, b, results, frames, time.monotonic() - started)
    return results


def summary(a, b, results, frames, wall):
    score = sum(r["score"] for r in results)
    stocks = sum(r["stocks_a"] - r["stocks_b"] for r in results) / max(1, len(results))
    print(f"{a.name}: {score:g} of {len(results)} against {b.name} ({stocks:+.2f} stocks a game); {frames:,} frames "
          f"in {wall / 60:.1f} min ({frames / wall:,.0f} a second)", flush=True)


def _worker(job):

    torch.set_num_threads(1)
    a, b, games, lanes, out, seed, ucf, first, graph = job
    results = play(a, b, games, lanes, out, seed, ucf, first=first, quiet=True, graph=graph)
    return results, sum(r["frames"] for r in results)


def play_parallel(a, b, games, lanes=64, out=None, seed=0, ucf=False, workers=1, graph=True):
    """`play` split over worker processes, each with its own simulator batch and models."""
    import multiprocessing
    from concurrent.futures import ProcessPoolExecutor

    if workers <= 1:
        return play(a, b, games, lanes, out, seed, ucf, graph=graph)
    share = [games // workers + (i < games % workers) for i in range(workers)]
    firsts = np.cumsum([0, *share[:-1]])
    jobs = [(a, b, n, min(lanes, n), out, seed, ucf, int(f), graph) for n, f in zip(share, firsts) if n]
    started, results, frames = time.monotonic(), [], 0
    with ProcessPoolExecutor(len(jobs), mp_context=multiprocessing.get_context("spawn")) as ex:
        for r, f in ex.map(_worker, jobs):
            results += r
            frames += f
    summary(a, b, results, frames, time.monotonic() - started)
    return results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("a")
    ap.add_argument("b")
    ap.add_argument("--games", type=int, default=64)
    ap.add_argument("--lanes", type=int, default=64)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--ucf", action="store_true")
    ap.add_argument("--workers", type=int, default=1, help="processes; each runs --lanes games at a time")
    ap.add_argument("--no-graph", action="store_true", help="step Faynt eagerly instead of replaying a CUDA graph")
    args = ap.parse_args()
    play_parallel(Player.parse(args.a), Player.parse(args.b), args.games, args.lanes, args.out, args.seed, args.ucf,
                  args.workers, not args.no_graph)


if __name__ == "__main__":
    main()
