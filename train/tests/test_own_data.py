"""own.data: windows are aligned to the delay, and records survive the trip to tensors."""
import random

import numpy as np
import torch
from own import data, hal


def _frames(n):
    f = np.zeros(n, hal.FRAME)
    f["pad"]["buttons"] = np.arange(n) % 251
    f["p0"]["x"] = np.arange(n)
    f["p0"]["facing"] = np.arange(n) % 2 == 0
    f["item_type"][:, 3] = np.arange(n) % 7
    return f


def test_window_alignment():
    f = _frames(2000)
    labels = dict(character=14, opponent=1, stage=25, rank=3)
    seen = set()
    for w in data.windows(f, labels, (0, 12), random.Random(0)):
        d = (0, 12)[w["meta"][4]]
        seen.add(d)
        s = int(w["frames"]["p0"]["x"][0])
        assert len(w["frames"]) == data.WINDOW and w["meta"][3] == hal.FIRST_FRAME + s
        assert (w["pad"]["buttons"] == f["pad"]["buttons"][s + d:s + d + data.WINDOW]).all()
        assert (w["target"]["buttons"] == f["pad"]["buttons"][s + d + 1:s + d + 1 + data.WINDOW]).all()
    assert seen == {0, 12}


def test_tensors_round_trip():
    f = _frames(2000)
    labels = dict(character=14, opponent=1, stage=25, rank=3)
    ws = list(data.windows(f, labels, (0,), random.Random(1)))[:3]
    game, pad, target, name, valid = data.tensors(data.collate(ws), device="cpu")
    for i, w in enumerate(ws):
        assert torch.equal(game["p0"]["x"][i], torch.from_numpy(w["frames"]["p0"]["x"].copy()))
        assert torch.equal(game["p0"]["facing"][i], torch.from_numpy(w["frames"]["p0"]["facing"].copy()))
        assert torch.equal(game["items"]["type"][i, :, 3], torch.from_numpy(w["frames"]["item_type"][:, 3].astype(np.int64)))
        assert torch.equal(pad["buttons"]["A"][i], torch.from_numpy((w["pad"]["buttons"] & 1).astype(bool)))
    assert game["items"]["exists"].shape == (3, data.WINDOW, 15) and game["p0"]["character"][0, 0] == 14
    assert name.shape == valid.shape == (3, data.WINDOW)
