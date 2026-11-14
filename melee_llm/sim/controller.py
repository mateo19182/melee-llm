"""A melee.Controller with no Dolphin behind it: agents press buttons exactly as they would live, and each
frame `raw_input()` turns the controller state into the integers the game reads, as Dolphin does.

libmelee's Controller pre-distorts stick and trigger values (fix_analog_inputs) so that Dolphin's
conversion lands on a chosen integer: Dolphin reads a stick as floor((v - 0.5) * 254) and a trigger as
floor(v * 255). `current` holds the distorted stick values but the *undistorted* trigger amounts (that is
how libmelee's tilt_analog and press_shoulder store them), so triggers are distorted here before
Dolphin's conversion. The result is the raw input a bot would produce live.
"""
from __future__ import annotations

import copy
import math

import melee
from melee import enums
from melee.controller import fix_analog_trigger

from melee_llm.sim.state import _BUTTON_BITS


def _stick(v: float) -> int:
    return max(-80, min(80, math.floor((v - 0.5) * 254)))  # melee_sim takes the [-80, 80] range Melee clamps to


def _trigger(v: float) -> int:
    return max(0, min(255, math.floor(v * 255)))


class SimController(melee.Controller):
    def __init__(self, port: int, fix_analog_inputs: bool = True):  # noqa: super().__init__ needs a Dolphin console
        self.port = port
        self.prev, self.current = melee.ControllerState(), melee.ControllerState()
        self.logger, self.pipe, self.pipe_path = None, True, None
        self._type, self._fix_analog_inputs = enums.ControllerType.STANDARD, fix_analog_inputs

    def connect(self) -> bool:
        return True

    def disconnect(self) -> None:
        pass

    def _write(self, command) -> None:
        pass

    def flush(self) -> None:
        self.prev = copy.copy(self.current)

    def raw_input(self, out) -> None:
        """Write this frame's input into one melee_sim raw input row (buttons, main_x/y, c_x/y, l, r)."""
        cur = self.current
        out["buttons"] = sum(bit for b, bit in _BUTTON_BITS.items() if cur.button.get(b))
        out["main_x"], out["main_y"] = _stick(cur.main_stick[0]), _stick(cur.main_stick[1])
        out["c_x"], out["c_y"] = _stick(cur.c_stick[0]), _stick(cur.c_stick[1])
        fix = fix_analog_trigger if self._fix_analog_inputs else (lambda v: v)
        out["l"], out["r"] = _trigger(fix(cur.l_shoulder)), _trigger(fix(cur.r_shoulder))
