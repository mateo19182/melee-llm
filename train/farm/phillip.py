"""Phillip (slippi-ai) in the farm: slippi-ai's own delayed agent, built as the live bot builds it, with a batch.

Runs in vendor/slippi-ai's venv (farm.remote). Each seat reads what the live bot (melee_llm/bots/bot_phillip.py, which
calls eval_lib.Agent) reads: slippi-ai's Parser turns the seat's GameState into a Game with itself as p0. One
DelayedAgent steps every seat of a model; its delay queue (18-24 frames) and recurrent state are per row.

The published ONNX exports take one game at a time. farm/phillip_onnx.py rewrites a copy to take a batch, cached in
BATCHED; it is checked here against the original, row for row, before use.
"""
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np

from .common import LIVE, Brain, row, stack

MODELS = LIVE / "vendor/slippi-ai/models"
BATCHED = Path("/mnt/data/melee/phillip-batched")


def batched_model(name):
    """Path of the batch-capable copy of a published model, made (and checked) on first use. Workers that start
    together take turns through a lock file, so each model is converted once."""
    import fcntl

    dst = BATCHED / f"{name}.onnx"
    BATCHED.mkdir(parents=True, exist_ok=True)
    with open(BATCHED / ".lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if not dst.exists():
            tmp = dst.with_suffix(".tmp.onnx")
            uv = shutil.which("uv") or str(Path.home() / ".local/bin/uv")
            subprocess.run([uv, "run", "--no-project", "--quiet", "--with", "onnx", "--with", "numpy", "python",
                            str(Path(__file__).with_name("phillip_onnx.py")), str(MODELS / f"{name}.onnx"), str(tmp)],
                           check=True, stdout=sys.stderr)
            check_batched(MODELS / f"{name}.onnx", tmp)
            tmp.rename(dst)
    return dst


def check_batched(original, batched, batch=8, trials=4):
    """The batched graph gives every row exactly what the original gives that row alone."""
    import onnxruntime as ort

    from slippi_ai import onnx_policies

    policy = onnx_policies.load_policy_from_state(onnx_policies.load_state_from_disk(str(original)))
    temperature = next(leaf for leaf in policy.input_layout["inputs.float32"] if leaf.name == "temperature")
    options = ort.SessionOptions()
    options.log_severity_level = 3
    one = ort.InferenceSession(str(original), options, providers=["CPUExecutionProvider"])
    many = ort.InferenceSession(str(batched), options, providers=["CPUExecutionProvider"])
    rng = np.random.default_rng(0)
    kinds = {"tensor(int32)": np.int32, "tensor(bool)": bool, "tensor(float)": np.float32}
    for _ in range(trials):
        feed = {}
        for i in one.get_inputs():
            shape, kind = (batch, i.shape[1]), kinds[i.type]
            feed[i.name] = (rng.integers(0, 3, shape).astype(kind) if kind is np.int32 else
                            rng.random(shape) < 0.3 if kind is bool else rng.random(shape).astype(kind))
        feed["inputs.float32"][:, temperature.offset] = 1.0  # one temperature for the batch, as OnnxAgent packs it
        together = many.run(None, feed)
        alone = [one.run(None, {k: v[r:r + 1] for k, v in feed.items()}) for r in range(batch)]
        for j, out in enumerate(together):
            want = np.concatenate([a[j] for a in alone])
            # sampled actions must match exactly; float outputs may differ by summation order (multi-threaded
            # matmuls split a batch differently: super-gm with 4 threads, 4e-6 of its largest value)
            same = (np.allclose(out, want, rtol=0, atol=1e-5 * max(1.0, float(np.abs(want).max())))
                    if out.dtype.kind == "f" else np.array_equal(out, want))
            if not same:
                raise RuntimeError(f"{batched}: output {j} differs from the original's")


class PhillipBrain(Brain):
    """One Phillip model playing all its seats (spec `phillip:MODEL[,temperature=T]`)."""

    def __init__(self, spec, seats, seed=0, check=False, threads=4):
        super().__init__(seats, check)
        from slippi_ai import eval_lib, onnx_policies

        from melee_llm.bots.bot_phillip import _pin_onnx_threads

        name, *options = spec.partition(":")[2].split(",")
        o = dict(x.split("=", 1) for x in options)
        name = name or "gm"
        _pin_onnx_threads(threads)
        state = onnx_policies.load_state_from_disk(str(MODELS / f"{name}.onnx"))
        state["onnx_model"] = batched_model(name).read_bytes()
        state["onnx_metadata"] = {**state["onnx_metadata"], "batch_size": None}
        # As eval_lib.build_agent does for the live bot (bot_phillip: name=None, console_delay=0), with a batch.
        self.agent = eval_lib.build_delayed_agent(
            state, console_delay=0, name=None, batch_size=len(self.seats),
            onnx={"seed": seed, "providers": ["CPUExecutionProvider"]},
            sample_temperature=float(o.get("temperature", 1.0)))
        self.agent.warmup()
        self.send = eval_lib.send_controller
        self.parsers = [None] * len(self.seats)
        self.delay = self.agent.delay

    def reader(self, port):
        from slippi_db.parse_libmelee import Parser

        return Parser(ports=(port, 3 - port)).get_game

    def _forget(self, rows):
        """A new game in these rows: the actions queued from the last game become the neutral controller, as for a
        bot that has just started."""
        dummy = self.agent.dummy_sample_outputs.controller_state
        for queued in self.agent._output_queue:
            for (_, leaf), (_, empty) in zip(_leaves(queued.controller_state), _leaves(dummy)):
                leaf[rows] = empty[rows]

    def decide(self, states, frame):
        reset = np.zeros(len(self.seats), bool)
        for i, (lane, port) in enumerate(self.seats):
            if lane not in states:
                continue
            if frame.fresh[lane] or self.parsers[i] is None:
                self.parsers[i], reset[i] = self.reader(port), True
            self.last_read[i] = self.parsers[i](states[lane])
        if reset.any():
            self._forget(reset)
        outputs = self.agent.step(stack(self.last_read), reset)
        actions = self.agent.policy.controller_head.decode_controller(outputs.controller_state)
        for i, (lane, _) in enumerate(self.seats):
            if lane in states:
                self.send(self.controllers[i], row(actions, i))


def _leaves(tree, path=()):
    if hasattr(tree, "_fields"):
        for f in tree._fields:
            yield from _leaves(getattr(tree, f), (*path, f))
    else:
        yield path, tree
