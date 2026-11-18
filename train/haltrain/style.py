"""How a Yoshi executes: technique counts from game frames (docs/yoshi.md, section 7).

    python -m haltrain.style amsa:400 /mnt/data/melee/farm/agree-1/d0-1 /mnt/data/melee/farm/agree-1/d10-1 [--against FOX]

A source is `amsa:N` (the first N of aMSa's human games with him on Yoshi, from a scratch copy of HAL's dataset) or a
farm output folder (haltrain.farm --out; the first player is counted). Each row of the table is one source.

What is counted, all from the animation state each frame:
- aerials per minute, and the share started straight out of the double jump (double-jump cancelled);
- the share of aerial landings that were L-cancelled, from how long the landing lasted (down air is left out);
- double-jump lands per minute: a double jump that ends on the ground without a fall in between;
- shields per minute, and parries per minute: the opponent's attack freezes on Yoshi's shield start-up while Yoshi
  is not frozen and nobody takes damage. This one is an approximation: an attack that hits an egg in that moment
  counts too.
"""
import argparse
import json
from pathlib import Path

import numpy as np

YOSHI = 14                      # libmelee's internal character id, as HAL's columns store it
AERIALS = (65, 66, 67, 68, 69)  # neutral, forward, back, up, down air
LANDING = {70: (15, 7), 71: (21, 10), 72: (15, 7), 73: (19, 9)}  # Yoshi's landing lag: normal, L-cancelled
DOUBLE_JUMP = (27, 28)
SHIELD_START = 341             # Yoshi's own shield start-up state: 6 frames, the parry window
SCRATCH = "/mnt/data/melee/hal-count/pro/amsa"  # HAL's loaders delete shards they do not expect: never the originals
FIELDS = ("action", "airborne", "hitlag_left", "percent", "character")


def count(me, opp):
    """Counts for one game. me, opp: {field: array over frames}."""
    action = me["action"]
    starts = np.flatnonzero(np.r_[True, action[1:] != action[:-1]])
    state, length = action[starts], np.diff(np.r_[starts, len(action)])
    before = np.r_[-1, state[:-1]]
    grounded_next = np.r_[me["airborne"][starts[1:]] == 0, False]
    aerial = np.isin(state, AERIALS)
    out = {"minutes": len(action) / 3600, "aerials": int(aerial.sum()),
           "djc": int((aerial & np.isin(before, DOUBLE_JUMP)).sum()),
           "double_jumps": int(np.isin(state, DOUBLE_JUMP).sum()),
           "dj_lands": int((np.isin(state, DOUBLE_JUMP) & grounded_next).sum()),
           "shields": int((state == SHIELD_START).sum()), "landings": 0, "l_cancels": 0}
    for lag, (full, cancelled) in LANDING.items():
        runs = length[state == lag]
        out["landings"] += len(runs)
        out["l_cancels"] += int((runs <= (full + cancelled) // 2).sum())
    froze = (opp["hitlag_left"][1:] > 0) & (opp["hitlag_left"][:-1] == 0)
    unhurt = (opp["percent"][1:] == opp["percent"][:-1]) & (me["percent"][1:] == me["percent"][:-1])
    starting = (action[1:] == SHIELD_START) | (action[:-1] == SHIELD_START)
    out["parries"] = int((froze & unhurt & starting & (me["hitlag_left"][1:] == 0)).sum())
    return out


def human(n, against=None):
    """aMSa's games with exactly one Yoshi, as (me, opp) pairs."""
    from hal.data.policy_world_schema import decode_policy_world_replay
    from hal.training.validation_replay_loader import patch_streaming
    from streaming import Stream, StreamingDataset

    patch_streaming()
    games = StreamingDataset(streams=[Stream(local=SCRATCH, split="train")], shuffle=False, cache_limit="60gb")
    found = 0
    for i in range(len(games)):
        g = decode_policy_world_replay(games[i])
        sides = [{f: np.asarray(g[f"{p}_{f}"]) for f in FIELDS} for p in ("p1", "p2")]
        yoshi = [int(s["character"][0]) == YOSHI for s in sides]
        if sum(yoshi) != 1:
            continue
        me, opp = (sides[0], sides[1]) if yoshi[0] else (sides[1], sides[0])
        if against is None or int(opp["character"][0]) == against:
            yield me, opp
            found += 1
            if found == n:
                return


def farm(folder, against=None):
    """The games of a farm output folder, the first player as `me`."""
    from hal.data.schema import MDS_PER_FRAME_DTYPES
    from hal.sim.native import OBSERVATION_FIELDS

    where = {name: i for i, name in enumerate(OBSERVATION_FIELDS)}
    for line in (Path(folder) / "results.jsonl").read_text().splitlines():
        row = json.loads(line)
        words = np.load(Path(folder) / row["tape"])["records"]["columns"]
        sides = [{f: words[:, where[f"p{p}_{f}"]].view(np.dtype(MDS_PER_FRAME_DTYPES[f"p{p}_{f}"])) for f in FIELDS}
                 for p in (row["a_port"], 3 - row["a_port"])]
        if against is None or int(sides[1]["character"][-1]) == against:
            yield sides[0], sides[1]


def table(sources, against=None):
    import melee

    against = None if against is None else int(melee.Character[against].value)
    print("| Source | Games | Aerials/min | Double-jump cancelled | L-cancelled | Double-jump lands/min | Shields/min "
          "| Parries/min |\n|---|---|---|---|---|---|---|---|")
    for source in sources:
        games = human(int(source[5:]), against) if source.startswith("amsa:") else farm(source, against)
        total, n = {}, 0
        for me, opp in games:
            n += 1
            for k, v in count(me, opp).items():
                total[k] = total.get(k, 0) + v
        if not n:
            print(f"| {source} | 0 | | | | | | |")
            continue
        m = total["minutes"]
        print(f"| {source} | {n} | {total['aerials'] / m:.1f} | {total['djc'] / max(total['aerials'], 1):.0%} "
              f"| {total['l_cancels'] / max(total['landings'], 1):.0%} | {total['dj_lands'] / m:.2f} "
              f"| {total['shields'] / m:.1f} | {total['parries'] / m:.2f} |", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("sources", nargs="+")
    ap.add_argument("--against", help="only games against this character, e.g. FOX")
    a = ap.parse_args()
    table(a.sources, a.against)


if __name__ == "__main__":
    main()
