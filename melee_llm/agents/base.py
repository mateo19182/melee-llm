"""The contract every player type implements.

A match calls `setup` once, then `step` on every in-game frame. `step` presses buttons on
`self.controller`; the runner flushes it. In `paused` matches Dolphin blocks on our input, so
`step` may take as long as it likes (the game waits). In `live` matches `step` must return within
~16 ms; slow thinking has to run off-thread and leave a fast executor in charge of the controller.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import melee


@dataclass
class Agent:
    character: melee.Character = melee.Character.FOX
    cpu_level: int = 0  # >0: the in-game CPU plays this port and step() is never called
    costume: int = 0

    def setup(self, controller: melee.Controller, port: int, opponent_port: int) -> None:
        self.controller, self.port, self.opponent_port = controller, port, opponent_port

    def on_game_start(self, gs: melee.GameState, replay: Path | None) -> None:
        """First in-game frame. `replay` is the .slp Slippi just started writing (None if not found)."""

    def step(self, gs: melee.GameState) -> None:
        pass

    def on_game_end(self, gs: melee.GameState | None) -> None:
        pass

    def close(self) -> None:
        pass

    @property
    def name(self) -> str:
        return f"cpu{self.cpu_level}" if self.cpu_level else type(self).__name__


class CPU(Agent):
    def __init__(self, level: int = 9, character: melee.Character = melee.Character.FOX):
        super().__init__(character=character, cpu_level=level)


class Idle(Agent):
    def step(self, gs):
        self.controller.release_all()


class Multishine(Agent):
    def step(self, gs):
        melee.techskill.multishine(ai_state=gs.players[self.port], controller=self.controller)
