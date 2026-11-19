"""A small student of HAL's model, shaped to play fast with input delay.

HAL (247M) handles delay in its decoder: the actions already sent are fed back as a forced prefix and it decodes on
from there, 48 tokens and 8 sampling passes per decision at 10 frames of delay. A 10M model of that shape plays no
faster than the big one (docs/experiments/E24-sim-farm.md and the entry that follows it). The student keeps what
makes HAL's data and checks reusable and changes how delay is handled:

- Same input: HAL's own code turns a frame (both players, items, stage, the action applied on it) into a token, and
  HAL's trunk blocks run over the frames. Only the sizes differ.
- The actions already sent are an input. With d frames of delay, seeing the game up to frame t, the d actions
  for t+1..t+d and the number d go into a small head together with the trunk's output for t.
- The head outputs one action, for frame t+d+1: the only one the bot has to choose. Its four controller groups
  are picked in HAL's order, each knowing the ones before.

The trunk never sees d, so one pass over a game trains every delay, and in play its cache is shared by all of them.
"""
import dataclasses

import torch
import torch.nn.functional as F
from torch import nn


class Student(nn.Module):
    def __init__(self, hal_config, vocabulary, width=256, layers=6, heads=8, context=128, head_layers=2, max_delay=11):
        super().__init__()
        from hal.models.action_sequence import ActionSequenceTransformer
        from hal.models.controller_codec import (CONTROLLER_DECODE_ORDER, CONTROLLER_GROUP_INDEX,
                                                 controller_group_vocabs)

        cfg = dataclasses.replace(
            hal_config, d_model=width, n_layers=layers, n_heads=heads, L_ctx=context,
            # HAL's decoder is built and dropped: its constructor is the only way to get the frame encoder and trunk
            temporal_d_model=width, temporal_layers=1, temporal_heads=heads, temporal_ff_dim=width, group_head_dim=width)
        self.body = ActionSequenceTransformer(cfg, vocabulary)
        del self.body.temporal, self.body.value_head
        self.cfg, self.max_delay = cfg, max_delay
        self.order = tuple(CONTROLLER_DECODE_ORDER)
        self.index = dict(CONTROLLER_GROUP_INDEX)
        vocab = dict(zip(sorted(self.index, key=self.index.get), controller_group_vocabs(cfg.main_stick_layout)))
        self.pending = nn.Linear(len(self.index) * cfg.action_embed_dim, width)
        self.slot = nn.Embedding(max_delay, width)
        self.delay = nn.Embedding(max_delay + 1, width)
        block = nn.TransformerEncoderLayer(width, heads, 4 * width, dropout=0.0, activation="gelu", batch_first=True,
                                           norm_first=True)
        self.fuse = nn.TransformerEncoder(block, head_layers, enable_nested_tensor=False)
        self.norm = nn.LayerNorm(width)
        self.chosen = nn.ModuleDict({name: nn.Embedding(vocab[name], width) for name in self.order})
        self.out = nn.ModuleDict({name: nn.Linear(width, vocab[name]) for name in self.order})

    def hidden(self, features, ctx_pad, action_indices=None):
        """The trunk's output for every frame of a window: [B, L, width]."""
        return self.body(features, ctx_pad, action_indices)

    def fused(self, hidden, pending, delay):
        """What the head knows when it chooses: [N, width].

        hidden [N, width]: the trunk's output for the last frame seen. pending [N, max_delay, groups]: the actions
        already sent, oldest first, as class indices; rows use their first `delay` slots. delay [N].
        """
        slots = torch.arange(self.max_delay, device=hidden.device)
        sent = self.pending(self.body.codec.embed_frame(pending).to(hidden.dtype)) + self.slot(slots)
        tokens = torch.cat([(hidden + self.delay(delay))[:, None], sent], dim=1)
        unused = F.pad(slots[None] >= delay[:, None], (1, 0))
        return self.norm(self.fuse(tokens, src_key_padding_mask=unused)[:, 0])

    def logits(self, fused, action):
        """Each group's logits given the groups before it in `action` [N, groups] (teacher forcing)."""
        out, x = {}, fused
        for name in self.order:
            out[name] = self.out[name](x)
            x = x + self.chosen[name](action[:, self.index[name]])
        return out

    @torch.no_grad()
    def sample(self, fused, generator=None, temperature=1.0):
        """An action [N, groups] of class indices."""
        action = torch.zeros(len(fused), len(self.index), dtype=torch.long, device=fused.device)
        x = fused
        for name in self.order:
            probabilities = torch.softmax(self.out[name](x).float() / temperature, -1)
            pick = torch.multinomial(probabilities, 1, generator=generator)[:, 0]
            action[:, self.index[name]] = pick
            x = x + self.chosen[name](pick)
        return action

    def parameters_m(self):
        """Millions of parameters, without HAL's table of player identities (the student plays one)."""
        return (sum(p.numel() for p in self.parameters()) - self.body.player_embedding.weight.numel()) / 1e6


class Cache:
    """The trunk's attention keys and values for the last `context` frames of B games, so a new frame costs one token."""

    def __init__(self, student, batch, device="cuda", dtype=torch.bfloat16):
        cfg = student.cfg
        self.capacity = cfg.L_ctx
        self.layers = [torch.zeros(2, batch, cfg.n_heads, self.capacity, cfg.d_model // cfg.n_heads, device=device,
                                   dtype=dtype) for _ in range(cfg.n_layers)]
        self.position = torch.full((batch, self.capacity), -1, device=device, dtype=torch.long)
        self.next = torch.zeros(batch, device=device, dtype=torch.long)
        self.rows = torch.arange(batch, device=device)

    def reset(self, rows):
        """Start a new game on `rows` (a bool mask or indices)."""
        self.position[rows] = -1
        self.next[rows] = 0

    @torch.no_grad()
    def step(self, student, tokens):
        """Add one frame per game (tokens [B, width], from body.context_tokens) and return the trunk's output for it."""
        from hal.models.attention import rmsnorm, rotate_positions

        slot = self.next % self.capacity
        self.position[self.rows, slot] = self.next
        valid = (self.position >= 0)[:, None, None]  # the ring holds exactly the last `capacity` frames
        at = self.next[:, None]
        x = tokens[:, None]
        for block, kv in zip(student.body.trunk.blocks, self.layers, strict=True):
            attn = block.attn
            q, k, v = attn.c_attn(rmsnorm(x)).chunk(3, dim=-1)
            shape = (len(x), 1, attn.n_heads, attn.head_dim)
            q = rotate_positions(q.view(shape), at, attn.rotary).transpose(1, 2)
            k = rotate_positions(k.view(shape), at, attn.rotary).transpose(1, 2)
            kv[0][self.rows, :, slot] = k[:, :, 0]
            kv[1][self.rows, :, slot] = v.view(shape).transpose(1, 2)[:, :, 0]
            attended = F.scaled_dot_product_attention(q, kv[0], kv[1], attn_mask=valid)
            x = x + block.attn_scale * attn.c_proj(attended.transpose(1, 2).reshape(len(x), 1, attn.d_model))
            x = x + block.mlp_scale * block.mlp(rmsnorm(x))
        self.next += 1
        return rmsnorm(x)[:, 0]
