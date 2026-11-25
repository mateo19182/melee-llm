"""A game of HAL's dataset as the per-frame inputs of a Faynt-architecture policy, from one player's side.

Field meanings follow slippi-ai's live parser (slippi_db/parse_libmelee.py), which is what the model reads in play:
`own.parity` compares the two on real replays. The dataset has no Fountain of Dreams platform heights, so our models
are built without that input, and it keeps the four oldest items of a frame where the parser keeps fifteen.
"""
import numpy as np

ITEMS = 4
PLAYER = np.dtype([("percent", "u2"), ("x", "f4"), ("y", "f4"), ("action", "u2"), ("shield", "f4"), ("jumps", "u1"),
                   ("facing", "?"), ("invulnerable", "?"), ("on_ground", "?"), ("exists", "?")])
PAD = np.dtype([("stick", "i1", 4), ("shoulder", "u1"), ("buttons", "u1")])  # dataset codes: /80, /140, bits
FRAME = np.dtype([("p0", PLAYER), ("p1", PLAYER), ("n0", PLAYER), ("n1", PLAYER), ("pad", PAD),
                  ("item_exists", "?", ITEMS), ("item_type", "u2", ITEMS), ("item_state", "u1", ITEMS),
                  ("item_x", "f4", ITEMS), ("item_y", "f4", ITEMS)])
FIRST_FRAME = -123  # a replay's first frame; Randall's position is a function of the frame number
NANA = 11  # melee.Character.NANA

STATE = ("state", "position_x", "position_y", "percent", "shield")
COLUMNS = {"replay_id", "num_frames", "stage", "item_present",
           *(f"item{i}_{k}" for i in range(ITEMS) for k in ("meta", "pos_x", "pos_y")),
           *(f"p{i}_{k}" for i in (1, 2) for k in (
               "character", "rank", *STATE, *(f"nana_{s}" for s in STATE),
               "buttons", "main_stick_x", "main_stick_y", "c_stick_x", "c_stick_y", "trigger_l", "trigger_r"))}

# dataset button bits (a b x y z r l d_up) -> the model's order (A B X Y Z L R D_UP)
BUTTON_BITS = (0, 1, 2, 3, 4, 6, 5, 7)


def _player(row, prefix):
    u = row[f"{prefix}_state"].astype(np.uint32)
    out = np.zeros(len(u), PLAYER)
    action, jumps = u & 0x1FFFF, (u >> 20) & 15
    hurtbox, airborne, direction = (u >> 24) & 3, (u >> 26) & 3, (u >> 28) & 3
    out["exists"] = action != 65536
    out["action"] = np.where(out["exists"], action, 0)
    out["jumps"] = np.where(jumps == 15, 0, np.minimum(jumps, 6))
    out["invulnerable"] = (hurtbox == 1) | (hurtbox == 2)
    out["on_ground"] = airborne == 0
    out["facing"] = direction == 2
    out["x"], out["y"] = np.nan_to_num(row[f"{prefix}_position_x"]), np.nan_to_num(row[f"{prefix}_position_y"])
    out["percent"] = np.nan_to_num(row[f"{prefix}_percent"]).astype(np.uint16)
    out["shield"] = np.nan_to_num(row[f"{prefix}_shield"])
    return out


def _pad(row, prefix):
    out = np.zeros(len(row[f"{prefix}_buttons"]), PAD)
    for i, k in enumerate(("main_stick_x", "main_stick_y", "c_stick_x", "c_stick_y")):
        v = row[f"{prefix}_{k}"]
        out["stick"][:, i] = np.where(v == -128, 0, v)
    left, right = (np.where(t == 255, 0, t) for t in (row[f"{prefix}_trigger_l"], row[f"{prefix}_trigger_r"]))
    out["shoulder"] = np.maximum(left, right)
    b = row[f"{prefix}_buttons"]
    for ours, theirs in enumerate(BUTTON_BITS):
        out["buttons"] |= ((b >> theirs) & 1) << ours
    return out


def game(row):
    """Both sides of one dataset row: [(frames as FRAME, labels), (the other side)]. Labels: the two characters
    (libmelee ids), the stage (libmelee id), the player's rank (1 Platinum .. 3 Master, 4 the folder's pro, 0 unknown)
    and whether they won (more stocks on the last frame, then less percent)."""
    players = [_player(row, p) for p in ("p1", "p2")]
    nanas = [_player(row, f"{p}_nana") for p in ("p1", "p2")]
    pads = [_pad(row, p) for p in ("p1", "p2")]
    n = len(players[0])
    items = np.zeros(n, FRAME)[["item_exists", "item_type", "item_state", "item_x", "item_y"]]
    for i in range(ITEMS):
        meta = row[f"item{i}_meta"].astype(np.uint32)
        present = ((row["item_present"] >> i) & 1).astype(bool)
        kind, state = meta & 0x1FFFF, (meta >> 17) & 0x1FF
        items["item_exists"][:, i] = present
        items["item_type"][:, i] = np.where(present & (kind != 65536), kind, 0)
        items["item_state"][:, i] = np.where(present & (state != 256), state, 0)
        items["item_x"][:, i] = np.where(present, np.nan_to_num(row[f"item{i}_pos_x"]), 0)
        items["item_y"][:, i] = np.where(present, np.nan_to_num(row[f"item{i}_pos_y"]), 0)
    stocks = [int((row[f"{p}_state"][-1].astype(np.uint32) >> 17) & 7) for p in ("p1", "p2")]
    score = [(stocks[i], -float(players[i]["percent"][-1])) for i in (0, 1)]
    out = []
    for me in (0, 1):
        f = np.zeros(n, FRAME)
        f["p0"], f["p1"], f["n0"], f["n1"], f["pad"] = players[me], players[1 - me], nanas[me], nanas[1 - me], pads[me]
        for k in items.dtype.names:
            f[k] = items[k]
        out.append((f, dict(character=row[f"p{me + 1}_character"], opponent=row[f"p{2 - me}_character"],
                            stage=row["stage"], rank=row[f"p{me + 1}_rank"], won=score[me] > score[1 - me])))
    return out
