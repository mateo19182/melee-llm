"""Brains that run in another virtualenv, one process each, spoken to over its stdin and stdout.

The farm sends each frame as raw bytes (simulator rows, input rows, flags) and gets back one raw input row per seat,
so the two sides share no Python objects and may run different Python, numpy and libmelee versions. The child is
`python -m farm.remote` in the bot's own venv.
"""
import os
import pickle
import struct
import subprocess
import sys

import numpy as np

from .common import LIVE, REPO, SIM, Frame

PROTOCOL = 4  # readable by every venv's Python
KINDS = {  # kind -> (python, working directory, module:class)
    "phillip": (LIVE / "vendor/slippi-ai/.venv/bin/python", LIVE / "vendor/slippi-ai", "farm.phillip:PhillipBrain"),
    "hal": (LIVE / "vendor/hal/.venv/bin/python", LIVE / "vendor/hal", "farm.hal:HALBrain"),
}


def send(stream, obj):
    data = pickle.dumps(obj, protocol=PROTOCOL)
    stream.write(struct.pack("<Q", len(data)) + data)
    stream.flush()


def receive(stream):
    head = stream.read(8)
    if len(head) < 8:
        raise EOFError("brain process closed its pipe")
    (n,) = struct.unpack("<Q", head)
    return pickle.loads(stream.read(n))


def pack(frame):
    return {"obs": frame.obs.tobytes(), "inputs": frame.inputs.tobytes(), "has_input": frame.has_input.tobytes(),
            "fresh": frame.fresh.tobytes(), "active": frame.active.tobytes(), "events": frame.events}


def unpack(msg, obs_dtype, input_dtype):
    return Frame(np.frombuffer(msg["obs"], obs_dtype), np.frombuffer(msg["inputs"], input_dtype),
                 np.frombuffer(msg["has_input"], bool), np.frombuffer(msg["fresh"], bool),
                 np.frombuffer(msg["active"], bool), msg["events"])


class RemoteBrain:
    """The farm's handle on a brain process. `submit` sends a frame without waiting, `collect` reads the rows, so
    several brains (and the local Faynt step) work on the same frame at once."""

    def __init__(self, kind, spec, seats, seed=0, check=False, **options):
        python, cwd, target = KINDS[kind]
        env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(REPO / "train"), str(REPO), str(SIM)])}
        self.proc = subprocess.Popen([str(python), "-m", "farm.remote"], cwd=cwd, env=env, stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE)
        self.seats = [tuple(s) for s in seats]
        send(self.proc.stdin, {"target": target, "spec": spec, "seats": self.seats, "seed": seed, "check": check,
                               "options": options})
        reply = receive(self.proc.stdout)
        if "error" in reply:
            raise RuntimeError(f"{kind} brain failed to start:\n{reply['error']}")
        self.from_events = reply["from_events"]
        from .common import player_dtype
        self.dtype = player_dtype()

    def submit(self, frame):
        send(self.proc.stdin, {"frame": pack(frame)})

    def collect(self):
        reply = receive(self.proc.stdout)
        if "error" in reply:
            raise RuntimeError(f"brain process failed:\n{reply['error']}")
        return np.frombuffer(reply["rows"], self.dtype)

    def act(self, frame):
        self.submit(frame)
        return self.collect()

    def report(self):
        send(self.proc.stdin, {"report": True})
        return receive(self.proc.stdout).get("report")

    def close(self):
        if self.proc.poll() is None:
            try:
                send(self.proc.stdin, {"close": True})
                self.proc.wait(timeout=30)
            except (BrokenPipeError, subprocess.TimeoutExpired):
                self.proc.kill()


def serve():
    import importlib
    import traceback

    from melee_sim import dtypes

    stdin, stdout = sys.stdin.buffer, sys.stdout.buffer
    sys.stdout = sys.stderr  # the bot's own prints must not reach the pipe
    init = receive(stdin)
    try:
        module, _, cls = init["target"].partition(":")
        brain = getattr(importlib.import_module(module), cls)(init["spec"], init["seats"], init["seed"], init["check"],
                                                             **init["options"])
    except Exception:
        send(stdout, {"error": traceback.format_exc()})
        return
    send(stdout, {"ok": True, "from_events": brain.from_events})
    obs_dtype, input_dtype = dtypes.gamestate_dtype(), dtypes.input_dtype()
    while True:
        msg = receive(stdin)
        if "close" in msg:
            return
        if "report" in msg:
            send(stdout, {"report": brain.report()})
            continue
        try:
            rows = brain.act(unpack(msg["frame"], obs_dtype, input_dtype))
            send(stdout, {"rows": rows.tobytes()})
        except Exception:
            send(stdout, {"error": traceback.format_exc()})
            return


if __name__ == "__main__":
    serve()
