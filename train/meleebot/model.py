"""Causal transformer over frames; four controller heads predicted in order, each seeing the earlier ones.

Positions: "rope" (rotary, relative) lets play run one cached step per frame (`step`); "learned"
(absolute, bc-6m-v1) needs the whole window recomputed every frame.
"""
from dataclasses import asdict, dataclass

import torch
import torch.nn as nn
import torch.nn.functional as F

from . import features as fe
from .schema import CHARACTERS, RANKS


@dataclass
class Config:
    layers: int = 6
    width: int = 256
    heads: int = 8
    context: int = 256
    dropout: float = 0.1
    n_stick: int = 40
    pos: str = "learned"


HEADS = ("shoulder", "cstick", "stick", "buttons")


def rope(x, pos):
    """Rotate (B, H, T, Dh) by absolute positions (T,); computed in float32, games run to ~30k frames."""
    half = x.shape[-1] // 2
    freq = 10000 ** (-torch.arange(half, device=x.device, dtype=torch.float32) / half)
    ang = pos.to(torch.float32)[:, None] * freq
    cos, sin = ang.cos(), ang.sin()
    x1, x2 = x[..., :half].float(), x[..., half:].float()
    return torch.cat([x1 * cos - x2 * sin, x1 * sin + x2 * cos], -1).to(x.dtype)


class Block(nn.Module):
    def __init__(self, c):
        super().__init__()
        self.ln1, self.ln2 = nn.LayerNorm(c.width), nn.LayerNorm(c.width)
        self.qkv, self.proj = nn.Linear(c.width, 3 * c.width), nn.Linear(c.width, c.width)
        self.mlp = nn.Sequential(nn.Linear(c.width, 4 * c.width), nn.GELU(), nn.Linear(4 * c.width, c.width))
        self.heads, self.drop, self.rope, self.context = c.heads, c.dropout, c.pos == "rope", c.context

    def forward(self, x, pos, cache=None):
        """cache: dict holding this layer's last context-1 keys/values; x is then the newest token(s)."""
        B, T, D = x.shape
        q, k, v = self.qkv(self.ln1(x)).view(B, T, 3, self.heads, D // self.heads).permute(2, 0, 3, 1, 4)
        if self.rope:
            q, k = rope(q, pos), rope(k, pos)
        if cache is not None:  # one new token, which may see everything cached
            if "k" in cache:
                k, v = torch.cat([cache["k"], k], 2), torch.cat([cache["v"], v], 2)
            cache["k"], cache["v"] = k[:, :, -(self.context - 1):], v[:, :, -(self.context - 1):]
        a = F.scaled_dot_product_attention(q, k, v, is_causal=cache is None and T > 1,
                                           dropout_p=self.drop if self.training else 0)
        x = x + F.dropout(self.proj(a.transpose(1, 2).reshape(B, T, D)), self.drop, self.training)
        return x + F.dropout(self.mlp(self.ln2(x)), self.drop, self.training)


def _head(width, n):
    return nn.Sequential(nn.LayerNorm(width), nn.Linear(width, width), nn.GELU(), nn.Linear(width, n))


class Policy(nn.Module):
    def __init__(self, c: Config):
        super().__init__()
        self.config = c
        w = c.width
        self.register_buffer("num_mean", torch.zeros(fe.NUM))
        self.register_buffer("num_std", torch.ones(fe.NUM))
        self.register_buffer("stick_centers", torch.zeros(c.n_stick, 2))
        self.num = nn.Linear(fe.NUM, w)
        self.action_me, self.action_opp = nn.Embedding(fe.N_ACTIONS, w), nn.Embedding(fe.N_ACTIONS, w)
        self.char_me, self.char_opp = nn.Embedding(len(CHARACTERS), w), nn.Embedding(len(CHARACTERS), w)
        self.stage = nn.Embedding(len(fe.STAGE_INDEX), w)
        self.rank = nn.Embedding(len(RANKS), w)
        self.win = nn.Embedding(fe.N_WIN, w)
        self.delay = nn.Embedding(fe.MAX_DELAY + 1, w)
        if c.pos == "learned":
            self.pos = nn.Embedding(c.context, w)
        self.blocks = nn.ModuleList(Block(c) for _ in range(c.layers))
        self.ln = nn.LayerNorm(w)
        sizes = (fe.N_SHOULDER, fe.N_CSTICK, c.n_stick, fe.N_BUTTONS)
        self.out = nn.ModuleList(_head(w, n) for n in sizes)
        self.given = nn.ModuleList(nn.Embedding(n, w) for n in sizes[:-1])

    def trunk(self, b, pos=None, caches=None):
        """b: num (B,T,NUM), actions (B,T,2), and per-window me_char, opp_char, stage, rank, win, delay (B,).

        pos: absolute frame positions (T,), default 0..T-1. caches: one dict per layer, for `step`.
        """
        T = b["num"].shape[1]
        if pos is None:
            pos = torch.arange(T, device=b["num"].device)
        x = self.num((b["num"] - self.num_mean) / self.num_std)
        x = x + self.action_me(b["actions"][..., 0]) + self.action_opp(b["actions"][..., 1])
        if self.config.pos == "learned":
            x = x + self.pos.weight[:T]
        per_window = (self.char_me(b["me_char"]) + self.char_opp(b["opp_char"]) + self.stage(b["stage"])
                      + self.rank(b["rank"]) + self.win(b["win"]) + self.delay(b["delay"]))
        x = x + per_window[:, None]
        for i, blk in enumerate(self.blocks):
            x = blk(x, pos, None if caches is None else caches[i])
        return self.ln(x)

    def forward(self, b):
        """Teacher forcing: each head sees the true earlier choices. Returns per-head logits."""
        h, logits = self.trunk(b), []
        for i, name in enumerate(HEADS):
            logits.append(self.out[i](h))
            if i < len(self.given):
                h = h + self.given[i](b[name])
        return logits

    def _choose(self, h, temperature):
        out = {}
        for i, name in enumerate(HEADS):
            p = F.softmax(self.out[i](h).float() / temperature, -1)
            out[name] = torch.multinomial(p, 1)[:, 0]
            if i < len(self.given):
                h = h + self.given[i](out[name])
        return out

    @torch.no_grad()
    def sample(self, b, temperature=1.0):
        """Choices for the last token of each window: dict head -> (B,) class index."""
        return self._choose(self.trunk(b)[:, -1], temperature)

    @torch.no_grad()
    def step(self, b, pos, caches, temperature=1.0):
        """One new frame per window (b tensors with T=1), attending to `caches` (rope models only)."""
        return self._choose(self.trunk(b, torch.as_tensor([pos], device=b["num"].device), caches)[:, -1], temperature)

    def new_caches(self):
        return [{} for _ in self.blocks]


def save(path, model, extra):
    torch.save(dict(config=asdict(model.config), state=model.state_dict(), **extra), path)


def load(path, device="cpu"):
    ck = torch.load(path, map_location=device, weights_only=False)
    m = Policy(Config(**ck["config"])).to(device)
    m.load_state_dict(ck["state"])
    return m.eval(), ck
