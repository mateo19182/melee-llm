"""One melee-sim-light match stepped frame by frame: SimControllers in, libmelee GameStates out, with savestates.

The runner plays whole games on it; tests and scenarios restore a saved moment and step from there.
"""
from __future__ import annotations

import copy
import os
from dataclasses import dataclass
from pathlib import Path

import melee

from melee_llm.paths import VENDOR
from melee_llm.sim.controller import SimController
from melee_llm.sim.state import SIM_STAGE, StateBuilder

DATA_DIR = Path(os.environ.get("MSL_DATA_DIR", VENDOR / "melee-sim-light/data"))
TIMER_FRAMES = 8 * 60 * 60  # Slippi's 8-minute timer
_RING = 1024  # frames per buffer pass; the cursor wraps


def available() -> bool:
    """melee-sim-light is installed and its game data (extracted from the ISO) is present."""
    try:
        import melee_sim  # noqa: F401
    except ImportError:
        return False
    return (DATA_DIR / "raw").is_dir() or DATA_DIR.name == "raw" and DATA_DIR.is_dir()


@dataclass(frozen=True)
class Snapshot:
    """A moment of a match: the simulator's complete state and the GameState built for it."""
    state: bytes
    gs: melee.GameState


class World:
    def __init__(self, characters: dict[int, melee.Character], stage: melee.Stage = melee.Stage.BATTLEFIELD,
                 seed: int = 0, costumes: dict[int, int] | None = None, max_frame: int = TIMER_FRAMES):
        import melee_sim as msl

        if stage not in SIM_STAGE:
            raise ValueError(f"{stage.name} is not a legal stage in the simulator")
        self.stage, self.ports, self.max_frame = stage, sorted(characters), max_frame
        self.costumes = {p: (costumes or {}).get(p, 0) for p in self.ports}
        self.controllers = {p: SimController(p) for p in self.ports}
        self._players = tuple(msl.PlayerConfig(characters[p].value, controller_port=p - 1, costume=self.costumes[p])
                              for p in self.ports)
        self.env = msl.EnvBatch(batch_size=1, length=_RING, action_format="raw", data_dir=str(DATA_DIR))
        self.reset(seed)

    def reset(self, seed: int) -> melee.GameState:
        """Start a new game: the first frame of the countdown, controllers released."""
        self.env.configure_match(stage=SIM_STAGE[self.stage], seed=seed % 2**32, max_frame=self.max_frame,
                                 players=self._players)
        self.env.reset_all()
        self.builder = StateBuilder(self.stage, self.ports, self.costumes)
        self.gs, self.done = self.builder.build(self.env.current_frame[0]), False
        for c in self.controllers.values():
            c.release_all()
            c.flush()
        return self.gs

    def step(self) -> melee.GameState:
        """Feed the controllers' current state to the game and advance one frame."""
        env = self.env
        if env.t >= env.length:
            env.reset_cursor()
        row = env.raw_action_view[env.t, 0]
        for i, p in enumerate(self.ports):
            self.controllers[p].raw_input(row["players"][i])
            self.controllers[p].flush()
        t = env.t
        env.step()
        self.gs = self.builder.build(env.current_frame[0], row)
        self.done = bool(env.terminal_view[t, 0]["done"])
        return self.gs

    def save(self) -> Snapshot:
        return Snapshot(self.env.save(0), copy.deepcopy(self.gs))

    def restore(self, snap: Snapshot) -> melee.GameState:
        """Back to `snap`. Controllers are released: the next step reads only what is pressed after this."""
        self.env.restore(0, snap.state)
        self.env.observe()
        self.gs, self.done = copy.deepcopy(snap.gs), False
        self.builder.prev = self.gs
        for c in self.controllers.values():
            c.release_all()
            c.flush()
        return self.gs

    def close(self) -> None:
        self.env.close()
