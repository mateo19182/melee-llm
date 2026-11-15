"""A model playing one side of many simulator matches at once, one cached step per frame.

Inputs are built exactly as play.Policy builds them for one live game (fe.frame_parts, own pad of frame t,
everything else from t - delay, the first frame repeated while fewer than `delay` exist), so a model behaves
here as it does on Dolphin. Keys/values live in a fixed ring of `context` slots shared by all matches; each
slot remembers which game wrote it, so a match never attends to the game before.
"""
import numpy as np
import torch

from .. import features as fe
from ..model import default_rank
from ..schema import RANKS


class Ring:
    """Write slot and attention mask for the current step, shared by every layer's RingCache. All state lives on
    the device and changes in place, so a step can be captured in a CUDA graph."""

    def __init__(self, n, size, device):
        self.size = size
        self.w = torch.full((1,), size - 1, dtype=torch.long, device=device)
        self.owner = torch.full((n, size), -1, dtype=torch.long, device=device)  # game id that wrote each slot
        self.slot = torch.arange(size, device=device)
        self.mask = torch.zeros(n, 1, 1, size, dtype=torch.bool, device=device)

    def advance(self, game, active):
        """game: (n,) id of each match's current game; active: (n,) whether this frame belongs to it."""
        self.w.copy_((self.w + 1) % self.size)
        self.owner.scatter_(1, self.w.expand(len(game), 1), torch.where(active, game, -1)[:, None])
        # a token may always see itself, so matches in their countdown get finite (ignored) outputs
        self.mask.copy_(((self.owner == game[:, None]) | (self.slot == self.w))[:, None, None])


class RingCache:
    def __init__(self, ring, n, heads, head_dim, device, dtype):
        self.ring = ring
        self.k = torch.zeros(n, heads, ring.size, head_dim, device=device, dtype=dtype)
        self.v = torch.zeros_like(self.k)

    def update(self, k, v):
        self.k.index_copy_(2, self.ring.w, k[:, :, -1:].to(self.k.dtype))
        self.v.index_copy_(2, self.ring.w, v[:, :, -1:].to(self.v.dtype))
        return self.k, self.v, self.ring.mask


class Actor:
    """Plays side `side` of matches `idx` (indices into the env's batch)."""

    def __init__(self, model, ckpt, idx, side, delay=3, rank=None, win=1, temperature=1.0, device="cuda", graphs=True):
        self.model, self.idx, self.side, self.delay, self.temperature = model, np.asarray(idx), side, delay, temperature
        self.features = model.config.features
        self.device = torch.device(device)
        n, c = len(self.idx), model.config
        self.rank = RANKS.index(rank or default_rank(ckpt))
        self.win = {0: 0, 1: 1, None: 2}[win]
        self.centers = model.stick_centers.cpu().numpy()
        self.ring = Ring(n, c.context, self.device)
        dtype = torch.bfloat16 if self.device.type == "cuda" else torch.float32
        self.caches = [RingCache(self.ring, n, c.heads, c.width // c.heads, self.device, dtype) for _ in model.blocks]
        D = fe.MAX_DELAY + 1
        self.hist = (np.zeros((n, D, 2 * fe.PLAYER_NUM), np.float32), np.zeros((n, D, fe.PAD_NUM), np.float32),
                     np.zeros((n, D, 2), np.int64))   # state, opponent pad, actions of the last D frames
        self.game = torch.zeros(n, dtype=torch.long, device=self.device)
        self.age = np.zeros(n, np.int64)
        self.graph, self.graphs = None, graphs and self.device.type == "cuda"

    def tokens(self, frames, start, chars, stage):
        """Model inputs for this frame: dict of (n, ...) numpy arrays, one token per match.

        frames: (n,) FRAME from this side's view; start: (n,) bool, first frame (frame 0) of a game;
        chars: (n, 2) CHARACTERS indices (this side, other side); stage: (n,) fe.STAGE_INDEX."""
        state, own, opp_pad, actions = fe.frame_parts(frames, self.features)
        for h, x in zip(self.hist, (state, opp_pad, actions)):
            h[:, :-1] = h[:, 1:]
            h[:, -1] = x
            h[start] = x[start, None]   # a new game: its first frame stands in for the missing older ones
        d = -1 - self.delay
        n = len(frames)
        return dict(num=np.concatenate([self.hist[0][:, d], own, self.hist[1][:, d]], -1), actions=self.hist[2][:, d],
                    me_char=chars[:, 0], opp_char=chars[:, 1], stage=stage, delay=np.full(n, self.delay),
                    rank=np.full(n, self.rank), win=np.full(n, self.win))

    def _inputs(self, tok, start, active):
        self.age = np.where(start, 0, self.age + 1)
        x = {k: torch.as_tensor(v)[:, None] if k in ("num", "actions") else torch.as_tensor(v) for k, v in tok.items()}
        return x, torch.as_tensor(self.age)[:, None], torch.as_tensor(start), torch.as_tensor(active)

    def _step(self, b, pos, start, active):
        """Device-only work of one frame: advance the ring, run the trunk, sample. Returns (hidden, choice)."""
        self.game += start.long()
        self.ring.advance(self.game, active)
        with torch.autocast(self.device.type, torch.bfloat16, enabled=self.device.type == "cuda"):
            h = self.model.trunk(b, pos, self.caches)[:, -1]
            return h, self.model._choose(h, self.temperature)

    @torch.inference_mode()
    def run(self, tok, start, active):
        """(hidden (n, width), choice dict head -> (n,) tensor) for this frame's token of every match."""
        x = self._inputs(tok, start, active)
        if not self.graphs:
            return self._step(*(_to(v, self.device) for v in x))
        if self.graph is None:
            self._capture(x)
        for dst, src in zip(_flat(self.static), _flat(x)):
            dst.copy_(src, non_blocking=True)
        self.graph.replay()
        return self.out

    def _capture(self, x):
        """Record one step as a CUDA graph (fixed shapes: the ring never grows) and replay it from then on.
        Capture runs a real step, so ring and game state are saved first and restored after warming up."""
        self.static = _to(x, self.device)
        saved = [t.clone() for t in self._state()]
        s = torch.cuda.Stream()
        s.wait_stream(torch.cuda.current_stream())
        with torch.cuda.stream(s):
            for _ in range(2):
                self._step(*self.static)
        torch.cuda.current_stream().wait_stream(s)
        self.graph = torch.cuda.CUDAGraph()
        with torch.cuda.graph(self.graph):
            self.out = self._step(*self.static)
        for t, v in zip(self._state(), saved):
            t.copy_(v)

    def _state(self):
        return [self.game, self.ring.w, self.ring.owner, *(t for c in self.caches for t in (c.k, c.v))]

    def act(self, tok, start, active):
        """Sample this frame's choice for every match: dict head -> (n,) numpy class indices."""
        return {k: v.cpu().numpy() for k, v in self.run(tok, start, active)[1].items()}

    def hidden(self, tok, start, active):
        return self.run(tok, start, active)[0]


def _flat(x):
    if isinstance(x, dict):
        return [t for v in x.values() for t in _flat(v)]
    if isinstance(x, (tuple, list)):
        return [t for v in x for t in _flat(v)]
    return [x]


def _to(x, device):
    if isinstance(x, dict):
        return {k: _to(v, device) for k, v in x.items()}
    if isinstance(x, (tuple, list)):
        return type(x)(_to(v, device) for v in x)
    return x.to(device)
