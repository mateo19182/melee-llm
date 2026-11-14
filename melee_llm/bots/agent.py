"""Main-process side: an Agent that runs a learned bot in a subprocess under the bot's own venv.

The parent stays dependency-light (no torch/onnx): it forwards the raw Slippi events its Console
consumed, and applies the controller state the child sends back. See protocol.py.
"""
from __future__ import annotations

import base64
import statistics
import subprocess
import time
from pathlib import Path

import melee

from melee_llm.agents.base import Agent
from melee_llm.bots import protocol
from melee_llm.paths import VENDOR  # noqa: F401 - re-exported for the bot classes

SERVER = Path(__file__).resolve().parent / "server.py"
APPLIED_BUTTONS = [melee.Button[n] for n in ("BUTTON_A", "BUTTON_B", "BUTTON_X", "BUTTON_Y", "BUTTON_Z",
                                             "BUTTON_L", "BUTTON_R", "BUTTON_D_UP")]


class ConsoleTap:
    """Copies every raw Slippi message a Console dispatches into each subscriber's list.

    Wraps the instance's `_slippstream.dispatch` (a private libmelee attribute, stable across
    0.45-0.47). One tap per console, shared by every bot in the match.
    """

    def __init__(self, console: melee.Console):
        self.subscribers: list[list] = []
        stream = console._slippstream
        dispatch = stream.dispatch

        def tapped(*args, **kwargs):
            msg = dispatch(*args, **kwargs)
            if msg is not None and msg["type"] in ("game_event", "frame_end"):
                payload = msg.get("payload", b"")
                raw = base64.b64decode(payload) if isinstance(payload, str) else bytes(payload)
                for sub in self.subscribers:
                    sub.append((msg["type"], raw))
            return msg

        stream.dispatch = tapped

    @classmethod
    def of(cls, console: melee.Console) -> ConsoleTap:
        if not hasattr(console, "_melee_llm_tap"):
            console._melee_llm_tap = cls(console)
        return console._melee_llm_tap

    def subscribe(self) -> list:
        self.subscribers.append([])
        return self.subscribers[-1]


def apply_controller(controller, ctrl: dict) -> None:
    controller.tilt_analog(melee.Button.BUTTON_MAIN, *ctrl["main"])
    controller.tilt_analog(melee.Button.BUTTON_C, *ctrl["c"])
    controller.press_shoulder(melee.Button.BUTTON_L, ctrl["l"])
    controller.press_shoulder(melee.Button.BUTTON_R, ctrl["r"])
    pressed = set(ctrl["buttons"])
    for b in APPLIED_BUTTONS:
        (controller.press_button if b.name in pressed else controller.release_button)(b)


class BotAgent(Agent):
    """Base for subprocess bots. Subclasses set `bot`, `python` and `cwd`.

    `steer` is a plain dict the coach may mutate at any time; changes are sent with the next frame.
    Before setup it holds only explicit overrides; after setup, every knob's effective value.
    `applied_steer` is what the bot last confirmed (it may add read-only keys, e.g. identity_active).
    `open_loop` (tests only) tells bots not to assert that their last action was executed.
    """

    bot = ""
    python: Path
    cwd: Path

    def __init__(self, arg: str | None = None, *, character: melee.Character = melee.Character.FOX,
                 steer: dict | None = None, **config):
        super().__init__(character=character)
        self.arg, self.config = arg, config
        self.steer = dict(steer or {})
        self.open_loop = False
        self.info: dict = {}
        self.applied_steer: dict = {}
        self.round_trip_ms: list[float] = []
        self.model_ms: list[float] = []
        self.errors = 0
        self._proc = None
        self._asked = None  # (steer sent, send time) of the frame the child is working on

    @property
    def name(self) -> str:
        return f"{self.bot}:{self.arg}" if self.arg else self.bot

    def init_config(self) -> dict:
        """Bot-specific init payload; subclasses resolve `arg` and `character` here."""
        return dict(self.config)

    def setup(self, controller, port: int, opponent_port: int) -> None:
        super().setup(controller, port, opponent_port)
        self._events = ConsoleTap.of(controller._console).subscribe()
        self._start()

    def _start(self) -> None:
        if not self.python.exists():
            raise RuntimeError(f"{self.bot}: missing venv {self.python}; see docs/bots.md")
        self._proc = subprocess.Popen([str(self.python), str(SERVER), self.bot], cwd=self.cwd,
                                      stdin=subprocess.PIPE, stdout=subprocess.PIPE, bufsize=0)
        protocol.send(self._proc.stdin, {
            "op": "init", "port": self.port, "opponent_port": self.opponent_port,
            "character": self.character.name, "config": self.init_config(), "steer": dict(self.steer)})
        reply = protocol.recv(self._proc.stdout)
        if not reply["ok"]:
            self.close()
            raise RuntimeError(f"{self.bot} failed to start:\n{reply['error']}")
        self.info = reply["info"]
        self.applied_steer = self.info.get("steer", {})
        self.steer = dict(self.applied_steer)
        self._sent_steer = dict(self.steer)

    def begin(self, gs: melee.GameState) -> None:
        """Send the frame. The runner does this for both players before either `step`, so two bots infer at
        the same time and a frame costs the slower one, not the sum."""
        events = self._events[:]
        del self._events[:]
        steer = None if self.steer == self._sent_steer else dict(self.steer)
        self._asked = (steer, time.perf_counter())
        protocol.send(self._proc.stdin, {"op": "step", "events": events, "steer": steer,
                                         "open_loop": self.open_loop})

    def step(self, gs: melee.GameState) -> None:
        if self._asked is None:  # called without begin(): tests, bots/bench.py, netplay
            self.begin(gs)
        (steer, t0), self._asked = self._asked, None
        reply = protocol.recv(self._proc.stdout)
        self.round_trip_ms.append((time.perf_counter() - t0) * 1000)
        if steer is not None:
            self._sent_steer = steer
            if reply["steer"] is not None:
                self.applied_steer = reply["steer"]
        if reply["error"]:
            self.errors += 1
            if self.errors <= 3:
                print(f"[{self.name} p{self.port}] {reply['error']}")
        if reply["ctrl"] is None:
            return
        if reply["frame"] != gs.frame:
            raise RuntimeError(f"{self.name}: bot saw frame {reply['frame']}, game is at {gs.frame}")
        self.model_ms.append(reply["ms"])
        apply_controller(self.controller, reply["ctrl"])

    def latency(self) -> dict:
        def summary(xs):
            if not xs:
                return {}
            s = sorted(xs)
            pick = lambda q: round(s[min(len(s) - 1, int(q * len(s)))], 2)  # noqa: E731
            return {"n": len(s), "mean": round(statistics.fmean(s), 2), "p50": pick(.5), "p95": pick(.95),
                    "p99": pick(.99), "max": round(s[-1], 2)}
        return {"round_trip_ms": summary(self.round_trip_ms), "model_ms": summary(self.model_ms)}

    def close(self) -> None:
        if self._proc is None:
            return
        try:
            protocol.send(self._proc.stdin, {"op": "close"})
            self._proc.wait(timeout=10)
        except (OSError, subprocess.TimeoutExpired):
            self._proc.kill()
        self._proc = None
