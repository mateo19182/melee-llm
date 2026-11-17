"""Can a Fox be squeezed? A map of what a defender may do, by approach, distance and room behind him.

The question behind docs/optimal-play.md sections 13 and 14: a Fox who can never be made to guess has, at every
moment, an input that is safe even if the attacker sees it before answering. Whether one exists for the next
`frames` frames is the C forced search of melee-brute (`Forced.safe`), with one input a frame for both sides.
This module asks it over a grid of starting positions and under three conditions:

- `free`: the defender may do anything. No safe first input means he has to guess here.
- `hold`: he also loses if he is ever `--give` units behind where he started. Safe when free but not when
  holding means he is squeezed: he keeps his safety only by giving ground.
- `edge`: he also loses if he leaves the stage. For positions near the ledge.

Known results are rules, not searched again (both from section 13): a shielding Fox with a free Fox within 14.39
units cannot get out, and a spotdodge seen early by a Fox standing within 16.8 units is hit at its end. Both are
the attacker's.

    MOD=squeeze scripts/search.sh squeeze-8 -- --grid mid ledge --frames 8
"""
from __future__ import annotations

import argparse
import json
import mmap
import multiprocessing as mp
import os
import time

DOOR = 14.39  # the widest gap at which the shield door was verified shut
DODGE, DODGE_REACH = 235, 16.8
SHIELDING = frozenset({178, 179, 182})  # shield coming up, held, and its first frames (which reflect)
WORKER_MB, RESERVE_MB = 250, 10_000
KINDS = ("stand", "walk", "dash")
GAPS = (10.4, 11.0, 11.6, 12.2, 12.8, 13.4, 14.0, 14.6, 15.2, 16.0, 17.0, 18.0, 20.0, 22.0, 25.0)
GRIDS = {  # name -> (kinds, gaps, rooms behind the defender, conditions)
    "pilot": (("stand", "walk"), (12.8, 14.0), (60.0, 3.0), ("free", "hold", "edge")),
    "mid": (KINDS, GAPS, (60.0,), ("free", "hold")),
    "ledge": (KINDS, GAPS, (0.5, 3.0, 6.0, 10.0, 15.0, 21.0), ("free", "edge")),
}


def root(kind: str, gap: float, room: float) -> tuple[bytes, dict]:
    """P2 stands `room` units from the right ledge, facing P1, who is to his left: standing about `gap` away
    (`stand`), walking in and just inside `gap` (`walk`), or a few frames into a dash from `gap + 5` (`dash`).
    Returns the savestate and what the position is."""
    from melee_brute import Match, fox, pad
    m = Match()
    m.start()
    x = lambda i: float(m.players()[i]["pos_x"])
    target = fox.LEDGE - room
    for _ in range(900):  # P2 walks to his spot, then turns to face the stage
        if abs(x(1) - target) < 0.6:
            break
        m.step(pad(), pad(x=30 if x(1) < target else -30))
    m.step(frames=25)
    if int(m.players()[1]["facing"]) > 0:
        m.step(pad(), pad(x=-25), frames=3)
        m.step(frames=25)
    stop = {"stand": gap + 2.3, "walk": gap, "dash": gap + 7.3}[kind]  # a walk stopped slides 2.3 further
    for _ in range(900):  # P1 walks in
        if x(1) - x(0) <= stop:
            break
        m.step(pad(x=30))
    if kind != "walk":
        m.step(frames=30)
    if kind == "dash":
        for _ in range(12):
            if x(1) - x(0) <= gap:
                break
            m.step(pad(x=80))
    a, b = m.players()
    at = {"kind": kind, "gap": round(x(1) - x(0), 2), "room": round(fox.LEDGE - x(1), 2), "x2": x(1),
          "actions": [int(a["action_id"]), int(b["action_id"])], "facing": [int(a["facing"]), int(b["facing"])]}
    state = m.save()
    m.close()
    return state, at


def rules(condition: str, x2: float, give: float):
    from melee_brute import Trap, Zone, fox
    anyone = frozenset(range(1024))
    lost = {"free": None, "hold": x2 + give, "edge": fox.LEDGE}[condition]
    zones = () if lost is None else (Zone("attacker", anyone, anyone, x=(lost, 1e9), same_y=False),)
    # A spotdodge is 22 frames, longer than these searches. Measured (section 13): seen in its first 3 frames by
    # a Fox standing within 16.8 units, or 2 frames into a shine he can jump out of, it is hit at its end.
    dodge = dict(defender=frozenset({DODGE}), gap=(0, DODGE_REACH), either_side=True, defender_frame=3)
    zones += (Zone("attacker", frozenset({14}), **dodge), Zone("attacker", frozenset({360}), attacker_frame=2, **dodge))
    return fox.frame_rules(trap=Trap(frozenset(fox.FREE), SHIELDING, DOOR), zones=zones)


_M = _TABLE = None


def _job(job: dict) -> dict:
    """Which first inputs of the defender are safe for `frames` frames against an attacker who sees each of his
    inputs before answering, and what beats the others."""
    global _M, _TABLE
    from melee_brute import Forced, Match
    if _M is None:
        _M, _TABLE = Match(), mmap.mmap(-1, job["table_mb"] << 20)
    t0 = time.time()
    _M.load(job["state"])
    f = Forced(_M, rules(job["condition"], job["at"]["x2"], job["give"]), table=_TABLE)
    att, dfn = f.options()
    _M.checkpoint(0)
    safe, beaten = [], {}
    for d in dfn:
        for a in att:
            o, used, ra, rd = f.play(a, d)
            ok = o < 0 if o else f.safe(job["frames"] - used, ra, rd, depth=1)
            _M.rollback(0)
            if not ok:
                beaten[d[0]] = a[0]
                break
        else:
            safe.append(d[0])
    return {"ask": job["ask"], "at": job["at"], "safe": safe, "beaten": beaten, "positions": f.positions,
            "seconds": round(time.time() - t0, 1)}


def fit_workers(workers: int, table_mb: int) -> int:
    with open("/proc/meminfo") as f:
        avail = next(int(x.split()[1]) for x in f if x.startswith("MemAvailable")) // 1024
    return max(1, min(workers, (avail - RESERVE_MB) // (WORKER_MB + table_mb)))


def run(grid: str, frames: int, give: float, out: str, workers: int, table_mb: int) -> None:
    kinds, gaps, rooms, conditions = GRIDS[grid]
    done = set()
    if os.path.exists(out):
        with open(out) as f:
            done = {json.dumps(json.loads(line)["ask"], sort_keys=True) for line in f}
    jobs = []
    for room in rooms:
        for kind in kinds:
            for gap in gaps:
                state, at = None, None
                for condition in conditions:
                    ask = {"v": 1, "kind": kind, "gap": gap, "room": room, "condition": condition, "frames": frames,
                           "give": give if condition == "hold" else 0}
                    if json.dumps(ask, sort_keys=True) in done:
                        continue
                    if state is None:
                        state, at = root(kind, gap, room)
                    jobs.append({"ask": ask, "at": at, "state": state, "condition": condition, "frames": frames,
                                 "give": give, "table_mb": table_mb})
    workers = fit_workers(workers, table_mb)
    print(f"{grid}: {len(jobs)} jobs to run, {len(done)} already in {out}, {workers} processes", flush=True)
    jobs.sort(key=lambda j: -j["ask"]["gap"])  # far positions are the cheap ones: first results come early
    t0, n = time.time(), 0
    with mp.get_context("spawn").Pool(workers) as pool, open(out, "a") as log:
        for row in pool.imap_unordered(_job, jobs):
            log.write(json.dumps(row) + "\n")
            log.flush()
            n += 1
            a = row["ask"]
            print(f"[{n}/{len(jobs)} {time.time() - t0:6.0f}s] {a['kind']:5s} gap {row['at']['gap']:5.2f} room "
                  f"{row['at']['room']:5.2f} {a['condition']:4s} {frames}f: "
                  f"{'safe with ' + ' '.join(row['safe']) if row['safe'] else 'NO SAFE INPUT'} "
                  f"({row['positions']:,} positions, {row['seconds']} s)", flush=True)


def table(out: str) -> str:
    """The finished jobs as one table per condition and frame count: rows by gap, a column per approach and room."""
    rows = [json.loads(line) for line in open(out)]
    text = []
    for key in sorted({(r["ask"]["condition"], r["ask"]["frames"]) for r in rows}):
        part = [r for r in rows if (r["ask"]["condition"], r["ask"]["frames"]) == key]
        cols = sorted({(r["ask"]["room"], r["ask"]["kind"]) for r in part})
        text.append(f"\n{key[0]}, {key[1]} frames. The gap as measured, then the defender's safe first inputs "
                    "(- none: he has to guess)")
        text.append("gap    " + " | ".join(f"{kind} room {room:g}" for room, kind in cols))
        for gap in sorted({r["ask"]["gap"] for r in part}):
            cells = []
            for room, kind in cols:
                r = next((r for r in part if (r["ask"]["room"], r["ask"]["kind"], r["ask"]["gap"]) == (room, kind, gap)),
                         None)
                cells.append("?" if r is None else f"{r['at']['gap']:.1f}: " + (" ".join(r["safe"]) or "-"))
            text.append(f"{gap:5.1f}  " + " | ".join(cells))
    return "\n".join(text)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--grid", choices=GRIDS, nargs="+", default=["pilot"], help="run these one after another")
    ap.add_argument("--frames", type=int, default=8)
    ap.add_argument("--give", type=float, default=3.0, help="units of retreat that lose under `hold`")
    ap.add_argument("--workers", type=int, default=24)
    ap.add_argument("--table-mb", type=int, default=256, help="memory for decided positions, per process")
    ap.add_argument("--out", required=True)
    ap.add_argument("--table", action="store_true", help="print the finished jobs of --out as tables and stop")
    args = ap.parse_args()
    if args.table:
        print(table(args.out))
    else:
        for grid in args.grid:
            run(grid, args.frames, args.give, args.out, args.workers, args.table_mb)


if __name__ == "__main__":
    main()
