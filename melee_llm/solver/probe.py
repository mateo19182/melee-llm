"""Measured answers to "can anyone hit a perfect Fox before he shines?", one character at a time, on the simulator.

- `reach`: every move of the menu from a standing start against a standing, idle Fox at a range of gaps: the
  farthest gap it connects from and on which frame (grabs count when Fox is caught).
- `duel`: the attacker starts a move; Fox sees it and answers on a later frame (1 = the next frame, the best a
  TAS can do) with each reaction he has. A move gets through when every answer still loses the first hit.
- `shine_vs`: Fox shines on the same frame (or a frame earlier or later) as the attacker's move, at close range,
  grounded or both airborne: who gets hit, and whether the hitboxes clank (both in hitlag, nobody damaged). Two
  grounded hitboxes with the clank flag clank before any hurtbox check (ftColl_80078C70); airborne ones never do.

    uv run python -m melee_llm.solver.probe reach --chars MARTH SHEIK
"""
from __future__ import annotations

import argparse
import json
import multiprocessing as mp
from dataclasses import asdict, dataclass
from pathlib import Path

import melee
import numpy as np

from melee_llm.solver.game import MOVES, NONE, Sim, caught, move

FOX = melee.Character.FOX
GAPS = [round(float(g), 1) for g in np.arange(6.0, 46.0, 1.5)] + [50.0, 60.0, 75.0, 90.0, 110.0]
REACTIONS = ("shine", "shield", "spotdodge", "away", "roll_away", "hop", "jab", "usmash", "grab", "dsmash")
WINDOW = 90  # frames a trial runs


@dataclass
class Hit:
    gap: float
    frame: int  # first frame Fox was hit or caught (1 = the frame the move was input)
    damage: float


@dataclass
class Reach:
    char: str
    move: str
    hits: list[Hit]  # every tested gap it connects from

    @property
    def max_gap(self) -> float:
        return max((h.gap for h in self.hits), default=0.0)


def _hurt(before, after) -> bool:
    return float(after["percent"]) > float(before["percent"]) or (caught(after) and not caught(before))


def _row(slot) -> dict:
    return dict(zip(slot.dtype.names, slot.tolist()))


@dataclass
class Outcome:
    hit: list  # first frame (1-based) each player was hit or caught, or None
    clank: int | None  # first frame both entered hitlag with nobody damaged: hitbox met hitbox
    pct: tuple[float, float]


def trial(sim: Sim, state: bytes, m1, m2, delay1: int = 0, delay2: int = 0, frames: int = WINDOW,
          air: int = 0) -> Outcome:
    """P1 plays `m1` from frame `delay1`, P2 plays `m2` from frame `delay2` (idle before). With `air` > 0 both
    short hop on frame 0 and the frame numbers count from `air` frames later, when both are airborne."""
    sim.restore(state)
    if air:
        sim.step([(0x0400, 0, 0, 0, 0, 0)] * 2)
        sim.idle(air - 1)
    f1, f2 = (m if callable(m) else move(m) for m in (m1, m2))
    first, clank = [None, None], None
    a, b = sim.players()
    toward = 1 if b["pos_x"] >= a["pos_x"] else -1
    for f in range(frames):
        pa, pb = _row(a), _row(b)
        sim.step([f1(f - delay1, toward, pa) if f >= delay1 else NONE,
                  f2(f - delay2, -toward, pb) if f >= delay2 else NONE])
        a, b = sim.players()
        hurt = [_hurt(pa, a), _hurt(pb, b)]
        for k in (0, 1):
            if first[k] is None and hurt[k]:
                first[k] = f + 1
        if clank is None and not any(hurt) and int(a["hitlag"]) > pa["hitlag"] and int(b["hitlag"]) > pb["hitlag"] \
                and float(a["shield_hp"]) == pa["shield_hp"] and float(b["shield_hp"]) == pb["shield_hp"]:
            clank = f + 1
        if all(x is not None for x in first):
            break
    return Outcome(first, clank, (float(a["percent"]), float(b["percent"])))


_SIM: dict = {}


def _sim(char, target=FOX) -> Sim:
    if (char, target) not in _SIM:
        for old in _SIM.values():
            old.world.close()
        _SIM.clear()
        _STATES.clear()
        _SIM[char, target] = Sim(char, target)
    return _SIM[char, target]


_STATES: dict = {}


def _states(sim: Sim, gaps) -> list[tuple[float, bytes]]:
    key = (sim.chars, tuple(gaps))
    if key in _STATES:
        return _STATES[key]
    start, out = sim.start(), []
    for g in gaps:
        st = sim.setup(g, start)
        gap = round(sim.gap(), 2)
        if not out or gap != out[-1][0]:
            out.append((gap, st))
    _STATES[key] = out
    return out


def _reach_one(args) -> list[Reach]:
    char, moves, target, defend = args
    sim = _sim(char, target)
    states = _states(sim, GAPS)
    out = []
    for m in moves:
        hits = []
        for gap, st in states:
            o = trial(sim, st, m, defend)
            hit_me, hit_fox = o.hit
            if hit_fox is not None and (hit_me is None or hit_fox <= hit_me):
                hits.append(Hit(gap, hit_fox, round(o.pct[1], 1)))
        out.append(Reach(char.name if target == FOX else target.name, m, hits))
    return out


def reach(chars, moves=tuple(MOVES), workers: int = 8, target=FOX, defend: str = "wait") -> list[Reach]:
    """Each of `chars` attacks `target` (who plays `defend`, e.g. crouch). With `target` other than Fox, rows are
    named after the target, so `--chars FOX --targets ...` lists Fox's reach on each character."""
    jobs = [(c, (m,), target, defend) for c in chars for m in moves]
    with mp.get_context("spawn").Pool(workers) as pool:
        return [r for rs in pool.map(_reach_one, jobs) for r in rs]


@dataclass
class Duel:
    char: str
    move: str
    gap: float
    hit_frame: int  # against an idle Fox
    best: str  # Fox's best answer: "<reaction>@<frame>"
    outcome: str  # through (Fox hit first whatever he does), traded, blocked (nobody hit), punished (attacker hit)
    clank: bool = False  # Fox's best answer clanked with the move (grounded hitbox met grounded hitbox)


def _duel_one(args) -> list[Duel]:
    char, m, gaps, target = args
    sim = _sim(char, target)
    out = []
    for gap, st in _states(sim, gaps):
        idle_hit = trial(sim, st, m, "wait").hit[1]
        if idle_hit is None:
            continue
        rank = {"punished": 3, "blocked": 2, "traded": 1, "through": 0}
        best = ("through", "-", False)
        for r in REACTIONS if target == FOX else REACTIONS + ("ftilt", "dtilt", "utilt", "sh_nair"):
            for d in range(1, idle_hit + 1):
                o = trial(sim, st, m, r, delay2=d)
                hit_me, hit_fox = o.hit
                res = ("blocked" if hit_fox is None and hit_me is None else "punished" if hit_fox is None
                       else "through" if hit_me is None or hit_fox < hit_me else "traded")
                if rank[res] > rank[best[0]]:
                    best = (res, f"{r}@{d}", o.clank is not None)
        out.append(Duel(char.name if target == FOX else f"{char.name}>{target.name}", m, gap, idle_hit, best[1],
                        best[0], best[2]))
    return out


def duel(chars, moves, gaps, workers: int = 8, target=FOX) -> list[Duel]:
    """`target` (Fox by default) reacts with REACTIONS; another character also gets tilts and a short-hop nair, since
    their down-B ("shine") is no shine."""
    jobs = [(c, m, gaps, target) for c in chars for m in moves]
    with mp.get_context("spawn").Pool(workers) as pool:
        return [d for ds in pool.map(_duel_one, jobs) for d in ds]


def _vs_one(args):
    char, m, gaps, offsets, air = args
    sim = _sim(char)
    out = []
    for gap, st in _states(sim, gaps):
        for off in offsets:  # off > 0: Fox shines `off` frames after the attacker's input; < 0: before
            o = trial(sim, st, m, "shine", delay1=max(0, -off), delay2=max(0, off), air=air)
            out.append(dict(char=char.name, move=m, air=bool(air), gap=gap, fox_offset=off, attacker_hit=o.hit[0],
                            fox_hit=o.hit[1], clank=o.clank, attacker_pct=round(o.pct[0], 1),
                            fox_pct=round(o.pct[1], 1)))
    return out


def shine_vs(chars, moves, gaps, offsets=(-2, -1, 0, 1, 2), air: int = 0, workers: int = 8):
    jobs = [(c, m, gaps, offsets, air) for c in chars for m in moves]
    with mp.get_context("spawn").Pool(workers) as pool:
        return [d for ds in pool.map(_vs_one, jobs) for d in ds]


def _reflect_one(args):
    char, m, gap = args
    sim = _sim(char)
    out = []
    for g, st in _states(sim, [gap]):
        h = trial(sim, st, m, "wait", frames=150).hit[1]
        if h is None:
            continue
        seen = {"reflected": [], "blocked": [], "hit": []}
        for d in range(0, h):
            o = trial(sim, st, m, "shine_hold", delay2=d, frames=150)
            seen["reflected" if o.hit[0] is not None and o.hit[1] is None else
                 "blocked" if o.hit[1] is None else "hit"].append(d)
        out.append(dict(char=char.name, move=m, gap=g, idle_hit=h, **{k: len(v) for k, v in seen.items()},
                        first_reflect=min(seen["reflected"], default=None)))
    return out


def reflect(chars, moves, gap: float, workers: int = 8):
    """Fox raises and holds his reflector `d` frames after the attacker fires, for every `d` before the projectile
    would hit him idle: how many timings reflect it (the attacker takes damage), just stop it, or still get hit."""
    jobs = [(c, m, gap) for c in chars for m in moves]
    with mp.get_context("spawn").Pool(workers) as pool:
        return [d for ds in pool.map(_reflect_one, jobs) for d in ds]


def _chars(names) -> list[melee.Character]:
    return [melee.Character[n.upper()] for n in names]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("what", choices=("reach", "duel", "shine_vs", "reflect"))
    ap.add_argument("--targets", nargs="+", default=["FOX"], help="reach, duel: defenders (one run each)")
    ap.add_argument("--defend", default="wait", help="reach: the defender's move, e.g. crouch")
    ap.add_argument("--chars", nargs="+", default=["FOX"])
    ap.add_argument("--moves", nargs="+", default=list(MOVES))
    ap.add_argument("--gaps", type=float, nargs="+", default=[8, 10, 12, 15, 20, 25, 30])
    ap.add_argument("--air", type=int, default=0, help="shine_vs: both short hop and act this many frames later")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()
    chars = _chars(args.chars)
    if args.what == "reach":
        rows = [r for t in _chars(args.targets) for r in reach(chars, args.moves, args.workers, t, args.defend)]
        for r in rows:
            far = max(r.hits, key=lambda h: h.gap, default=None)
            fast = min(r.hits, key=lambda h: h.frame, default=None)
            print(f"{r.char:12s} {r.move:12s} reach {r.max_gap:6.1f}"
                  + (f"  (frame {far.frame} there, {far.damage}%)  fastest frame {fast.frame}" if far else ""))
        data = [asdict(r) | {"max_gap": r.max_gap} for r in rows]
    elif args.what == "duel":
        rows = [d for t in _chars(args.targets) for d in duel(chars, args.moves, args.gaps, args.workers, t)]
        for d in rows:
            print(f"{d.char:12s} {d.move:12s} gap {d.gap:6.2f} hits idle Fox on f{d.hit_frame:<3d} -> {d.outcome:9s}"
                  f" (Fox: {d.best}{', clank' if d.clank else ''})")
        data = [asdict(d) for d in rows]
    elif args.what == "reflect":
        data = reflect(chars, args.moves, args.gaps[0], args.workers)
        for d in data:
            print(f"{d['char']:12s} {d['move']:12s} gap {d['gap']:6.2f} idle hit f{d['idle_hit']:<4d} "
                  f"reflected {d['reflected']:3d}  blocked {d['blocked']:3d}  hit {d['hit']:3d}")
    else:
        data = shine_vs(chars, args.moves, args.gaps, air=args.air, workers=args.workers)
        for d in data:
            print(f"{d['char']:11s} {d['move']:8s} {'air' if d['air'] else 'ground'} gap {d['gap']:6.2f} "
                  f"Fox {d['fox_offset']:+d}f: attacker hit f{d['attacker_hit']} ({d['attacker_pct']}%), "
                  f"Fox hit f{d['fox_hit']} ({d['fox_pct']}%), clank f{d['clank']}")
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(data, indent=1))


if __name__ == "__main__":
    main()
