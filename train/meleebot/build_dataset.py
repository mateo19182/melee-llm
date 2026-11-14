"""Turn .slp replays into frames.bin + games.npz (see schema.py).

    uv run python -m meleebot.build_dataset SLP_DIR OUT_DIR --character YOSHI
"""
import argparse, hashlib, json, os, time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor

import numpy as np

from .schema import CHARACTERS, FRAME, RANKS, STAGES

MIN_FRAMES = 1500
VAL_PERCENT = 2
END_TIME, END_GAME = 1, 2


def _np(a, fill=0.0):
    out = a.to_numpy(zero_copy_only=False)
    return np.nan_to_num(out, nan=fill) if out.dtype.kind == "f" else out


def _player(post, keep):
    """keep: indices of the frames to store, in frame order."""
    out = np.zeros(len(keep), FRAME["me"])
    out["pos"][:, 0] = _np(post.position.x)[keep]
    out["pos"][:, 1] = _np(post.position.y)[keep]
    v = post.velocities
    for i, name in enumerate(("self_x_air", "self_x_ground", "self_y", "knockback_x", "knockback_y")):
        out["vel"][:, i] = _np(getattr(v, name))[keep]
    out["percent"] = _np(post.percent)[keep]
    out["shield"] = _np(post.shield)[keep]
    out["state_age"] = _np(post.state_age)[keep]
    # misc_as only counts hitstun down while the hitstun flag (byte 4, bit 0x02) is set.
    in_hitstun = (_np(post.state_flags[3]) & 0x02) != 0
    out["hitstun"] = np.where(in_hitstun, _np(post.misc_as), 0)[keep]
    out["action"] = _np(post.state)[keep]
    out["hitlag"] = _np(post.hitlag)[keep]
    out["stocks"] = _np(post.stocks)[keep]
    out["jumps"] = _np(post.jumps)[keep]
    out["facing"] = np.sign(_np(post.direction))[keep]
    out["airborne"] = _np(post.airborne)[keep]
    out["invuln"] = _np(post.hurtbox_state)[keep]
    return out


def _pad(pre, keep):
    out = np.zeros(len(keep), FRAME["me_pad"])
    for field, src in (("stick", pre.joystick), ("cstick", pre.cstick)):
        out[field][:, 0] = np.round(_np(src.x) * 80)[keep]
        out[field][:, 1] = np.round(_np(src.y) * 80)[keep]
    out["trigger"][:, 0] = np.round(_np(pre.triggers_physical.l) * 140)[keep]
    out["trigger"][:, 1] = np.round(_np(pre.triggers_physical.r) * 140)[keep]
    out["buttons"] = _np(pre.buttons_physical)[keep]
    return out


def parse(args):
    """One replay -> list of (frames, labels), one per kept perspective, or a rejection reason."""
    path, character = args
    import peppi_py
    name = os.path.basename(path)
    try:
        g = peppi_py.read_slippi(path)
    except Exception as e:
        return name, f"parse error: {type(e).__name__}"
    s = g.start
    if len(s.players) != 2 or s.is_teams or s.is_pal or any(int(p.type) != 0 for p in s.players):
        return name, "not a 1v1 between humans"
    if int(s.stage) not in STAGES:
        return name, "stage not legal"
    ids = _np(g.frames.id)
    # Rollback netplay re-emits frames; the last copy of each frame id is the one that happened.
    uniq, first_from_end = np.unique(ids[::-1], return_index=True)
    if (np.diff(uniq) != 1).any():
        return name, "frames not contiguous"
    keep = (len(ids) - 1 - first_from_end)[uniq >= 0]
    if len(keep) < MIN_FRAMES:
        return name, "too short"
    posts = [p.leader.post for p in g.frames.ports]
    stocks = [_np(p.stocks)[keep] for p in posts]
    pct = [_np(p.percent)[keep] for p in posts]
    if any(st.min() == st[0] and pc.max() == 0 for st, pc in zip(stocks, pct)):
        return name, "a player took no damage"
    end = [int(st[-1]) for st in stocks]
    method = int(g.end.method) if g.end is not None else None
    if not (min(end) == 0 or method == END_TIME):
        return name, "unfinished"
    score = [(end[i], -float(pct[i][-1])) for i in (0, 1)]
    chars = [int(p.character) for p in s.players]
    players = [_player(p, keep) for p in posts]
    pads = [_pad(p.leader.pre, keep) for p in g.frames.ports]
    out = []
    for me in (0, 1):
        if character != "ALL" and CHARACTERS[chars[me]] != character:
            continue
        opp = 1 - me
        f = np.zeros(len(keep), FRAME)
        f["me"], f["opp"], f["me_pad"], f["opp_pad"] = players[me], players[opp], pads[me], pads[opp]
        rank = (s.players[me].netplay.name if s.players[me].netplay else "").split(" ")[0].upper()
        out.append((f.tobytes(), dict(
            replay=name, me_char=chars[me], opp_char=chars[opp], stage=int(s.stage),
            rank=RANKS.index(rank) if rank in RANKS else 0,
            win=int(score[me] > score[opp]), draw=int(score[me] == score[opp]),
            val=int(int(hashlib.sha1(name.encode()).hexdigest(), 16) % 100 < VAL_PERCENT))))
    return name, out or "character not in game"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("slp_dir"); ap.add_argument("out_dir")
    ap.add_argument("--character", default="YOSHI", choices=CHARACTERS + ["ALL"])
    ap.add_argument("--workers", type=int, default=20)
    ap.add_argument("--limit", type=int)
    a = ap.parse_args()

    paths = sorted(os.path.join(r, f) for r, _, fs in os.walk(a.slp_dir) for f in fs if f.endswith(".slp"))
    paths = paths[:a.limit]
    os.makedirs(a.out_dir, exist_ok=True)
    rows, rejected, offset, t0 = [], Counter(), 0, time.time()
    with ProcessPoolExecutor(a.workers) as ex, open(os.path.join(a.out_dir, "frames.bin"), "wb") as fh:
        for i, (name, res) in enumerate(ex.map(parse, [(p, a.character) for p in paths], chunksize=8)):
            if isinstance(res, str):
                rejected[res] += 1
            else:
                for blob, row in res:
                    fh.write(blob)
                    n = len(blob) // FRAME.itemsize
                    rows.append(dict(row, offset=offset, length=n))
                    offset += n
            if i % 2000 == 0:
                print(f"{i}/{len(paths)} replays, {offset / 1e6:.0f}M frames, {time.time() - t0:.0f}s", flush=True)

    cols = {k: np.array([r[k] for r in rows]) for k in rows[0]}
    np.savez(os.path.join(a.out_dir, "games.npz"), **cols)
    meta = dict(character=a.character, source=os.path.abspath(a.slp_dir), replays=len(paths),
                perspectives=len(rows), frames=offset, frame_bytes=FRAME.itemsize,
                rejected=dict(rejected), min_frames=MIN_FRAMES, val_percent=VAL_PERCENT)
    with open(os.path.join(a.out_dir, "meta.json"), "w") as fh:
        json.dump(meta, fh, indent=1)
    print(json.dumps(meta, indent=1))


if __name__ == "__main__":
    main()
