"""Faynt in the farm: one batched model step a frame for all the seats of one checkpoint, recorded as a CUDA graph.

Each seat reads what the live Faynt bot (melee_llm/bots/bot_faynt.py) reads on Dolphin: slippi-ai's Parser turns the
seat's GameState into a Game with itself as p0, and the chosen controller is pressed as the bot presses it.
Runs in the farm's own process (Faynt's venv).
"""
import dataclasses

import numpy as np
import torch

from .common import LIVE, Brain

WEIGHTS = LIVE / "vendor/Faynt-Tournament/weights"
BUTTONS = ("A", "B", "X", "Y", "Z", "L", "R", "D_UP")


def batched_cache(model):
    """Replace Faynt's cached attention, which loops over the batch in Python (two .item() syncs and a gather per
    row per layer), with one indexed write and a mask. Keys carry their RoPE positions and softmax attention does not
    depend on key order, so attending to the ring in slot order instead of chronological order is the same function
    up to float summation order. After a reset slots fill from 0, so the live slots are those below the length."""

    cls = type(model.policy.backbone.layers[0].attention)
    if getattr(cls, "_batched", False):
        return

    def forward_cached(self, normalized_inputs, positions, cache, valid_mask):
        queries, keys, values = self._project(normalized_inputs, positions)
        valid = valid_mask.to(device=cache.keys.device, dtype=torch.bool)
        rows = torch.arange(cache.batch_size, device=cache.keys.device)
        write = cache.write_position.long()
        layer_k, layer_v = cache.keys[self.layer_index], cache.values[self.layer_index]
        layer_k[rows, write] = torch.where(valid[:, None, None], keys[:, :, 0].to(layer_k.dtype), layer_k[rows, write])
        layer_v[rows, write] = torch.where(valid[:, None, None], values[:, :, 0].to(layer_v.dtype), layer_v[rows, write])
        lengths = torch.clamp(cache.valid_length + valid.long(), max=cache.capacity)
        key_valid = torch.arange(cache.capacity, device=cache.keys.device)[None] < lengths[:, None]
        mask = key_valid[:, None, None, :] & valid[:, None, None, None]
        head_output = self._sdpa(queries, layer_k.permute(0, 2, 1, 3).to(queries.dtype),
                                 layer_v.permute(0, 2, 1, 3).to(queries.dtype), attention_mask=mask, is_causal=False)
        head_output = torch.where(valid[:, None, None, None], head_output, 0.0)
        return self._apply_output_gate(head_output, normalized_inputs)

    cls.forward_cached, cls._batched = forward_cached, True


def _leaves(tree, path=()):
    """(path, tensor) for every tensor in a tensor_batch dataclass tree."""
    if dataclasses.is_dataclass(tree):
        for f in dataclasses.fields(tree):
            yield from _leaves(getattr(tree, f.name), (*path, f.name))
    else:
        yield path, tree


def _column(games, path):
    """One input field for every seat, from slippi-ai Games (self as p0), as a numpy array."""
    if path[0] == "items":
        return np.array([[getattr(getattr(g.items, f"item_{i}"), path[1]) for i in range(15)] for g in games])
    values = []
    for g in games:
        v = g
        for name in path:
            v = getattr(v, name)
        values.append(v)
    return np.array(values)


class GraphStep:
    """Faynt's batched step recorded once as a CUDA graph and replayed every frame.

    The model checks its inputs with Python-side reads of GPU tensors (`bool(x.any())`), which a graph cannot
    contain. A warm-up step runs those checks for real on valid inputs and records their answers; while recording
    the graph, tensor truth values replay those answers in order. Every such check guards a `raise` (and the cache
    reset is replaced by a masked one), so control flow does not depend on the data and the recorded graph is the
    model's arithmetic alone. The constant tables the codec builds with `torch.tensor` each step are likewise
    the warm-up's, kept alive for the graph. Sampling draws from the default CUDA generator, which graphs support."""

    def __init__(self, model, batch, temperature, seed=0):

        batched_cache(model)
        kv = type(model.init_cache(1, device="cuda"))
        if not getattr(kv, "_masked_reset", False):
            def reset_slots(self, reset_mask):
                reset = reset_mask.to(device=self.keys.device, dtype=torch.bool)
                self.keys.masked_fill_(reset.view(1, -1, 1, 1, 1), 0)
                self.values.masked_fill_(reset.view(1, -1, 1, 1, 1), 0)
                for t in (self.valid_length, self.write_position, self.next_position):
                    t.masked_fill_(reset, 0)
            kv.reset_slots, kv._masked_reset = reset_slots, True
        self.model, self.temperature = model, temperature
        example = model.example_inputs(batch, None, device="cuda")
        self.state = example["game_state_t"]
        self.inputs = list(_leaves(self.state))
        self.reset = torch.zeros(batch, dtype=torch.bool, device="cuda")
        self.cache = model.init_cache(batch, device="cuda")
        torch.cuda.manual_seed(seed)

        def run():
            with torch.inference_mode():
                out = model.step(game_state_t=self.state, controller_t=self.state.p0.controller, cache=self.cache,
                                 reset_mask=self.reset, temperature=temperature)
            self.button_logits = out.logits["buttons"]
            return out.controller.as_packed_tensor().reshape(batch, -1)

        truth, build, answers, constants = torch.Tensor.__bool__, torch.tensor, [], []

        def recording_truth(t):
            answers.append(truth(t))
            return answers[-1]

        def recording_build(*args, **kwargs):
            constants.append(build(*args, **kwargs))
            return constants[-1]

        side = torch.cuda.Stream()
        side.wait_stream(torch.cuda.current_stream())
        with torch.cuda.stream(side):
            run()
            torch.Tensor.__bool__, torch.tensor = recording_truth, recording_build
            try:
                run()
            finally:
                torch.Tensor.__bool__, torch.tensor = truth, build
        torch.cuda.current_stream().wait_stream(side)
        replay_truth, replay_build = iter(answers), iter(constants)
        self.constants = constants  # the graph reads them: keep them alive
        self.graph = torch.cuda.CUDAGraph()
        torch.Tensor.__bool__ = lambda t: next(replay_truth)
        torch.tensor = lambda *args, **kwargs: next(replay_build)
        try:
            with torch.cuda.graph(self.graph):
                self.out = run()
        finally:
            torch.Tensor.__bool__, torch.tensor = truth, build
        if next(replay_truth, None) is not None or next(replay_build, None) is not None:
            raise RuntimeError("the recorded step took a different path from the warm-up step")
        self.fresh = True  # the warm-up wrote history: the first real frame restarts every row

    def load(self, games):
        """Copy one frame of inputs (slippi-ai Games, one per seat) into the recorded input tensors."""

        for path, tensor in self.inputs:
            tensor.copy_(torch.from_numpy(_column(games, path)).to(tensor.dtype), non_blocking=True)

    def step(self, reset):
        """Advance every row one frame; rows with `reset` start a new game. Returns the packed controllers on the
        GPU: main x/y, c x/y, shoulder, A B X Y Z L R D_UP."""

        self.reset.copy_(torch.from_numpy(np.asarray(reset, dtype=bool) | self.fresh), non_blocking=True)
        self.fresh = False
        self.graph.replay()
        return self.out

    def __call__(self, games, reset):
        self.load(games)
        return self.step(reset).float().cpu().numpy()


class EagerStep:
    """The same step without a graph: for checking GraphStep, and a fallback if capture fails."""

    def __init__(self, model, batch, temperature, seed=0):

        batched_cache(model)
        self.model, self.temperature = model, temperature
        self.state = model.example_inputs(batch, None, device="cuda")["game_state_t"]
        self.inputs = list(_leaves(self.state))
        self.cache = model.init_cache(batch, device="cuda")
        self.generator = torch.Generator(device="cuda").manual_seed(seed)

    def __call__(self, games, reset):

        for path, tensor in self.inputs:
            tensor.copy_(torch.from_numpy(_column(games, path)).to(tensor.dtype), non_blocking=True)
        with torch.inference_mode():
            out = self.model.step(game_state_t=self.state, controller_t=self.state.p0.controller, cache=self.cache,
                                  reset_mask=torch.as_tensor(np.asarray(reset, dtype=bool)).cuda(),
                                  temperature=self.temperature, generator=self.generator)
        return out.controller.as_packed_tensor().reshape(len(reset), -1).float().cpu().numpy()


def press(controller, c):
    import melee

    B = melee.enums.Button
    controller.tilt_analog(B.BUTTON_MAIN, c[0], c[1])
    controller.tilt_analog(B.BUTTON_C, c[2], c[3])
    controller.press_shoulder(B.BUTTON_L, c[4])
    for name, v in zip(BUTTONS, c[5:]):
        (controller.press_button if v > 0.5 else controller.release_button)(B[f"BUTTON_{name}"])



class FayntBrain(Brain):
    """One Faynt checkpoint playing all its seats (spec `faynt:VARIANT[,temperature=T]`)."""

    def __init__(self, spec, seats, seed=0, check=False, graph=True):
        from transformers import AutoModel

        super().__init__(seats, check)
        variant, *options = spec.partition(":")[2].split(",")
        o = dict(x.split("=", 1) for x in options)
        self.model = AutoModel.from_pretrained(str(WEIGHTS / f"Faynt-{variant or '10M-Arena'}"),
                                               trust_remote_code=True).eval().cuda()
        temperature = float(o.get("temperature", 1.0))
        self.step = (GraphStep if graph else EagerStep)(self.model, len(self.seats), temperature, seed)
        self.parsers = [None] * len(self.seats)

    def reader(self, port):
        from slippi_db.parse_libmelee import Parser

        return Parser(ports=(port, 3 - port)).get_game

    def decide(self, states, frame):
        reset = np.zeros(len(self.seats), bool)
        for i, (lane, port) in enumerate(self.seats):
            if lane not in states:
                continue  # finished: the batch keeps its last frame
            if frame.fresh[lane] or self.parsers[i] is None:
                self.parsers[i], reset[i] = self.reader(port), True
            self.last_read[i] = self.parsers[i](states[lane])
        actions = self.step(self.last_read, reset)
        for i, (lane, _) in enumerate(self.seats):
            if lane in states:
                press(self.controllers[i], actions[i])
