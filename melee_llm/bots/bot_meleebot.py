"""Our own behaviour-cloned bot (lane B, train/meleebot) inside train/.venv.

Checkpoints live in data/train/runs/<run>/last.pt. Features come from the raw Slippi bytes, exactly
as the dataset was built (meleebot.play.RawFrames), so this Bot ignores most of libmelee's GameState.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.getcwd())  # cwd is train/, home of the meleebot package

from meleebot.play import Policy  # noqa: E402

import melee  # noqa: E402

B = melee.enums.Button
BUTTONS = ("BUTTON_A", "BUTTON_B", "BUTTON_X", "BUTTON_Z", "BUTTON_L")


class Bot:
    def __init__(self, init: dict):
        cfg = init["config"]
        # A fixed seed against a deterministic CPU replays the same game; default to a fresh one.
        seed = cfg["seed"] if cfg.get("seed") is not None else int.from_bytes(os.urandom(4), "little")
        self.policy = Policy(cfg["checkpoint"], init["port"], init["opponent_port"],
                             device=cfg.get("device"), threads=cfg.get("threads", 8), seed=seed)
        self.checkpoint, self.seed = cfg["checkpoint"], seed

    def info(self) -> dict:
        ck = self.policy.ckpt
        return {"model": self.checkpoint, "device": self.policy.device, "step": ck.get("step"), "seed": self.seed,
                "params_m": round(ck.get("params", 0) / 1e6, 1), "steer": dict(self.policy.steer),
                "ranges": {"delay": [0, 12], "rank": ["UNKNOWN", "PLATINUM", "DIAMOND", "MASTER", "PRO"],
                           "win": [0, 1, None], "temperature": "> 0"}}

    def set_steer(self, steer: dict) -> dict:
        return self.policy.set_steer(steer)

    def act(self, gs, controller, open_loop: bool) -> None:
        ctrl = self.policy.act(gs)
        if ctrl is None:
            return
        controller.tilt_analog(B.BUTTON_MAIN, *ctrl["main"])
        controller.tilt_analog(B.BUTTON_C, *ctrl["c"])
        controller.press_shoulder(B.BUTTON_L, ctrl["l"])
        controller.press_shoulder(B.BUTTON_R, ctrl["r"])
        for name in BUTTONS:
            (controller.press_button if name in ctrl["buttons"] else controller.release_button)(B[name])
