"""Training batches from HAL's dataset: 256-frame windows of one player's side, each at one input delay.

At delay D the model, reading the game at frame t, is given the pad it last committed (the one the game applies at
t + D) and must produce the pad for t + D + 1: slippi-ai's alignment, and what `farm.faynt` does in play with
`delay=D,own=1`. D = 0 is Faynt's own setup.

The model is told three things about the player it imitates through one name code (`code`): the delay, the rank and
whether they won the game. In play we pick the code: `python -m own.data 0,12` prints the table.
"""
import json
import random
from pathlib import Path

import numpy as np
import torch

from . import hal
from .mds import read_shard

ROOT = Path("/mnt/data/melee/hal-mds")
ARCHIVE = Path("/mnt/archive/melee/hal-mds")  # holds the shards of the pro folders that are not under ROOT
WINDOW = 256
# slippi-ai's opt-out list (slippi_ai/nametags.py): never imitated, still seen as opponents.
OPTED_OUT = {"mang0", "m2k"}
RANKS = ("unknown", "platinum", "diamond", "master", "pro")
CODES = 32  # the model's name vocabulary: room for 3 delays


def code(delays, delay, rank, won):
    """The name code of a player of `rank` (index into RANKS) who won or lost, read at `delay` frames."""
    return delays.index(delay) + len(delays) * (int(won) + 2 * min(int(rank), len(RANKS) - 1))


def sources(root=ROOT):
    return sorted(p.parent for p in root.glob("*/manifest.jsonl")) + sorted(p.parent for p in root.glob("pro/*/manifest.jsonl"))


def shards(split, root=ROOT, archive=ARCHIVE):
    """[(shard path, opted-out folder?)] of every source's split."""
    out = []
    for src in sources(root):
        index = json.load(open(src / split / "index.json"))
        for s in index["shards"]:
            path = src / split / s["zip_data"]["basename"]
            if not path.exists():
                path = archive / path.relative_to(root)
            out.append((str(path), src.name in OPTED_OUT))
    return out


def windows(frames, labels, delays, rng):
    """Cut one side of a game into windows at a random phase, each with a delay drawn from `delays`."""
    n, top = len(frames), max(delays)
    start = rng.randrange(WINDOW)
    for s in range(start, n - WINDOW - top - 1, WINDOW):
        d = rng.choice(delays)
        yield dict(frames=frames[s:s + WINDOW], pad=frames["pad"][s + d:s + d + WINDOW],
                   target=frames["pad"][s + d + 1:s + d + 1 + WINDOW],
                   meta=np.array([labels["character"], labels["opponent"], labels["stage"], hal.FIRST_FRAME + s,
                                  code(delays, d, labels["rank"], labels["won"]), delays.index(d)], np.int32))


class Windows(torch.utils.data.IterableDataset):
    """Shuffled batches, endlessly (train) or one fixed pass over `limit` games (validation)."""

    def __init__(self, split, delays, batch, seed=0, buffer=8192, limit=None, character=None, mix=4):
        self.files, self.delays, self.batch, self.seed = shards(split), tuple(delays), batch, seed
        self.buffer, self.limit, self.character, self.mix = buffer, limit, character, mix

    def shard(self, path, opted_out):
        for row in read_shard(path, hal.COLUMNS):
            for frames, labels in hal.game(row):
                if opted_out and labels["rank"] == 4:
                    continue
                if self.character is not None and labels["character"] != self.character:
                    continue
                yield frames, labels

    def games(self, files, mix=1, rng=None):
        """The games of `files`, reading `mix` shards at once and taking the next game from a random one. A shard
        holds about 170 games of one source, often one player's, so shard after shard makes batches of very few
        sources (E35's validation loss swung with whatever the last shards held)."""
        files, open_ = iter(files), []
        while True:
            while len(open_) < mix and (f := next(files, None)) is not None:
                open_.append(self.shard(*f))
            if not open_:
                return
            i = rng.randrange(len(open_)) if rng else 0
            game = next(open_[i], None)
            if game is None:
                open_.pop(i)
            else:
                yield game

    def __iter__(self):
        info = torch.utils.data.get_worker_info()
        worker, workers = (info.id, info.num_workers) if info else (0, 1)
        rng = random.Random(self.seed * 1000 + worker)
        if self.limit:  # validation: the same windows every time
            files = sorted(self.files)
            random.Random(self.seed).shuffle(files)
            pool, games = [], 0
            for frames, labels in self.games(files[worker::workers]):
                pool += list(windows(frames, labels, self.delays, rng))
                games += 1
                if games >= self.limit // workers:
                    break
            for i in range(0, len(pool) - self.batch + 1, self.batch):
                yield collate(pool[i:i + self.batch])
            return
        pool = []
        while True:
            files = list(self.files)
            rng.shuffle(files)
            for frames, labels in self.games(files[worker::workers], self.mix, rng):
                pool += list(windows(frames, labels, self.delays, rng))
                while len(pool) >= self.buffer:
                    rng.shuffle(pool)
                    take, pool = pool[:self.buffer // 4], pool[self.buffer // 4:]
                    for i in range(0, len(take) - self.batch + 1, self.batch):
                        yield collate(take[i:i + self.batch])


def collate(items):
    return {k: torch.from_numpy(np.stack([w[k] for w in items]).view(np.uint8).reshape(len(items), -1)
                                if k != "meta" else np.stack([w[k] for w in items])) for k in items[0]}


def loader(split, delays, batch, workers, **kw):
    return torch.utils.data.DataLoader(Windows(split, delays, batch, **kw), batch_size=None, num_workers=workers,
                                       prefetch_factor=4 if workers else None, persistent_workers=bool(workers))


def _fields(raw, dtype, shape):
    """A batch of structured records sent as bytes -> {field: tensor}, on the tensor's device."""
    raw = raw.reshape(*shape, dtype.itemsize)
    out = {}
    for name, (sub, offset, *_) in dtype.fields.items():
        chunk = raw[..., offset:offset + sub.itemsize]
        if sub.fields:
            out[name] = _fields(chunk, sub, shape)
            continue
        base, inner = (sub.subdtype if sub.subdtype else (sub, ()))
        t = chunk.contiguous().view(getattr(torch, {"b1": "bool", "u1": "uint8", "i1": "int8", "u2": "uint16",
                                                     "f4": "float32"}[base.str.lstrip("<|")]))
        out[name] = t.reshape(*shape, *inner)
    return out


def controller(pad):
    """Dataset pad codes -> the model's controller values (slippi-ai's: sticks in [0, 1], one shoulder)."""
    stick = (pad["stick"].float() / 80 + 1) / 2
    names = ("A", "B", "X", "Y", "Z", "L", "R", "D_UP")
    return dict(main_stick=dict(x=stick[..., 0], y=stick[..., 1]), c_stick=dict(x=stick[..., 2], y=stick[..., 3]),
                shoulder=pad["shoulder"].float() / 140,
                buttons={n: (pad["buttons"] >> i & 1).bool() for i, n in enumerate(names)})


def tensors(batch, device="cuda"):
    """One collated batch -> (game, controller in, controller target, name code, valid) for the model."""
    b = {k: v.to(device, non_blocking=True) for k, v in batch.items()}
    n = len(b["meta"])
    shape = (n, WINDOW)
    f = _fields(b["frames"], hal.FRAME, shape)
    meta = b["meta"].long()
    whole = lambda v: v[:, None].expand(n, WINDOW)

    def player(p, character, nana=None):
        out = dict(percent=p["percent"].long(), facing=p["facing"], x=p["x"], y=p["y"], action=p["action"].long(),
                   invulnerable=p["invulnerable"], character=character, jumps_left=p["jumps"].long(),
                   shield_strength=p["shield"], on_ground=p["on_ground"])
        if nana is not None:
            out["nana"] = dict(player(nana, torch.where(nana["exists"], hal.NANA, 0)), exists=nana["exists"])
        return out

    pad15 = lambda v: torch.nn.functional.pad(v, (0, 15 - hal.ITEMS))
    game = dict(p0=player(f["p0"], whole(meta[:, 0]), f["n0"]), p1=player(f["p1"], whole(meta[:, 1]), f["n1"]),
                stage=whole(meta[:, 2]), raw_frame_id=meta[:, 3, None] + torch.arange(WINDOW, device=device),
                items=dict(exists=pad15(f["item_exists"]), type=pad15(f["item_type"].long()),
                           state=pad15(f["item_state"].long()), x=pad15(f["item_x"]), y=pad15(f["item_y"])))
    pad_in = controller(_fields(b["pad"], hal.PAD, shape))
    target = controller(_fields(b["target"], hal.PAD, shape))
    return game, pad_in, target, whole(meta[:, 4]), torch.ones(shape, dtype=torch.bool, device=device)


if __name__ == "__main__":
    import sys

    ds = tuple(int(x) for x in sys.argv[1].split(","))
    for r, rank in enumerate(RANKS):
        print(rank.ljust(9), *(f"delay {d} {'won' if w else 'lost'}: {code(ds, d, r, w):2d}  " for d in ds for w in (1, 0)))
