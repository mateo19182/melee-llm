"""Training (fe.window) and play (Policy._push/_batch) must give the model identical inputs.

    cd train && uv run python -m pytest tests
"""
from types import SimpleNamespace

import melee
import numpy as np
import pytest

from meleebot import features as fe
from meleebot.play import Policy
from meleebot.schema import FRAME


def random_frames(n, seed=0):
    rng = np.random.default_rng(seed)
    raw = rng.integers(0, 256, n * FRAME.itemsize, dtype=np.uint8)
    f = np.frombuffer(raw.tobytes(), FRAME).copy()
    for side in ("me", "opp"):  # keep floats finite and actions in range, like real frames
        for k in ("pos", "vel", "percent", "shield", "state_age", "hitstun"):
            f[side][k] = rng.normal(0, 50, f[side][k].shape)
        f[side]["action"] = rng.integers(0, 600, n)
    return f


def reference_window(frames, start, length, delay):
    """fe.window as first written (bc-6m-v1 was trained with it)."""
    t = start + np.arange(length)
    state, own = frames[t - delay], frames[t]["me_pad"]
    num = np.concatenate([fe.player_num(state["me"]), fe.player_num(state["opp"]),
                          fe.pad_num(own), fe.pad_num(state["opp_pad"])], -1)
    actions = np.stack([state["me"]["action"], state["opp"]["action"]], -1).astype(np.int64)
    return num, np.minimum(actions, fe.N_ACTIONS - 1)


def play_policy(context):
    p = Policy.__new__(Policy)
    p.context, p.port, p.opp, p.device, p.features = context, 1, 2, "cpu", "v1"
    p.steer = dict(delay=0, rank="MASTER", win=1, temperature=1.0)
    cap = 4 * context
    p.feats = (np.zeros((cap, 2 * fe.PLAYER_NUM), np.float32), np.zeros((cap, fe.PAD_NUM), np.float32),
               np.zeros((cap, fe.PAD_NUM), np.float32), np.zeros((cap, 2), np.int64))
    p.size = 0
    return p


GS = SimpleNamespace(players={1: SimpleNamespace(character=melee.Character.YOSHI),
                              2: SimpleNamespace(character=melee.Character.FOX)}, stage=melee.Stage.BATTLEFIELD)


@pytest.mark.parametrize("delay", [0, 1, 5, 12])
def test_window_unchanged(delay):
    f = random_frames(300)
    for start in (12, 40):
        new = fe.window(f, start, 256, delay)
        old = reference_window(f, start, 256, delay)
        assert np.array_equal(new[0], old[0]) and np.array_equal(new[1], old[1])


@pytest.mark.parametrize("delay", [0, 1, 5, 12])
def test_play_matches_training(delay):
    context, n = 32, 200   # n > 4 * context exercises the store's compaction
    f = random_frames(n, seed=delay)
    p = play_policy(context)
    p.steer["delay"] = delay
    for i in range(n):
        p._push(f[i])
        for last_only in (False, True):
            b = p._batch(GS, last_only)
            T = b["num"].shape[1]
            start = i + 1 - T
            if start >= delay:  # early frames are front-padded in play; training never starts there
                num, actions = reference_window(f, start, T, delay)
                assert np.array_equal(b["num"][0].numpy(), num), (i, last_only)
                assert np.array_equal(b["actions"][0].numpy(), actions), (i, last_only)
