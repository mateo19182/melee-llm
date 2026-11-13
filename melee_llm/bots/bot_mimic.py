"""MIMIC (erickfm/MIMIC) inside vendor/MIMIC/.venv. Mirrors tools/play.py's per-frame loop."""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, os.getcwd())  # cwd is vendor/MIMIC

import torch  # noqa: E402

from tools.inference_utils import (  # noqa: E402
    PlayerState, build_frame, build_frame_p2, build_mock_frame, decode_and_press, is_window_model,
    load_inference_context, load_mimic_model, set_cond_temperature,
)
from tools.play import _make_ctx  # noqa: E402

WEIGHTS = Path("hf_checkpoints")
# Default checkpoint per character; any downloaded dir (fox-master, fox-diamond...) can be chosen by name.
BY_CHARACTER = {"FOX": "fox", "FALCO": "falco", "MARTH": "marth", "SHEIK": "sheik", "CPTFALCON": "cptfalcon",
                "LUIGI": "luigi", "PEACH": "peach", "JIGGLYPUFF": "puff"}


class Bot:
    def __init__(self, init: dict):
        name = init["config"].get("model") or BY_CHARACTER.get(init["character"])
        if name is None or not (WEIGHTS / name / "model.pt").exists():
            raise ValueError(f"no MIMIC checkpoint for {init['character']} ({name}); have {self.available()}")
        self.name = name
        self.model, self.cfg = load_mimic_model(str(WEIGHTS / name / "model.pt"), "cuda")
        self.ctx = _make_ctx(load_inference_context(WEIGHTS / name), self.cfg)
        self.ego_first = init["port"] < init["opponent_port"]  # build_frame orders players by port
        self.compiled = init["config"].get("compile", True) and not is_window_model(self.model)
        if self.compiled:
            # Full-causal models recompute the whole 180-frame window every frame; CUDA graphs cut
            # that from ~3.5 ms (launch-bound) to ~1.3 ms. Outputs match eager to ~1e-6.
            torch.set_num_threads(1)
            self.model = torch.compile(self.model, mode="reduce-overhead")
            warm = PlayerState(self.model, self.cfg.max_seq_len, "cuda", ctx=self.ctx)
            for _ in range(5):
                warm.push_frame(build_mock_frame(self.ctx))
                with torch.no_grad():
                    warm.predict()
        self.steer = {"temperature": 1.0, "top_k": 0, "top_p": 0.0}
        self.state = None

    @staticmethod
    def available() -> list[str]:
        return sorted(p.parent.name for p in WEIGHTS.glob("*/model.pt"))

    def info(self) -> dict:
        return {"model": self.name, "params_m": round(sum(p.numel() for p in self.model.parameters()) / 1e6, 1),
                "context_frames": self.cfg.max_seq_len, "cuda_graphs": self.compiled, "available": self.available(),
                "steer": dict(self.steer)}

    def set_steer(self, steer: dict) -> dict:
        new = {**self.steer, **{k: v for k, v in steer.items() if k in self.steer}}
        new["temperature"], new["top_k"], new["top_p"] = (
            float(new["temperature"]), int(new["top_k"]), float(new["top_p"]))
        if new["temperature"] < 0 or new["top_k"] < 0 or not 0 <= new["top_p"] < 1:
            raise ValueError(f"invalid MIMIC sampling {new}")
        self.steer = new
        set_cond_temperature(self.model, new["temperature"])
        return dict(new)

    def act(self, gs, controller, open_loop: bool) -> None:
        if self.state is None or gs.frame == -123:
            self.state = PlayerState(self.model, self.cfg.max_seq_len, "cuda", ctx=self.ctx)
        frame = (build_frame if self.ego_first else build_frame_p2)(gs, self.state.prev_sent, self.ctx)
        if frame is None:
            return
        self.state.push_frame(frame)
        with torch.no_grad():
            preds = self.state.predict()
        self.state.prev_sent, _, _ = decode_and_press(controller, preds, self.state.prev_sent, **self.steer)
