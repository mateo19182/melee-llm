"""Reyn-26C (frisson-labs) inside vendor/Reyn/.venv: a language-steerable policy for all 26 characters.

Observation path is Faynt's: slippi-ai's libmelee Parser -> the Game tree (p0 = this bot) -> one cached
step per frame, zero added delay. `steer["command"]` is a phrase (or None to clear); the router's reply
comes back in applied_steer["reply"]. An "abstain" keeps the previous command active.
"""
from __future__ import annotations

from pathlib import Path

import melee
import numpy as np
import torch
from reyn import Reyn
from reyn.language.context import CHARACTERS
from reyn.language.stages import by_model_id
from slippi_db.parse_libmelee import Parser

WEIGHTS = Path("model-files")
BUTTONS = ("A", "B", "X", "Y", "Z", "L", "R", "D_UP")
CONTEXT = {v: k for k, v in CHARACTERS.items()}  # libmelee internal character id -> Reyn key


def _nest(nt):
    return {k: _nest(v) for k, v in nt._asdict().items()} if hasattr(nt, "_asdict") else nt


def _tree(game) -> dict:
    """slippi-ai Game namedtuple -> Reyn's input tree: nested dicts, items as (15,) arrays per field."""
    tree = _nest(game._replace(items=None))
    items = [getattr(game.items, f"item_{i}") for i in range(15)]
    tree["items"] = {f: np.array([getattr(it, f) for it in items]) for f in ("exists", "type", "state", "x", "y")}
    return tree


class Bot:
    def __init__(self, init: dict):
        cfg = init["config"]
        self.device = torch.device(cfg.get("device", "cpu"))
        torch.set_num_threads(cfg.get("threads", 4))
        char = melee.Character[init["character"]]
        if char.value not in CONTEXT:
            raise ValueError(f"Reyn has no context for {char.name}")
        self.model = Reyn.load(cfg.get("weights", WEIGHTS), device=self.device, character=CONTEXT[char.value],
                               seed=cfg.get("seed") or 0)
        self.ports = (init["port"], init["opponent_port"])
        self.steer = {"command": None, "temperature": 1.0}
        self.reply: dict | None = None
        self.stage: str | None = None
        self.parser = None

    def info(self) -> dict:
        return {"model": "Reyn-26C", "device": str(self.device), "character": self.model.character,
                "params_m": round(sum(p.numel() for m in self.model.modules for p in m.parameters()) / 1e6, 1),
                "steer": self.applied()}

    def active(self) -> str | None:
        return self.model._steering.holding

    def applied(self) -> dict:
        return {**self.steer, "active": self.active(), "reply": self.reply}

    def set_steer(self, steer: dict) -> dict:
        t = float(steer.get("temperature", self.steer["temperature"]))
        if not t > 0:
            raise ValueError("temperature must be > 0")
        self.steer["temperature"] = t
        if "command" in steer and steer["command"] != self.steer["command"]:
            cmd = steer["command"]
            r = self.model.clear() if not cmd else self.model.say(str(cmd), stage=self.stage)
            self.reply = {"said": cmd, "outcome": r.outcome, "row": r.row, "name": r.name, "changed": r.changed,
                          "score": round(float(r.score), 3), "reason": r.reason}
            self.steer["command"] = cmd
        return self.applied()

    def _reset_keep_command(self, context: str) -> None:
        """New game or character switch (Sheik/Zelda): fresh history, same held command."""
        s = self.model._steering
        current, holding = s.current, s.holding
        self.model.reset(character=context)
        s.current, s.holding = current, holding

    @torch.inference_mode()
    def act(self, gs, controller, open_loop: bool) -> None:
        if self.parser is None or gs.frame == -123:
            self.parser = Parser(ports=self.ports)
            self._reset_keep_command(self.model.character)
            try:
                self.stage = by_model_id(gs.stage.value).name
            except KeyError:
                self.stage = None
        tree = _tree(self.parser.get_game(gs))
        context = CONTEXT.get(int(tree["p0"]["character"]))
        if context and context != self.model.character:
            self._reset_keep_command(context)
        c = self.model.predict(tree, temperature=self.steer["temperature"]).action.reshape(-1).tolist()
        B = melee.enums.Button
        controller.tilt_analog(B.BUTTON_MAIN, c[0], c[1])
        controller.tilt_analog(B.BUTTON_C, c[2], c[3])
        controller.press_shoulder(B.BUTTON_L, c[4])
        for name, v in zip(BUTTONS, c[5:]):
            (controller.press_button if v > 0.5 else controller.release_button)(B[f"BUTTON_{name}"])
