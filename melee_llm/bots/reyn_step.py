"""Static-shape re-implementation of `Reyn.predict` for real-time play (one CUDA graph per frame).

Upstream `predict` dispatches ~1,000 small ops per frame, syncs on validation checks and copies the whole
KV ring into chronological order in every layer: 10 ms on a quiet CPU, 20-40 ms under load, worse on CUDA.
This step reuses the same loaded modules and weights, but:
- validates and packs the observation on the host into two flat buffers (one H2D copy each);
- attends over the ring buffer in place with a validity mask (keys are stored after RoPE, so slot order
  does not matter);
- decodes labels and re-encodes `previous` through lookup tables built from the upstream codec;
- samples by inverse CDF from host-drawn uniforms instead of `torch.multinomial`: same distribution, no
  device RNG, so the whole step can be captured as one CUDA graph and replayed.
On CPU the same step runs eagerly. The taunt head is evaluated every frame but drawn on the host, only when
the held command enables it, exactly as upstream does.
"""
from __future__ import annotations

import numpy as np
import torch
import torch.nn.functional as F
from reyn.codec import ControllerLabels
from reyn.model import SlippiEncoder as E
from reyn.state_adapter import _CLIP, _UNIT
from reyn.taunt import draw

PLAYER_INT = ("percent", "action", "character", "jumps_left", "facing", "invulnerable", "on_ground")
PLAYER_FLOAT = ("x", "y", "shield_strength")
SLOTS = (("p0", False), ("p0", True), ("p1", False), ("p1", True))  # (player, is nana)
ITEMS = 15
# int buffer: 4 slots x (7 fields + nana exists) | stage | command | items type, state, exists
N_INT = 4 * 8 + 2 + 3 * ITEMS
# float buffer: 4 slots x 3 | randall x, y | fod left, right | temperature | 2 uniforms | items x, y
N_FLOAT = 4 * 3 + 4 + 1 + 2 + 2 * ITEMS
OUT = 13 + 2 + 1  # packed controller, (buttons, main) labels, taunt logit


def pack(tree: dict, command: int, temperature: float, uniforms: np.ndarray,
         ints: np.ndarray, floats: np.ndarray) -> None:
    """Fill the host buffers from Reyn's observation tree (same dtype casts as `prepare_input`)."""
    for s, (player, nana) in enumerate(SLOTS):
        p = tree[player]["nana"] if nana else tree[player]
        ints[8 * s:8 * s + 8] = [*(int(p[k]) for k in PLAYER_INT), bool(p["exists"]) if nana else 1]
        floats[3 * s:3 * s + 3] = [p[k] for k in PLAYER_FLOAT]
    i, f = 32, 12
    ints[i], ints[i + 1] = int(tree["stage"]), command
    it = tree["items"]
    ints[i + 2:i + 2 + ITEMS] = it["type"]
    ints[i + 2 + ITEMS:i + 2 + 2 * ITEMS] = it["state"]
    ints[i + 2 + 2 * ITEMS:] = np.asarray(it["exists"], dtype=bool)
    floats[f:f + 6] = (tree["randall"]["x"], tree["randall"]["y"], tree["fod_platforms"]["left"],
                       tree["fod_platforms"]["right"], temperature, uniforms[0])
    floats[f + 6] = uniforms[1]
    floats[f + 7:f + 7 + ITEMS] = it["x"]
    floats[f + 7 + ITEMS:] = it["y"]
    chars, jumps = ints[[2, 10, 18, 26]], ints[[3, 11, 19, 27]]
    if ((chars < 0) | (chars >= E.CHARACTER_SIZE)).any():
        raise ValueError("character index is outside the upstream [0, 33) vocabulary")
    if ((jumps < 0) | (jumps >= E.JUMPS_SIZE)).any():
        raise ValueError("jumps_left is outside the upstream [0, 7) vocabulary")
    if not 0 <= ints[32] < E.STAGE_SIZE:
        raise ValueError("stage is invalid for the 64-way vocabulary")


class FastStep:
    """Per-frame policy step over a loaded `reyn.Reyn`. Call `reset()` whenever the model is reset."""

    def __init__(self, model, *, cuda_graph: bool = True):
        self.model = model
        self.device = model.device
        trunk = model.trunk
        self.enc, self.backbone, self.head, codec = trunk.encoder, trunk.backbone, trunk.controller_head, trunk.codec
        cfg = trunk.config
        if any(d != torch.float32 for d in (cfg.torch_compute_dtype, cfg.torch_cache_dtype)):
            raise ValueError("FastStep implements the float32 release only")
        dev = self.device
        nb, nm = codec.vocabulary_sizes
        with torch.inference_mode():
            b, m = torch.arange(nb), torch.arange(nm)
            dec_b = codec.decode(ControllerLabels(b, torch.zeros_like(b))).as_packed_tensor()
            dec_m = codec.decode(ControllerLabels(torch.zeros_like(m), m)).as_packed_tensor()
            self.ctrl_b, self.ctrl_m = dec_b[:, 2:].to(dev), dec_m[:, :2].to(dev)
            self.enc_b, self.enc_m = codec.encode(dec_b).buttons.to(dev), codec.encode(dec_m).main_stick.to(dev)
            shape = (cfg.n_layers, 1, cfg.context_length, cfg.n_kv_heads, cfg.head_dim)
            self.keys, self.values = torch.zeros(shape, device=dev), torch.zeros(shape, device=dev)
            self.slot_valid = torch.zeros(cfg.context_length, dtype=torch.bool, device=dev)
            self.write = torch.zeros(1, dtype=torch.long, device=dev)
            self.position = torch.zeros(1, 1, dtype=torch.long, device=dev)
            self.prev = torch.zeros(2, dtype=torch.long, device=dev)
            self.ints = torch.zeros(N_INT, dtype=torch.long, device=dev)
            self.floats = torch.zeros(N_FLOAT, dtype=torch.float32, device=dev)
            self.out = torch.zeros(OUT, device=dev)
        pin = dev.type == "cuda"
        self.h_ints = torch.zeros(N_INT, dtype=torch.long, pin_memory=pin)
        self.h_floats = torch.zeros(N_FLOAT, dtype=torch.float32, pin_memory=pin)
        self.h_out = torch.zeros(OUT, pin_memory=pin)
        self.n_ints, self.n_floats = self.h_ints.numpy(), self.h_floats.numpy()
        self.rng = np.random.default_rng(model._seed)
        self.graph = None
        if cuda_graph and dev.type == "cuda":
            self._capture()
        self.reset()

    def reset(self) -> None:
        with torch.inference_mode():
            for t in (self.keys, self.values, self.slot_valid, self.write, self.position, self.prev):
                t.zero_()
        self.rng = np.random.default_rng(self.model._seed)

    def _capture(self) -> None:
        with torch.inference_mode():
            side = torch.cuda.Stream()
            side.wait_stream(torch.cuda.current_stream())
            with torch.cuda.stream(side):
                for _ in range(3):
                    self._forward()
            torch.cuda.current_stream().wait_stream(side)
            self.graph = torch.cuda.CUDAGraph()
            with torch.cuda.graph(self.graph):
                self._forward()

    def _player(self, base: int, fbase: int, nana: bool) -> torch.Tensor:
        enc, ints, floats = self.enc, self.ints, self.floats
        percent, action, character, jumps = (ints[base + k:base + k + 1] for k in range(4))
        facing, invulnerable, on_ground, exists = (ints[base + k:base + k + 1] for k in range(4, 8))
        x, y, shield = (floats[fbase + k:fbase + k + 1] for k in range(3))
        action = action.clamp(0, E.ACTION_SIZE - 1)
        action_embed = enc.action_embedding(action) + enc.character_action_embedding(character * E.ACTION_SIZE + action)
        parts = [
            enc._scaled_float(torch.remainder(percent, 1 << 16), 0.01),
            torch.where(facing > 0, 1.0, -1.0).unsqueeze(-1),
            enc._scaled_float(x, 0.05),
            enc._scaled_float(y, 0.05),
            action_embed,
            (invulnerable > 0).float().unsqueeze(-1),
            enc.character_embedding(character),
            F.one_hot(jumps, E.JUMPS_SIZE).float(),
            enc._scaled_float(shield, 0.01),
            (on_ground > 0).float().unsqueeze(-1),
        ]
        if nana:
            parts.append((exists > 0).float().unsqueeze(-1))
        return torch.cat([p.float() for p in parts], dim=-1)

    def _facts(self) -> torch.Tensor:
        """`reyn.state_adapter.state_features` from the packed buffers."""
        ints, floats = self.ints, self.floats
        x, y, his_x, his_y = floats[0:1] / _UNIT, floats[1:2] / _UNIT, floats[6:7] / _UNIT, floats[7:8] / _UNIT
        dx, dy = his_x - x, his_y - y
        facing = (ints[4:5] > 0).float() * 2.0 - 1.0
        his_facing = (ints[20:21] > 0).float() * 2.0 - 1.0
        return torch.stack((x, y, his_x, his_y, dx, dy, dx.abs(), x.abs(), facing, his_facing,
                            facing * torch.tanh(dx * 20.0), ints[0:1].float() / _UNIT, ints[16:17].float() / _UNIT,
                            (ints[6:7] > 0).float(), (ints[22:23] > 0).float(), ints[3:4].float() / 2.0),
                           dim=-1).clamp(-_CLIP, _CLIP)

    def _encode(self) -> torch.Tensor:
        enc, ints, floats = self.enc, self.ints, self.floats
        players = [self._player(8 * s, 3 * s, nana) for s, (_, nana) in enumerate(SLOTS)]
        it_type, it_state, exists = ints[34:34 + ITEMS], ints[34 + ITEMS:34 + 2 * ITEMS], ints[34 + 2 * ITEMS:] > 0
        it_type = torch.where((it_type >= 0) & (it_type < E.ITEM_TYPE_INPUT_SIZE), it_type, E.ITEM_TYPE_INPUT_SIZE)
        it_state = torch.where((it_state >= 0) & (it_state < E.ITEM_STATE_INPUT_SIZE), it_state,
                               E.ITEM_STATE_INPUT_SIZE)
        item_x, item_y = floats[19:19 + ITEMS], floats[19 + ITEMS:]
        items = torch.cat((exists.float().unsqueeze(-1), F.one_hot(it_type, E.ITEM_TYPE_SIZE).float(),
                           F.one_hot(it_state, E.ITEM_STATE_SIZE).float(), enc._scaled_float(item_x, 0.05),
                           enc._scaled_float(item_y, 0.05)), dim=-1)
        items = torch.where(exists.unsqueeze(-1), enc.item_mlp(items), 0.0).sum(dim=-2).float().unsqueeze(0)
        nb, nm = enc.codec.vocabulary_sizes
        parts = [*players, F.one_hot(ints[32:33], E.STAGE_SIZE).float(),
                 *(enc._scaled_float(floats[12 + k:13 + k], 0.05) for k in range(4)), items,
                 F.one_hot(self.prev[0:1], nb).float(), F.one_hot(self.prev[1:2], nm).float()]
        return torch.cat(parts, dim=-1)

    def _backbone(self, encoded: torch.Tensor) -> torch.Tensor:
        bb = self.backbone
        self.slot_valid.index_fill_(0, self.write, True)
        mask = self.slot_valid[None, None, None, :]
        values = [bb.input_projection(encoded).unsqueeze(1)]
        for i, layer in enumerate(bb.layers):
            att = layer.attention
            normed = layer.attention_norm(layer.attention_residual(values))
            q, k, v = att._project(normed, self.position)
            self.keys[i].index_copy_(1, self.write, k.transpose(1, 2))
            self.values[i].index_copy_(1, self.write, v.transpose(1, 2))
            out = att._sdpa(q, self.keys[i].permute(0, 2, 1, 3), self.values[i].permute(0, 2, 1, 3),
                            attention_mask=mask, is_causal=False)
            values.append(att._apply_output_gate(out, normed))
            values.append(bb._ffn_transform(layer, layer.ffn_residual(values)))
        hidden = bb.final_norm(bb.output_residual(values)).squeeze(1)
        self.write.copy_(torch.remainder(self.write + 1, bb.config.context_length))
        self.position.add_(1)
        return hidden

    def _sample(self, hidden: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        head, floats = self.head, self.floats
        residual = head.to_residual(hidden)
        temperature = floats[16]
        chosen = []
        for j, name in enumerate(head.codec.component_order):
            component = head.components[name]
            logits = component.logits(residual, self.prev[j:j + 1])
            cdf = torch.softmax(logits.float() / temperature, dim=-1).cumsum(-1)
            choice = (cdf < floats[17 + j] * cdf[:, -1:]).sum(-1).clamp(max=logits.shape[-1] - 1)
            chosen.append(choice)
            residual = component.update(residual, choice)
        return chosen[0], chosen[1]

    def _forward(self) -> None:
        m = self.model
        hidden = self.backbone_hidden = self._backbone(self._encode())
        command = self.ints[33:34]
        facts = self._facts()
        index = command.clamp(min=0)
        conditioned = m.attachment(hidden, m.features.tokens[index], m.features.mask[index], command >= 0)
        conditioned = conditioned + m.state_adapter(hidden, command, facts)
        buttons, main = self._sample(conditioned)
        taunt = m.taunt(torch.cat((hidden, facts.to(hidden.dtype)), dim=-1), command)
        self.out.copy_(torch.cat((self.ctrl_m[main], self.ctrl_b[buttons],
                                  torch.stack((buttons, main), -1).float(), taunt.unsqueeze(-1)), dim=-1)[0])
        self.prev.copy_(torch.cat((self.enc_b[buttons], self.enc_m[main])))

    @torch.inference_mode()
    def __call__(self, tree: dict, temperature: float = 1.0) -> list[float]:
        """One frame: returns the 13 packed controller values (upstream `Action.action` order)."""
        if not temperature > 0:
            raise ValueError("temperature must be finite and positive")
        m = self.model
        command = m.current
        pack(tree, command, temperature, self.rng.random(2), self.n_ints, self.n_floats)
        self.ints.copy_(self.h_ints, non_blocking=True)
        self.floats.copy_(self.h_floats, non_blocking=True)
        if self.graph is not None:
            self.graph.replay()
        else:
            self._forward()
        self.h_out.copy_(self.out)  # synchronizes
        out = self.h_out.tolist()
        controller = out[:13]
        if m.taunt.enables([command]):
            active = torch.tensor([True])
            if bool(draw(torch.tensor(out[15:16]), active, m._taunt_generator)[0]):
                controller = [0.5] * 4 + [0.0] * 9
                controller[12] = 1.0
                labels = m.trunk.codec.encode(torch.tensor([controller]))
                with torch.inference_mode():
                    self.prev.copy_(torch.cat((labels.buttons, labels.main_stick)).to(self.device))
        m._first = False
        return controller
