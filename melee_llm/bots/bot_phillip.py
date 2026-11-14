"""Phillip (vladfi1/slippi-ai) ONNX exports inside vendor/slippi-ai/.venv, via slippi_ai.eval_lib.Agent."""
from __future__ import annotations

from pathlib import Path

import numpy as np
from slippi_ai import eval_lib, saving

MODELS = Path("models")


def _pin_onnx_threads(n: int) -> None:
    # onnxruntime's default thread pool spikes to 25+ ms a step on some CPUs (e.g. the 12-core Ryzen AI laptop);
    # a fixed count is steady. slippi_ai builds its SessionOptions itself, so set it on every one.
    import onnxruntime as ort

    base = ort.SessionOptions

    def options():
        o = base()
        o.intra_op_num_threads = n
        return o

    ort.SessionOptions = options


class Bot:
    def __init__(self, init: dict):
        cfg = init["config"]
        path = MODELS / f"{cfg['model']}.onnx"
        if not path.exists():
            raise ValueError(f"no Phillip model {path}; have {self.available()}")
        self.model = cfg["model"]
        if cfg.get("threads"):
            _pin_onnx_threads(int(cfg["threads"]))
        self.state = saving.load_state_from_disk(str(path))
        self.agent = eval_lib.build_agent(
            port=init["port"], opponent_port=init["opponent_port"], state=self.state, name=None,
            console_delay=0, onnx={"seed": cfg.get("seed")})
        self.basic = self.agent._agent._agent  # OnnxAgent: holds the name code, rating and temperature
        policy = self.agent._agent.policy
        self.delay = policy.delay
        summary = eval_lib.AgentSummary.from_state(self.state)
        self.characters = [c.name for c in summary.characters]
        self.opponents = [c.name for c in summary.opponents]
        if init["character"] not in self.characters:
            raise ValueError(f"{self.model} plays {self.characters}, not {init['character']}")
        rl_names = eval_lib.get_name_from_rl_state(self.state) or []
        self.steer = {"name": rl_names[0] if rl_names else None, "rating": self.basic.rating,
                      "temperature": float(self.basic._temperature)}
        self.controller_set = False
        self.ports = (init["port"], init["opponent_port"])

    @staticmethod
    def available() -> list[str]:
        return sorted(p.stem for p in MODELS.glob("*.onnx"))

    def info(self) -> dict:
        return {"model": self.model, "delay_frames": self.delay, "characters": self.characters,
                "opponents": self.opponents, "names": sorted(self.state["name_map"]),
                "trained_names": eval_lib.get_name_from_rl_state(self.state),
                "providers": self.basic.runner.providers, "available": self.available(), "steer": dict(self.steer)}

    def set_steer(self, steer: dict) -> dict:
        # All three are inputs to every ONNX step, so they apply from the next frame's decision,
        # which reaches the controller `delay` (18-24) frames later.
        new = {**self.steer, **{k: v for k, v in steer.items() if k in self.steer and v is not None}}
        if new["name"] is not None and self.state["name_map"]:
            self.basic.set_name_code(eval_lib.get_name_code(self.state, new["name"]))
        if new["rating"] is not None:
            self.basic._rating = float(new["rating"])
        self.basic._temperature = np.array(float(new["temperature"]), dtype=np.float32)
        self.steer = new
        return dict(new)

    def act(self, gs, controller, open_loop: bool) -> None:
        if not self.controller_set:
            self.agent.set_controller(controller)
            self.controller_set = True
        if len(gs.players) > 2:  # slippi_ai's parser asserts a 1v1; extra humans (play.py --humans) stay unseen
            gs.players = {p: gs.players[p] for p in self.ports}
        self.agent.step(gs)
