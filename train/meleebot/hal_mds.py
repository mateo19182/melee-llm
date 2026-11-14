"""HAL's public dataset (huggingface ericyuegu/hal-mds-dataset) -> frames.bin + games.npz (see schema.py).

    uv run python -m meleebot.hal_mds OUT_DIR SOURCE_DIR... --character YOSHI

A SOURCE_DIR is one downloaded source folder, e.g. /mnt/data/melee/hal-mds/pro/amsa or
.../ranked-anonymized-1. Its train/ split goes to training and val/ to validation; test/ is left out.

HAL stores less per frame than our .slp builder: no velocities, state age or hitstun. Those fields
stay 0 here, so models trained on this data must use feature set "v2" (features.py), which ignores them.
"""
import argparse, gzip, json, os, time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor

import numpy as np

from .build_dataset import MIN_FRAMES
from .schema import CHARACTERS, FRAME

# libmelee internal character id -> our CHARACTERS index (external ids).
_INTERNAL = ["MARIO", "FOX", "FALCON", "DK", "KIRBY", "BOWSER", "LINK", "SHEIK", "NESS", "PEACH", "ICS",
             None, "PIKACHU", "SAMUS", "YOSHI", "PUFF", "MEWTWO", "LUIGI", "MARTH", "ZELDA", "YLINK", "DOC",
             "FALCO", "PICHU", "GNW", "GANON", "ROY"]
EXTERNAL = {i: CHARACTERS.index(n) for i, n in enumerate(_INTERNAL) if n}
# Shard rows use libmelee internal stage ids; schema.STAGES uses the .slp (external) ones.
STAGE_EXTERNAL = {8: 2, 18: 3, 6: 8, 26: 28, 24: 31, 25: 32}

# hal/wire.py ACTION_CHANNELS[6:] bit order -> our physical button bits (schema.BUTTONS).
_BUTTON_BITS = np.array([0x0100, 0x0200, 0x0400, 0x0800, 0x0010, 0x0020, 0x0040, 0x0008], np.uint16)
_SHAPE_BYTES = {0: 1, 1: 2, 2: 4, 3: 8}


def read_shard(path, columns):
    """Yield the rows of one zstd MDS shard, decoding only `columns`."""
    import zstandard
    idx = json.load(open(os.path.join(os.path.dirname(path), "index.json")))
    info = next(s for s in idx["shards"] if s["zip_data"]["basename"] == os.path.basename(path))
    names, encs, sizes = info["column_names"], info["column_encodings"], info["column_sizes"]
    with open(path, "rb") as fh:
        raw = zstandard.ZstdDecompressor().stream_reader(fh).read()
    n = int(np.frombuffer(raw, np.uint32, 1)[0])
    offsets = np.frombuffer(raw, np.uint32, n + 1, 4)
    for i in range(n):
        data, pos = memoryview(raw)[offsets[i]:offsets[i + 1]], 0
        lens = []
        for size in sizes:
            if size is None:
                size = int(np.frombuffer(data, np.uint32, 1, pos)[0]); pos += 4
            lens.append(size)
        row = {}
        for name, enc, size in zip(names, encs, lens):
            if name in columns:
                row[name] = _decode(enc, data[pos:pos + size])
            pos += size
        yield row


def _decode(enc, b):
    if enc == "int":
        return int(np.frombuffer(b, np.int64)[0])
    if enc == "str":
        return bytes(b).decode()
    assert enc.startswith("ndarray:"), enc  # static dtype, shape stored in front
    ndim, width = b[0] >> 2, _SHAPE_BYTES[b[0] % 4]
    shape = np.frombuffer(b, f"u{width}", ndim, 1)
    return np.frombuffer(b, enc.split(":")[1], offset=1 + ndim * width).reshape(shape)


def unpack_state(u):
    """hal/data/policy_schema.py pack_player_state, inverted. Missing values come back as 0."""
    u = u.astype(np.uint32)
    f = lambda shift, width, sentinel: np.where((v := (u >> shift) & ((1 << width) - 1)) == sentinel, 0, v)
    direction = (u >> 28) & 3
    return dict(action=f(0, 17, 65536), stocks=f(17, 3, 7), jumps_used=f(20, 4, 15), invuln=f(24, 2, 3),
                airborne=f(26, 2, 3), facing=np.where(direction == 3, 0, direction.astype(np.int8) - 1))


def _player(row, p):
    s = unpack_state(row[f"{p}_state"])
    out = np.zeros(len(s["action"]), FRAME["me"])
    out["pos"][:, 0], out["pos"][:, 1] = row[f"{p}_position_x"], row[f"{p}_position_y"]
    for ours, theirs in (("percent", "percent"), ("shield", "shield"), ("hitlag", "hitlag_left")):
        out[ours] = np.nan_to_num(row[f"{p}_{theirs}"])
    out["action"], out["stocks"], out["facing"] = s["action"], s["stocks"], s["facing"]
    out["airborne"], out["invuln"] = s["airborne"], s["invuln"]
    out["jumps"] = s["jumps_used"]  # despite HAL's name, jumps remaining, as in the .slp builder (checked: 2 when standing)
    out["pos"] = np.nan_to_num(out["pos"])
    return out


def _pad(row, p):
    out = np.zeros(len(row[f"{p}_buttons"]), FRAME["me_pad"])
    stick = lambda k: np.where(row[k] == -128, 0, row[k])
    out["stick"][:, 0], out["stick"][:, 1] = stick(f"{p}_main_stick_x"), stick(f"{p}_main_stick_y")
    out["cstick"][:, 0], out["cstick"][:, 1] = stick(f"{p}_c_stick_x"), stick(f"{p}_c_stick_y")
    for i, k in enumerate(("l", "r")):
        t = row[f"{p}_trigger_{k}"]
        out["trigger"][:, i] = np.where(t == 255, 0, t)
    b = row[f"{p}_buttons"][:, None]
    out["buttons"] = (((b >> np.arange(8)) & 1).astype(np.uint16) * _BUTTON_BITS).sum(1)
    return out


COLUMNS = {"replay_id", "num_frames", "stage", *(f"p{i}_{k}" for i in (1, 2) for k in (
    "character", "rank", "state", "position_x", "position_y", "percent", "shield", "hitlag_left",
    "buttons", "main_stick_x", "main_stick_y", "c_stick_x", "c_stick_y", "trigger_l", "trigger_r"))}


def parse_shard(args):
    """One shard -> (list of (frames bytes, labels), Counter of rejections)."""
    path, character, val, codes = args
    out, rejected = [], Counter()
    for row in read_shard(path, COLUMNS):
        stage = STAGE_EXTERNAL.get(row["stage"])
        if stage is None or row["num_frames"] < MIN_FRAMES:
            rejected["stage or length"] += 1
            continue
        chars = [EXTERNAL.get(row[f"p{i}_character"]) for i in (1, 2)]
        if None in chars:
            rejected["character"] += 1
            continue
        players = [_player(row, p) for p in ("p1", "p2")]
        end = [int(p["stocks"][-1]) for p in players]
        if min(end) != 0:
            rejected["unfinished"] += 1
            continue
        score = [(end[i], -float(players[i]["percent"][-1])) for i in (0, 1)]
        pads = [_pad(row, p) for p in ("p1", "p2")]
        ids = codes.get(row["replay_id"], (0, 0))
        kept = 0
        for me in (0, 1):
            if character != "ALL" and CHARACTERS[chars[me]] != character:
                continue
            opp = 1 - me
            f = np.zeros(row["num_frames"], FRAME)
            f["me"], f["opp"], f["me_pad"], f["opp_pad"] = players[me], players[opp], pads[me], pads[opp]
            out.append((f.tobytes(), dict(
                replay=row["replay_id"], me_char=chars[me], opp_char=chars[opp], stage=stage,
                rank=row[f"p{me + 1}_rank"], player=ids[me], win=int(score[me] > score[opp]),
                draw=int(score[me] == score[opp]), val=val)))
            kept += 1
        if not kept:
            rejected["character not in game"] += 1
    return out, rejected


def load_codes(root):
    """replay_id -> (p1, p2) HAL player ids (0 unknown); codes[id - 4] is the connect code."""
    path = os.path.join(root, "player_codes.jsonl.gz")
    if not os.path.exists(path):
        return {}, []
    with gzip.open(path, "rt") as fh:
        head = json.loads(fh.readline())
        return {r[0]: (r[1], r[2]) for r in map(json.loads, fh)}, head["codes"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out_dir"); ap.add_argument("sources", nargs="+")
    ap.add_argument("--character", default="YOSHI", choices=CHARACTERS + ["ALL"])
    ap.add_argument("--codes", default="/mnt/data/melee/hal-mds", help="folder with player_codes.jsonl.gz")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--limit", type=int, help="shards per split, for quick tests")
    a = ap.parse_args()

    codes, vocab = load_codes(a.codes)
    jobs = []
    for src in a.sources:
        for split, val in (("train", 0), ("val", 1)):
            d = os.path.join(src, split)
            shards = sorted(f for f in os.listdir(d) if f.endswith(".mds.zstd"))[:a.limit]
            jobs += [(os.path.join(d, f), a.character, val, codes) for f in shards]
    os.makedirs(a.out_dir, exist_ok=True)
    rows, rejected, offset, t0 = [], Counter(), 0, time.time()
    with ProcessPoolExecutor(a.workers) as ex, open(os.path.join(a.out_dir, "frames.bin"), "wb") as fh:
        for i, (res, rej) in enumerate(ex.map(parse_shard, jobs)):
            rejected.update(rej)
            for blob, row in res:
                fh.write(blob)
                n = len(blob) // FRAME.itemsize
                rows.append(dict(row, offset=offset, length=n))
                offset += n
            print(f"{i + 1}/{len(jobs)} shards, {len(rows)} perspectives, {offset / 1e6:.0f}M frames, "
                  f"{time.time() - t0:.0f}s", flush=True)

    cols = {k: np.array([r[k] for r in rows]) for k in rows[0]}
    np.savez(os.path.join(a.out_dir, "games.npz"), **cols)
    meta = dict(character=a.character, source="hal-mds", sources=[os.path.abspath(s) for s in a.sources],
                features="v2", perspectives=len(rows), frames=offset, frame_bytes=FRAME.itemsize,
                rejected=dict(rejected), min_frames=MIN_FRAMES,
                player_codes={i + 4: c for i, c in enumerate(vocab) if i + 4 in set(cols["player"].tolist())})
    with open(os.path.join(a.out_dir, "meta.json"), "w") as fh:
        json.dump(meta, fh, indent=1)
    print(json.dumps({k: v for k, v in meta.items() if k != "player_codes"}, indent=1))


if __name__ == "__main__":
    main()
