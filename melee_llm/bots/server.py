"""Child process for one bot: `<bot venv python> server.py <bot>`, speaking protocol.py on stdin/stdout.

Runs under the bot's own venv, so it may import only the stdlib, that venv's packages, and the
sibling modules in this directory (protocol.py, bot_<name>.py). Never imports melee_llm.
"""
from __future__ import annotations

import importlib
import os
import sys
import time
import traceback
from collections import deque
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import protocol  # noqa: E402


class EventStream:
    """Stands in for libmelee's SLPFileStreamer: hands the Console the parent's raw messages."""

    def __init__(self):
        self.queue: deque = deque()
        self.playedOn = self.timestamp = self.consoleNick = ""
        self.players: dict = {}

    def dispatch(self, *args, **kwargs):
        return self.queue.popleft() if self.queue else None

    def connect(self):
        return True

    def shutdown(self):
        pass

    def interrupt(self):
        pass


class Replayer:
    """Rebuilds GameStates with this venv's libmelee from the parent's raw Slippi events."""

    def __init__(self):
        import melee
        self.console = melee.Console(is_dolphin=False, path=os.devnull, allow_old_version=True)
        self.stream = EventStream()
        self.console._slippstream = self.stream

    def feed(self, events):
        self.stream.queue.extend({"type": t, "payload": p} for t, p in events)
        latest = None
        while self.stream.queue:
            gs = self.console.step()
            if gs is None:
                break
            latest = gs
        return latest


class RecordingController:
    """The subset of melee.Controller that bot code calls; records the final state instead of piping it."""

    def __init__(self, port: int):
        self.port = port
        self.release_all()

    def release_all(self):
        self.main, self.c, self.l, self.r = (0.5, 0.5), (0.5, 0.5), 0.0, 0.0
        self.buttons: set[str] = set()

    def press_button(self, button):
        self.buttons.add(button.name)

    def release_button(self, button):
        self.buttons.discard(button.name)

    def tilt_analog(self, button, x, y):
        if button.name == "BUTTON_MAIN":
            self.main = (float(x), float(y))
        elif button.name == "BUTTON_C":
            self.c = (float(x), float(y))

    def press_shoulder(self, button, amount):
        if button.name == "BUTTON_L":
            self.l = float(amount)
        elif button.name == "BUTTON_R":
            self.r = float(amount)

    def flush(self):
        pass

    def snapshot(self) -> dict:
        return {"main": self.main, "c": self.c, "l": self.l, "r": self.r, "buttons": sorted(self.buttons)}


def main() -> None:
    out = os.fdopen(os.dup(1), "wb", buffering=0)
    os.dup2(2, 1)  # library prints go to stderr, never into the protocol stream
    sys.stdout = sys.stderr
    inp = os.fdopen(0, "rb", buffering=0)

    init = protocol.recv(inp)
    try:
        module = importlib.import_module(f"bot_{sys.argv[1]}")
        bot = module.Bot(init)
        bot.set_steer(init.get("steer") or {})
        replayer = Replayer()
        controller = RecordingController(init["port"])
    except Exception:
        protocol.send(out, {"ok": False, "error": traceback.format_exc()})
        return
    protocol.send(out, {"ok": True, "info": bot.info()})

    while True:
        try:
            msg = protocol.recv(inp)
        except EOFError:
            return
        if msg["op"] == "close":
            return
        reply = {"ctrl": None, "frame": None, "ms": 0.0, "steer": None, "error": None}
        try:
            if msg.get("steer") is not None:
                reply["steer"] = bot.set_steer(msg["steer"])
            gs = replayer.feed(msg["events"])
            if gs is not None and gs.players:
                t0 = time.perf_counter()
                bot.act(gs, controller, open_loop=msg.get("open_loop", False))
                reply["ms"] = (time.perf_counter() - t0) * 1000
                reply["ctrl"], reply["frame"] = controller.snapshot(), int(gs.frame)
        except Exception:
            reply["error"] = traceback.format_exc()
        protocol.send(out, reply)


if __name__ == "__main__":
    main()
