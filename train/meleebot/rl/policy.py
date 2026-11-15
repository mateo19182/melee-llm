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
    """Write slot and attention mask for the current step, shared by every layer's RingCache."""

    def __init__(self, n, size, device):
        self.size, self.w = size, -1
        self.owner = torch.full((n, size), -1, dtype=torch.long, device=device)  # game id that wrote each slot
        self.slot = torch.arange(size, device=device)
        self.mask = None

    def advance(self, game, active):
        """game: (n,) id of each match's current game; active: (n,) whether this frame belongs to it."""
        self.w = (self.w + 1) % self.size
        self.owner[:, self.w] = torch.where(active, game, -1)
        # a token may always see itself, so matches in their countdown get finite (ignored) outputs
        self.mask = ((self.owner == game[:, None]) | (self.slot == self.w))[:, None, None]


class RingCache:
    def __init__(self, ring, n, heads, head_dim, device, dtype):
        self.ring = ring
        self.k = torch.zeros(n, heads, ring.size, head_dim, device=device, dtype=dtype)
        self.v = torch.zeros_like(self.k)

    def update(self, k, v):
        self.k[:, :, self.ring.w] = k[:, :, -1]
        self.v[:, :, self.ring.w] = v[:, :, -1]
        return self.k, self.v, self.ring.mask


class Actor:
    """Plays side `side` of matches `idx` (indices into the env's batch)."""

    def __init__(self, model, ckpt, idx, side, delay=3, rank=None, win=1, temperature=1.0, device="cuda"):
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

    @torch.inference_mode()
    def act(self, tok, start, active):
        """Sample this frame's choice for every match: dict head -> (n,) numpy class indices."""
        with torch.autocast(self.device.type, torch.bfloat16, enabled=self.device.type == "cuda"):
            choice = self.model._choose(self.hidden(tok, start, active), self.temperature)
        return {k: v.cpu().numpy() for k, v in choice.items()}

    @torch.inference_mode()
    def hidden(self, tok, start, active):
        """The trunk's output for this frame's token of every match, (n, width)."""
        start_t = torch.as_tensor(start, device=self.device)
        self.game += start_t.long()
        self.age = np.where(start, 0, self.age + 1)
        self.ring.advance(self.game, torch.as_tensor(active, device=self.device))
        b = {k: torch.as_tensor(v, device=self.device)[:, None] if k in ("num", "actions") else torch.as_tensor(v, device=self.device)
             for k, v in tok.items()}
        pos = torch.as_tensor(self.age, device=self.device)[:, None]
        with torch.autocast(self.device.type, torch.bfloat16, enabled=self.device.type == "cuda"):
            return self.model.trunk(b, pos, self.caches)[:, -1]
