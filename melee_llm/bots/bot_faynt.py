"""Faynt (frisson-labs) inside vendor/Faynt-Tournament/.venv.

Observation path matches Faynt-Tournament's native runtime (src/melee_policy/integration/
frisson_policy.py): slippi-ai's libmelee Parser (same Game schema as the pinned 577965a) ->
structured tensors -> one cached step per frame, zero added delay, 256-frame ring cache.

config `own: true` makes the model read its own last pad as its controller instead of the one the game applied, for
a bot whose pads land late (stomped.dev): Faynt has no delay input, and reading a pad older than its last one breaks
it (farm.faynt's own=1, E32).
"""
from __future__ import annotations

import sys
from pathlib import Path

import melee
import numpy as np
import torch
from slippi_db.parse_libmelee import Parser
from transformers import AutoModel

WEIGHTS = Path("weights")
BUTTONS = ("A", "B", "X", "Y", "Z", "L", "R", "D_UP")
CORE = ("percent", "facing", "x", "y", "action", "invulnerable", "character", "jumps_left", "shield_strength",
        "on_ground")
NANA = ("exists", *CORE)


def controller_of(c):
    """A packed pad (main x/y, c x/y, shoulder, buttons) as slippi-ai's parsed Controller."""
    from slippi_ai.types import Buttons, Controller, Stick

    f = np.float32
    return Controller(main_stick=Stick(f(c[0]), f(c[1])), c_stick=Stick(f(c[2]), f(c[3])), shoulder=f(c[4]),
                      buttons=Buttons(*(np.bool_(v > 0.5) for v in c[5:])))


NEUTRAL = controller_of([0.5, 0.5, 0.5, 0.5, 0.0] + [0.0] * len(BUTTONS))


class Bot:
    def __init__(self, init: dict):
        cfg = init["config"]
        path = WEIGHTS / f"Faynt-{cfg['model']}"
        if not path.exists():
            raise ValueError(f"no Faynt weights at {path}; have {self.available()}")
        self.name = cfg["model"]
        # The native step is host-bound (~80 small tensors, many validation syncs): eager CUDA takes
        # ~12 ms/frame on this box, CPU with 8 threads ~7 ms, CUDA + inductor ~8 ms.
        self.device = torch.device(cfg.get("device", "cpu"))
        torch.set_num_threads(cfg.get("threads", 8))
        self.model = AutoModel.from_pretrained(str(path), trust_remote_code=True).eval().to(self.device)
        self.step = torch.compile(self.model.step) if cfg.get("compile") else self.model.step
        self.tb = sys.modules[type(self.model).__module__]  # the remote code's tensor_batch classes
        self.generator = torch.Generator(device=self.device).manual_seed(cfg.get("seed") or 0)
        self.ports = (init["port"], init["opponent_port"])
        self.steer = {"temperature": 1.0}
        self.parser = self.cache = None
        self.own, self.last = bool(cfg.get("own")), None

    @staticmethod
    def available() -> list[str]:
        return sorted(p.name.removeprefix("Faynt-") for p in WEIGHTS.glob("Faynt-*"))

    def info(self) -> dict:
        cfg = self.model.config
        return {"model": f"Faynt-{self.name}", "device": str(self.device), "stage": cfg.training_stage, "context_frames": cfg.context_length,
                "params_m": round(sum(p.numel() for p in self.model.parameters()) / 1e6, 1),
                "available": self.available(), "steer": dict(self.steer)}

    def set_steer(self, steer: dict) -> dict:
        t = float(steer.get("temperature", self.steer["temperature"]))
        if not t > 0:
            raise ValueError("temperature must be > 0")
        self.steer = {"temperature": t}
        return dict(self.steer)

    def _tensors(self, game):
        tb, dev = self.tb, self.device

        def t(v):
            return torch.as_tensor(v, device=dev).reshape(1)

        def controller(c):
            return tb.ControllerBatch(
                main_stick=tb.StickBatch(t(c.main_stick.x), t(c.main_stick.y)),
                c_stick=tb.StickBatch(t(c.c_stick.x), t(c.c_stick.y)), shoulder=t(c.shoulder),
                buttons=tb.ButtonsBatch(**{b: t(getattr(c.buttons, b)) for b in BUTTONS}))

        def player(p):
            return tb.PlayerBatch(**{f: t(getattr(p, f)) for f in CORE}, controller=controller(p.controller),
                                  nana=tb.NanaBatch(**{f: t(getattr(p.nana, f)) for f in NANA}))

        items = [getattr(game.items, f"item_{i}") for i in range(15)]
        state = tb.GameStateBatch(
            p0=player(game.p0), p1=player(game.p1), stage=t(game.stage),
            randall=tb.RandallBatch(t(game.randall.x), t(game.randall.y)),
            fod_platforms=tb.FoDPlatformsBatch(t(game.fod_platforms.left), t(game.fod_platforms.right)),
            items=tb.ItemsBatch(**{f: torch.stack([t(getattr(it, f)) for it in items], -1)
                                   for f in ("exists", "type", "state", "x", "y")}))
        return state, state.p0.controller

    @torch.inference_mode()
    def act(self, gs, controller, open_loop: bool) -> None:
        reset = self.parser is None or gs.frame == -123
        if reset:
            self.parser = Parser(ports=self.ports)
            self.cache = self.model.init_cache(1, device=self.device)
        game = self.parser.get_game(gs)
        if self.own:
            game = game._replace(p0=game.p0._replace(controller=self.last if self.last and not reset else NEUTRAL))
        state, current = self._tensors(game)
        out = self.step(game_state_t=state, controller_t=current, cache=self.cache,
                              reset_mask=torch.tensor([reset], device=self.device),
                              temperature=self.steer["temperature"], generator=self.generator)
        self.cache = out.cache
        c = out.controller.as_packed_tensor().reshape(-1).tolist()  # main x/y, c x/y, shoulder, A B X Y Z L R D_UP
        self.last = controller_of(c)
        B = melee.enums.Button
        controller.tilt_analog(B.BUTTON_MAIN, c[0], c[1])
        controller.tilt_analog(B.BUTTON_C, c[2], c[3])
        controller.press_shoulder(B.BUTTON_L, c[4])
        for name, v in zip(BUTTONS, c[5:]):
            (controller.press_button if v > 0.5 else controller.release_button)(B[f"BUTTON_{name}"])
