"""Frames (schema.FRAME) -> model inputs, and controllers -> the classes the model predicts.

Token k of a window decides the controller of frame t+1, where t is the newest frame the bot has
acted on. It sees its own controller of frame t (the bot knows what it sent) and the game state
of frame t - delay (the bot only learns the state late). Shared by training and play.
"""
import numpy as np

from .schema import STAGES

MAX_DELAY = 12
N_ACTIONS = 512
STAGE_INDEX = {s: i for i, s in enumerate(STAGES)}
N_WIN = 3                      # lost, won, unknown

# Button classes: a bitmask over these groups, so combinations such as jump+shield are one class.
BUTTON_GROUPS = [0x0100, 0x0200, 0x0010, 0x0400 | 0x0800, 0x0020 | 0x0040]   # A, B, Z, X|Y, L|R
N_BUTTONS = 1 << len(BUTTON_GROUPS)
PAD_BITS = [0x0100, 0x0200, 0x0400, 0x0800, 0x0010, 0x0020, 0x0040, 0x0008]  # A B X Y Z R L Dup
SHOULDER_LEVELS = np.array([0, 60, 140])   # analog trigger value used when playing each class
N_SHOULDER = 3
N_CSTICK = 9                   # neutral + 8 directions
CSTICK_DIRS = np.array([[np.cos(a), np.sin(a)] for a in np.arange(8) * np.pi / 4])

PLAYER_NUM = 19
# "v1": every field the .slp builder stores. "v2": HAL's dataset (hal_mds.py) has no velocities, state
# age or hitstun, so v2 leaves those inputs at 0 everywhere (same layout, so the model is unchanged).
FEATURES = ("v1", "v2")
_V2_ZERO = [2, 3, 4, 5, 6, 9, 10]
PAD_NUM = 6 + len(PAD_BITS)
NUM = 2 * PLAYER_NUM + 2 * PAD_NUM


def player_num(p, features="v1"):
    """(..., 19) float32 raw numbers; normalised later with dataset mean/std."""
    out = np.empty(p.shape + (PLAYER_NUM,), np.float32)
    out[..., 0:2] = p["pos"]
    out[..., 2:7] = p["vel"]
    out[..., 7] = p["percent"]
    out[..., 8] = p["shield"]
    out[..., 9] = np.minimum(p["state_age"], 200)
    out[..., 10] = p["hitstun"]
    out[..., 11] = p["hitlag"]
    out[..., 12] = p["stocks"]
    out[..., 13] = p["jumps"]
    out[..., 14] = p["facing"]
    out[..., 15] = p["airborne"]
    out[..., 16:19] = p["invuln"][..., None] == np.arange(3)
    if features == "v2":
        out[..., _V2_ZERO] = 0
    return np.nan_to_num(out, nan=0.0, posinf=0.0, neginf=0.0)


def pad_num(c):
    out = np.empty(c.shape + (PAD_NUM,), np.float32)
    out[..., 0:2] = c["stick"] / 80
    out[..., 2:4] = c["cstick"] / 80
    out[..., 4:6] = c["trigger"] / 140
    b = c["buttons"][..., None]
    out[..., 6:] = (b & np.array(PAD_BITS, np.uint16)) != 0
    return out


def kmeans_stick(pads, k=40, iters=50, seed=0):
    """Cluster the main-stick positions players actually hold, weighted by how often."""
    pos, count = np.unique(pads["stick"].reshape(-1, 2), axis=0, return_counts=True)
    pos, w = pos.astype(np.float32), count.astype(np.float32)
    rng = np.random.default_rng(seed)
    centers = pos[rng.choice(len(pos), k, replace=False, p=w / w.sum())]
    for _ in range(iters):
        assign = ((pos[:, None] - centers[None]) ** 2).sum(-1).argmin(1)
        for j in range(k):
            m = assign == j
            if m.any():
                centers[j] = (pos[m] * w[m, None]).sum(0) / w[m].sum()
    # The exact positions players use most (neutral, full tilts) should be exact centres.
    for j, top in enumerate(pos[np.argsort(-w)[:9]]):
        nearest = ((centers - top) ** 2).sum(-1).argmin()
        centers[nearest] = top
    return np.round(centers).astype(np.float32)


def targets(c, stick_centers):
    """Controller records -> (shoulder, cstick, stick, buttons) class indices."""
    trig = c["trigger"].max(-1)
    shoulder = (trig >= 43).astype(np.int64) + (trig >= 130)
    cs = c["cstick"].astype(np.float32) / 80
    ang = np.round(np.arctan2(cs[..., 1], cs[..., 0]) / (np.pi / 4)).astype(np.int64) % 8
    cstick = np.where(np.hypot(cs[..., 0], cs[..., 1]) > 0.5, ang + 1, 0)
    st = c["stick"].astype(np.float32)
    stick = ((st[..., None, :] - stick_centers) ** 2).sum(-1).argmin(-1)
    buttons = np.zeros(c.shape, np.int64)
    for i, mask in enumerate(BUTTON_GROUPS):
        buttons |= ((c["buttons"] & mask) != 0).astype(np.int64) << i
    return shoulder, cstick, stick, buttons


def window(frames, start, length, delay, features="v1"):
    """Inputs for tokens deciding frames start+1 .. start+length, from a slice of one game.

    frames: FRAME records of one game. Needs start - delay >= 0 and start + length < len(frames).
    """
    lo = start - delay  # only the frames this window reads
    t = start + np.arange(length)
    return (*assemble(frame_parts(frames[lo:start + length], features), t - lo, delay), frames[t + 1]["me_pad"])


def frame_parts(frames, features="v1"):
    """Per-frame pieces of the model input; play computes them once per frame as it arrives.

    Returns state (N, 2*PLAYER_NUM), own pad (N, PAD_NUM), opponent pad (N, PAD_NUM), actions (N, 2).
    """
    state = np.concatenate([player_num(frames["me"], features), player_num(frames["opp"], features)], -1)
    actions = np.stack([frames["me"]["action"], frames["opp"]["action"]], -1).astype(np.int64)
    return state, pad_num(frames["me_pad"]), pad_num(frames["opp_pad"]), np.minimum(actions, N_ACTIONS - 1)


def assemble(parts, t, delay):
    """(num, actions) for the tokens at frame indices t: own pad of t, everything else from t - delay."""
    state, own, opp_pad, actions = parts
    return np.concatenate([state[t - delay], own[t], opp_pad[t - delay]], -1), actions[t - delay]
