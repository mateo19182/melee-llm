"""Shared by the farm and its brain processes: simulator rows in, one raw controller row per seat out.

A brain plays a set of seats, (lane, port) pairs, with one model. Each frame it gets the whole batch's simulator rows,
rebuilds each of its lanes as a libmelee GameState (melee_llm.sim.state.StateBuilder, as for live play in the
simulator), lets the model read it exactly as the live bot does, presses a SimController per seat and returns the raw
input rows the game will read. Brains for bots in other virtualenvs (Phillip, HAL) run in their own processes
(farm.remote), so this module imports only numpy, libmelee and melee_llm.sim.

With `check`, a brain also rebuilds every frame from its Slippi events with libmelee's Console, which is how the live
bot sees Dolphin, and counts the seat-frames where what the model would read differs (Brain.reader).
"""
from __future__ import annotations

import collections
import dataclasses
import os
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]  # melee_llm comes from the checkout this file is in
LIVE = Path.home() / "projects/ai/melee-llm"  # vendor/ (weights, simulator data) lives in the main checkout
SIM = Path(os.environ.get("MELEE_SIM", "/mnt/data/melee/native/melee-brute"))
for _p in (str(REPO), str(SIM)):
    if _p not in sys.path:
        sys.path.insert(0, _p)
# melee_sim falls back to the -O0 build; the optimised one (`make python-release` in SIM) plays bit-identical frames
# about 5x faster (E31).
_RELEASE = SIM / "build/melee_core/python-release/libmelee_core.so"
if _RELEASE.is_file():
    os.environ.setdefault("MSL_CORE_LIBRARY", str(_RELEASE))


@dataclasses.dataclass
class Frame:
    """One frame of the whole batch, as a brain sees it."""
    obs: np.ndarray  # [lanes] simulator gamestate rows
    inputs: np.ndarray  # [lanes] raw input rows that produced obs (garbage where not has_input)
    has_input: np.ndarray  # [lanes] bool; False on a game's first frame
    fresh: np.ndarray  # [lanes] bool; a new game starts on this frame
    active: np.ndarray  # [lanes] bool; the lane is still playing
    events: dict | None = None  # lane -> this frame's Slippi events, when checking


def player_dtype():
    from melee_sim import dtypes

    return dtypes.input_player_dtype()


def sim_stages():
    from melee_llm.sim.state import SIM_STAGE

    return {v: k for k, v in SIM_STAGE.items()}


def flatten(value, prefix=""):
    """(name, leaf) pairs of a NamedTuple / dict / tuple tree."""
    if hasattr(value, "_fields"):
        for f in value._fields:
            yield from flatten(getattr(value, f), f"{prefix}{f}.")
    elif isinstance(value, dict):
        for k in sorted(value, key=str):
            yield from flatten(value[k], f"{prefix}{k}.")
    elif isinstance(value, (tuple, list)):
        for i, v in enumerate(value):
            yield from flatten(v, f"{prefix}{i}.")
    else:
        yield prefix[:-1], value


class Checker:
    """Rebuilds each lane from Slippi events (as the live bot sees Dolphin) and compares what each seat reads."""

    def __init__(self, brain):
        from melee_llm.bots.server import Replayer
        from melee_llm.sim.slippi import Encoder  # noqa: F401  (the coordinator encodes; imported to fail early)

        self.brain, self.Replayer = brain, Replayer
        self.replayers, self.readers = {}, {}
        self.compared, self.diffs, self.examples = 0, collections.Counter(), {}

    def __call__(self, frame, states):
        for lane, gs in states.items():
            if frame.fresh[lane] or lane not in self.replayers:
                self.replayers[lane] = self.Replayer()
            ref = self.replayers[lane].feed([("game_event", frame.events[lane])])
            for i in self.brain.lane_seats[lane]:
                port = self.brain.seats[i][1]
                if frame.fresh[lane] or i not in self.readers:
                    self.readers[i] = self.brain.reader(port)
                ours, theirs = self.brain.last_read[i], self.readers[i](ref)
                self.compared += 1
                for (name, a), (_, b) in zip(flatten(ours), flatten(theirs)):
                    if not np.array_equal(np.asarray(a), np.asarray(b)):
                        self.diffs[name] += 1
                        self.examples.setdefault(name, (lane, int(frame.obs[lane]["frame_id"]), port, repr(a),
                                                        repr(b)))

    def report(self):
        return {"compared": self.compared, "diffs": dict(self.diffs), "examples": self.examples}


class Brain:
    """Base class. Subclasses set `reader(port)` (a callable GameState -> what the model reads, fresh each game)
    and `decide(states, frame)`, which presses self.controllers[i] for every live seat i.

    A brain with `from_events` builds its GameStates from each frame's Slippi events, with its own venv's libmelee,
    exactly as the live bot does; the farm then encodes events every frame. HAL needs this: its libmelee fork builds
    its observations from parsed event data that a GameState assembled field by field does not carry."""

    from_events = False

    def __init__(self, seats, check=False):
        from melee_llm.sim.controller import SimController

        self.seats = [tuple(s) for s in seats]
        self.lane_seats = collections.defaultdict(list)
        for i, (lane, _) in enumerate(self.seats):
            self.lane_seats[lane].append(i)
        self.controllers = [SimController(port) for _, port in self.seats]
        self.rows = np.zeros(len(self.seats), dtype=player_dtype())
        self.builders, self.stages = {}, sim_stages()
        self.last_read = [None] * len(self.seats)
        self.checker = Checker(self) if check and not self.from_events else None  # events are the live path
        self.replayers = {}

    def states(self, frame):
        """libmelee GameStates of this brain's live lanes."""
        from melee_llm.sim.state import StateBuilder

        out = {}
        for lane in self.lane_seats:
            if not frame.active[lane]:
                continue
            if self.from_events:
                if frame.fresh[lane] or lane not in self.replayers:
                    from melee_llm.bots.server import Replayer
                    self.replayers[lane] = Replayer()
                out[lane] = self.replayers[lane].feed([("game_event", frame.events[lane])])
                continue
            obs = frame.obs[lane]
            if frame.fresh[lane] or lane not in self.builders:
                self.builders[lane] = StateBuilder(self.stages[int(obs["stage_id"])], [1, 2])
            out[lane] = self.builders[lane].build(obs, frame.inputs[lane] if frame.has_input[lane] else None)
        return out

    def act(self, frame) -> np.ndarray:
        states = self.states(frame)
        self.decide(states, frame)
        if self.checker is not None:
            self.checker(frame, states)
        for i, (lane, port) in enumerate(self.seats):
            if frame.active[lane]:
                self.controllers[i].raw_input(self.rows[i])
                self.controllers[i].flush()
        return self.rows

    def report(self):
        if self.from_events:
            return {"from_events": True}
        return self.checker.report() if self.checker is not None else None

    def reader(self, port):
        raise NotImplementedError

    def decide(self, states, frame):
        raise NotImplementedError


def stack(trees):
    """Stack NamedTuple trees of scalars (one per seat) into one tree of arrays."""
    first = trees[0]
    if hasattr(first, "_fields"):
        return type(first)(*[stack([getattr(t, f) for t in trees]) for f in first._fields])
    return np.array(trees)


def row(tree, i):
    """Row i of a NamedTuple tree of arrays."""
    if hasattr(tree, "_fields"):
        return type(tree)(*[row(getattr(tree, f), i) for f in tree._fields])
    return tree[i]
