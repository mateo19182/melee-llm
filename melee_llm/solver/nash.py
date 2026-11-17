"""The Fox ditto as the game it is: both players pick an input every frame, at the same time, each knowing
everything up to the previous frame (a reaction is one frame late, as for a bot). Solved exactly to a horizon.

`force.py` gave one side the other's input on the same frame, which only bounds the answer. Here every position
where both can act is a matrix game: rows are P1's inputs, columns P2's, each cell is the value of the position
that pair leads to, and the position's value is that matrix's value (`matrix.solve`). The recursion bottoms out
at the first hit or at the horizon, so the result is exact for the menus and the horizon, on the real game code.

Two payoffs:
- `hit`: 1 if P1 lands the first hit without being hit on that frame, else 0. The value is the chance of a clean
  first hit that P1 can force however P2 plays. 0 means P2 can never be made to guess.
- `net`: +1 if P1 lands the first hit clean, -1 if P2 does, 0 for a trade or no hit. The value says who the
  position favours: above 0, P1 hits first more often than he is hit, however P2 plays.
- `percent`: percent P1 deals minus percent he takes at the first hit; with `--shield-cost c`, a position that
  reaches the horizon unhit is worth c per full shield of shield health P2 has lost more than P1.

Every move lasts one frame, so "hold shield" is choosing shield again each frame.

    scripts/search.sh nash-hop9 -- nash --gap 11.5 --hop 9 --frames 10
"""
from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import os
import time

import melee
import numpy as np

from melee_llm.solver import force
from melee_llm.solver.force import A, B, N, R, X, Z
from melee_llm.solver.matrix import solve as solve_matrix

MOVES = {  # stick x is multiplied by `toward` (+1: the opponent is to the right)
    "wait": N, "in": (0, 80, 0, 0), "out": (0, -80, 0, 0), "shine": (B, 0, -80, 0), "hold_b": (B, 0, -80, 0),
    "jab": (A, 0, 0, 0), "grab": (Z, 0, 0, 0), "hop": (X, 0, 0, 0), "shield": (R, 0, 0, 255),
    "release": N, "roll_in": (R, 80, 0, 255), "roll_out": (R, -80, 0, 255), "spotdodge": (R, 0, -80, 255),
    "shield_grab": (R | A, 0, 0, 255), "jump": (X, 0, 0, 0), "nair": (A, 0, 0, 0),
    "jump_oos": (R | X, 0, 0, 255),  # out of shield the jump needs the shield button held
    # not in the default menus (`--add1`, `--add2`). On the ground A with the stick hard over is a smash; from
    # a squat "usmash", "upb" and "grab" cancel the jump, and "jump" (X still held) makes the hop a full hop
    "usmash": (A, 0, 80, 0), "dsmash": (A, 0, -80, 0), "fsmash": (A, 80, 0, 0), "upb": (B, 0, 80, 0),
    "utilt": (A, 0, 50, 0), "dtilt": (A, 0, -50, 0), "ftilt": (A, 50, 0, 0),
    "walk_in": (0, 30, 0, 0), "walk_out": (0, -30, 0, 0),  # walk_out facing the opponent is a turn
    "crouch": (0, 0, -80, 0), "wd_in": (R, 70, -40, 255), "wd_out": (R, -70, -40, 255), "wd_down": (R, 0, -80, 255),
}
MENUS = {
    # R with the stick down is a spotdodge straight from standing, intangible on its second frame
    "ground": ("wait", "in", "out", "shine", "jab", "hop", "shield", "grab", "spotdodge"),
    "air": ("wait", "in", "out", "shine", "jump", "nair"),
    # B on the last squat frame is a shine on the first airborne one; up-B, up smash and grab cancel the squat
    "squat": ("wait", "in", "out", "shine", "upb", "usmash", "grab"),
    "shine": ("wait", "hold_b", "jump"),
    "shield": ("shield", "release", "jump_oos", "roll_in", "roll_out", "spotdodge", "shield_grab"),
    "release": ("wait", "jump", "spotdodge"),  # the 15 frames of dropping a shield can be cut short by these
    "locked": ("wait",),
}
SHIELD_FULL = 60.0
DOOR = 12.6
_RELEASE, _DODGE = melee.Action.SHIELD_RELEASE.value, melee.Action.SPOTDODGE.value
EDGE = 85.57  # Final Destination's ledges
DODGE_SEEN, DODGE_REACH = 3, 16.8  # how early in the dodge, and from how far, the punish was measured
_HELD = set(range(223, 229))  # pulled in, held or pummelled: a grab moves no percent, so it is read off the state


def menus_with(add: dict[str, tuple[str, ...]] | None) -> dict[str, tuple[str, ...]]:
    """The default menus plus `add`: extra moves by state, e.g. {"ground": ("usmash", "walk_in")}."""
    out = dict(MENUS)
    for k, extra in (add or {}).items():
        out[k] = out[k] + tuple(m for m in extra if m not in out[k])
    return out


def kind(slot) -> str:
    a = int(slot["action_id"])
    return ("ground" if a in force._GROUND else "air" if a in force._AIR
            else "squat" if a == force._ACT.KNEE_BEND.value else "shield" if a in force._SHIELD
            else "release" if a == _RELEASE else "shine" if a in force._SHINE else "locked")


def _menus(s, m1, m2, no_shield: bool):
    k2 = kind(s[1])
    return m1[kind(s[0])], tuple(m for m in m2[k2] if m != "shield") if no_shield and k2 == "ground" else m2[k2]


class Nash(force.Search):
    shortcuts = True  # settle a position by a read-proof pure strategy where there is one (off: to test them)

    def __init__(self, root: bytes, frames: int, payoff: str = "hit", shield_cost: float = 0.0, tt_mb: int = 400,
                 no_shield: bool = False, trap: bool = False, grain: int = 1, add1: dict | None = None,
                 add2: dict | None = None, dodge: bool = False, edge: bool = False, key=force._key):
        super().__init__(root, max_depth=frames + 4, tt_mb=tt_mb)
        self.payoff, self.shield_cost, self.no_shield, self.door = payoff, shield_cost, no_shield, trap
        self.dodge, self.edge = dodge, edge
        # The previous frame's inputs are part of a position: a button still held is not a new press, and the
        # stick's last place decides dash or walk. They are kept per checkpoint so a rollback restores them.
        self.last, self._lasts, self._mark = (N, N), {}, self.rb.checkpoint
        self.rb.checkpoint = self._checkpoint
        self.m1, self.m2, self.key = menus_with(add1), menus_with(add2), key
        self.values: dict[int, float] = {}
        self.grain = grain  # frames each chosen input is held: 2 halves the depth, and reactions come up to 2 late
        self.cap = tt_mb * 1_000_000 // (3 * force.TT_BYTES)  # `values` and the yes/no tables each hold this many
        s = self.slots()
        self.shield0 = (float(s[0]["shield_hp"]), float(s[1]["shield_hp"]))

    def _checkpoint(self, level: int) -> None:
        self._lasts[level] = self.last
        self._mark(level)

    def back(self, level: int) -> None:
        super().back(level)
        self.last = self._lasts[level]

    def where(self) -> tuple:
        s = self.slots()
        return self.key(s[0]) + self.key(s[1]) + self.last[0] + self.last[1]

    def menus(self):
        return _menus(self.slots(), self.m1, self.m2, self.no_shield)

    def leaf(self) -> float | None:
        """The payoff if this frame decided the game, else None."""
        s = self.slots()
        d1 = float(s[0]["percent"]) - self.base[0] + 100 * (self.base[2] - int(s[0]["stocks"]))
        d2 = float(s[1]["percent"]) - self.base[1] + 100 * (self.base[3] - int(s[1]["stocks"]))
        first = self.payoff in ("hit", "net")
        if first:  # a grab is a first hit too
            d1, d2 = d1 + (int(s[0]["action_id"]) in _HELD), d2 + (int(s[1]["action_id"]) in _HELD)
        if d1 == 0 and d2 == 0:
            if first and (self.door and self.shut(s) or self.dodge and self.dodged(s)):
                return 1.0
            if first and self.edge:  # `--edge`: whoever leaves the stage has lost the exchange
                off1, off2 = (abs(float(s[i]["pos_x"])) > EDGE for i in (0, 1))
                if off1 or off2:
                    return float(off2 and not off1) - (self.payoff == "net" and off1 and not off2)
            return None
        if self.payoff == "net":
            return float((d2 > 0 and d1 == 0) - (d1 > 0 and d2 == 0))
        return (1.0 if d2 > 0 and d1 == 0 else 0.0) if self.payoff == "hit" else d2 - d1

    def shut(self, s) -> bool:
        """P2 is in shield with P1 standing free within 12.6 units: every way out is hit on reaction (section 13
        of docs/optimal-play.md), so with `--trap` the position counts as P1's."""
        return (int(s[1]["action_id"]) in (178, 179, 182) and int(s[0]["action_id"]) in force._FREE
                and abs(float(s[1]["pos_x"]) - float(s[0]["pos_x"])) <= DOOR and float(s[0]["pos_y"]) == float(s[1]["pos_y"]))

    def dodged(self, s) -> bool:
        """P2 is early in a spotdodge and P1 stands free within reach, or has just started a shine he can jump
        out of. The dodge is 22 frames with the last 7 hittable and no way to cut it short, longer than our
        horizons, so with `--dodge` the position counts as P1's (measured: section 13 of docs/optimal-play.md)."""
        a = int(s[0]["action_id"])
        return (int(s[1]["action_id"]) == _DODGE and int(s[1]["action_frame"]) <= DODGE_SEEN
                and (a == force._ACT.STANDING.value or a == 360 and int(s[0]["action_frame"]) <= 2)
                and abs(float(s[1]["pos_x"]) - float(s[0]["pos_x"])) <= DODGE_REACH
                and float(s[0]["pos_y"]) == float(s[1]["pos_y"]))

    def horizon(self) -> float:
        if self.payoff == "hit" or not self.shield_cost:
            return 0.0
        s = self.slots()
        lost1, lost2 = self.shield0[0] - float(s[0]["shield_hp"]), self.shield0[1] - float(s[1]["shield_hp"])
        return self.shield_cost * (lost2 - lost1) / SHIELD_FULL

    def joint(self, a: str, d: str) -> None:
        """Both hold their chosen input for `grain` frames, or until a frame decides the game."""
        for i in range(self.grain):
            self._frame(a, d)
            if i + 1 < self.grain and self.leaf() is not None:
                return

    def _frame(self, a: str, d: str) -> None:
        s = self.slots()
        toward = 1 if float(s[1]["pos_x"]) >= float(s[0]["pos_x"]) else -1
        b, x, y, r = MOVES[a]
        db, dx, dy, dr = MOVES[d]
        self.expansions += 1
        self.last = (b, x * toward, y, r), (db, -dx * toward, dy, dr)
        self.step(*self.last)

    def matrix(self, depth: int, frames: int) -> tuple[tuple, tuple, np.ndarray]:
        """The matrix game at the current position: both menus and the value of every pair of inputs."""
        att, dfn = self.menus()
        m = np.zeros((len(att), len(dfn)))
        self.rb.checkpoint(depth)
        for i, a in enumerate(att):
            for j, d in enumerate(dfn):
                self.joint(a, d)
                v = self.leaf()
                m[i, j] = self.value(depth + 1, frames - self.grain) if v is None else v
                self.back(depth)
        return att, dfn, m

    def forced(self, depth: int, frames: int, attacking: bool, who: int = 0) -> bool:
        """About the clean first hit of player `who` (0: P1) on the other. `attacking`: does he have inputs that
        land it even if the other sees each one before answering? Otherwise: does the other have inputs that
        avoid it even if `who` sees each one? Either settles the `hit` game, and bounds the `net` one."""
        if frames <= 0:
            return not attacking
        key = hash(self.where() + (attacking, who))
        yes, no = (self.yes, self.no)
        if frames >= yes.get(key, 10 ** 6):  # proven for the hitter with fewer frames in hand
            return attacking
        if frames <= no.get(key, -1):
            return not attacking
        att, dfn = self.menus()
        hitter, other = (att, dfn) if who == 0 else (dfn, att)
        mine, theirs = (hitter, other) if attacking else (other, hitter)
        won = 1.0 if who == 0 else -1.0  # the leaf where `who` landed it
        self.rb.checkpoint(depth)
        found = False
        for x in mine:
            ok = True
            for y in theirs:
                h, o = (x, y) if attacking else (y, x)
                self.joint(*((h, o) if who == 0 else (o, h)))
                v = self.leaf()
                ok = self.forced(depth + 1, frames - self.grain, attacking, who) if v is None else (v == won) == attacking
                self.back(depth)
                if not ok:
                    break
            if ok:
                found = True
                break
        self._room()
        (yes if found == attacking else no)[key] = frames
        return found

    def value(self, depth: int, frames: int) -> float:
        if frames <= 0:
            return self.horizon()
        key = hash(self.where() + (frames,))
        if (v := self.values.get(key)) is not None:
            return v
        if not self.shortcuts:
            pass
        elif self.payoff == "hit":  # a pure strategy that holds even when read settles the position without a matrix
            if self.forced(depth, frames, False):
                return 0.0
            if self.forced(depth, frames, True):
                return 1.0
        elif self.payoff == "net":  # each side safe from the other when read: nobody can be made to guess
            if self.forced(depth, frames, False, 0) and self.forced(depth, frames, False, 1):
                return 0.0
            if self.forced(depth, frames, True, 0):
                return 1.0
            if self.forced(depth, frames, True, 1):
                return -1.0
        _, _, m = self.matrix(depth, frames)
        lo, hi = float(m.min()), float(m.max())
        v = lo if hi - lo < 1e-12 else float(solve_matrix(m).value)
        if len(self.values) >= self.cap:
            self.values.clear()
        self.values[key] = v
        return v


_S: Nash | None = None
_FRAMES = 0


def _init(root: bytes, frames: int, *args) -> None:
    global _S, _FRAMES
    _S, _FRAMES = Nash(root, frames, *args), frames


def _clean(run):
    while True:
        out = run()
        missed = _S.rb.verify()
        if not len(missed):
            return out
        _S.rb.add(missed)
        _S.rb.reset()
        _S.observe()
        _S.last = (N, N)
        _S.values.clear()
        _S.yes.clear()
        _S.no.clear()


def _open(pair):
    """After the root pair of inputs: the payoff if it decided the game, else the menus of the next position."""
    def run():
        _S.rb.checkpoint(0)
        _S.joint(*pair)
        v = _S.leaf()
        nxt = _S.menus() if v is None else None
        _S.back(0)
        return pair, v, nxt
    return _clean(run)


def _task(job):
    """The value after two given pairs of inputs."""
    def run():
        first, second = job
        _S.rb.checkpoint(0)
        _S.joint(*first)
        _S.rb.checkpoint(1)
        _S.joint(*second)
        v = _S.leaf()
        if v is None:
            v = _S.value(2, _FRAMES - 2 * _S.grain)
        _S.back(0)
        n, _S.expansions = _S.expansions, 0
        return first, second, v, n
    return _clean(run)


def solve(gap: float, ledge: float, frames: int, payoff: str = "hit", shield_cost: float = 0.0, hop: int = 0,
          shield: int = 0, workers: int = 28, tt_mb: int = 400, out: str | None = None, must_exit: bool = False,
          no_shield: bool = False, trap: bool = False, grain: int = 1, first: str | None = None,
          add1: dict | None = None, add2: dict | None = None, away: bool = False, pre: tuple[str, ...] = (),
          dodge: bool = False, edge: bool = False) -> dict:
    """`pre`: P1's inputs before the first decision, one move name per frame, P2 standing or holding his shield."""
    t0 = time.time()
    workers = force.fit_workers(workers, tt_mb)
    sim = force.Sim()
    force.corner(sim, gap, ledge, hop, shield, away)
    for m in pre:
        b, x, y, r = MOVES[m]
        sim.step([(b, x if sim.gap() >= 0 else -x, y, r), (R, 0, 0, 255) if shield else N])
    root = sim.save()
    s = sim.players()
    info = {"gap": round(sim.gap(), 2), "p1_y": round(float(s[0]["pos_y"]), 1), "frames": frames, "payoff": payoff,
            "workers": workers, "p1": melee.Action(int(s[0]["action_id"])).name,
            "p2": melee.Action(int(s[1]["action_id"])).name}
    att, dfn = _menus(s, menus_with(add1), menus_with(add2), no_shield)
    if first:  # P1's first input is given: the value of one plan, not of the position
        att = (first,)
    if must_exit:  # P2 starts in shield and may not keep holding it
        dfn = tuple(d for d in dfn if d != "shield")
    sim.world.close()
    ask = {"gap": gap, "ledge": ledge, "frames": frames, "payoff": payoff, "shield_cost": shield_cost, "hop": hop,
           "shield": shield, "must_exit": must_exit, "no_shield": no_shield, "trap": trap, "grain": grain,
           "first": first, "ledge2": ledge, "menus": 2, "add1": add1, "add2": add2, "away": away, "pre": list(pre),
           "dodge": dodge, "edge": edge}
    ask = json.loads(json.dumps(ask))  # as it reads back from the file
    old: dict[str, tuple[float, int]] = {}
    if out and os.path.exists(out):
        with open(out) as f:
            for row in map(json.loads, f):
                if row["ask"] == ask:
                    old[json.dumps(row["job"])] = (row["v"], row["n"])
    log = open(out, "a") if out else None
    top = np.zeros((len(att), len(dfn)))
    second: dict[tuple, tuple] = {}  # root pair -> (menus, matrix) of the position it leads to
    total = 0
    with mp.get_context("spawn").Pool(workers, initializer=_init,
                                      initargs=(root, frames, payoff, shield_cost, tt_mb, no_shield, trap, grain,
                                                add1, add2, dodge, edge)) as pool:
        jobs = []
        for pair, v, nxt in pool.imap_unordered(_open, [(a, d) for a in att for d in dfn]):
            if v is not None:
                top[att.index(pair[0]), dfn.index(pair[1])] = v
            else:
                second[pair] = (nxt, np.zeros((len(nxt[0]), len(nxt[1]))))
                jobs += [(pair, (a, d)) for a in nxt[0] for d in nxt[1]]
        np.random.default_rng(0).shuffle(jobs)
        todo = []
        for first, sec in jobs:
            if (seen := old.get(json.dumps([first, sec]))) is None:
                todo.append((first, sec))
            else:
                (a2, d2), m = second[first]
                m[a2.index(sec[0]), d2.index(sec[1])] = seen[0]
                total += seen[1]
        info["jobs"], info["resumed"] = len(jobs), len(jobs) - len(todo)
        for first, sec, v, n in pool.imap_unordered(_task, todo):
            (a2, d2), m = second[first]
            m[a2.index(sec[0]), d2.index(sec[1])] = v
            total += n
            if log:
                log.write(json.dumps({"ask": ask, "job": [first, sec], "v": v, "n": n}) + "\n")
                log.flush()
    if log:
        log.close()
    for (a, d), (_, m) in second.items():
        top[att.index(a), dfn.index(d)] = solve_matrix(m).value
    sol = solve_matrix(top)
    info.update(value=float(sol.value), att=att, dfn=dfn, matrix=top.round(3).tolist(), p1_state=info["p1"],
                p2_state=info["p2"], p1={a: round(float(p), 3) for a, p in zip(att, sol.row) if p > 1e-6},
                p2={d: round(float(p), 3) for d, p in zip(dfn, sol.col) if p > 1e-6},
                positions=total, seconds=round(time.time() - t0, 1))
    return info


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--gap", type=float, default=14)
    ap.add_argument("--ledge", type=float, default=12)
    ap.add_argument("--frames", type=int, default=8)
    ap.add_argument("--payoff", choices=("hit", "net", "percent"), default="hit")
    ap.add_argument("--shield-cost", type=float, default=0.0)
    ap.add_argument("--hop", type=int, default=0)
    ap.add_argument("--shield", type=int, default=0)
    ap.add_argument("--must-exit", action="store_true", help="P2 may not keep holding his shield at the start")
    ap.add_argument("--no-shield", action="store_true", help="P2 never starts a shield from the ground")
    ap.add_argument("--trap", action="store_true", help="count P2 in shield next to a free P1 as P1's first hit")
    ap.add_argument("--grain", type=int, default=1, help="frames each input is held (2: half the depth, coarser reactions)")
    ap.add_argument("--first", help="fix P1's first input, to value one plan (for example hop)")
    ap.add_argument("--edge", action="store_true", help="a fighter who leaves the stage has lost the exchange")
    ap.add_argument("--dodge", action="store_true",
                    help="count P2 early in a spotdodge beside a standing or just-shining P1 as P1's first hit")
    ap.add_argument("--away", action="store_true", help="P2 has his back to P1")
    ap.add_argument("--pre", nargs="*", default=[], metavar="MOVE[:N]",
                    help="P1's inputs before the first decision, e.g. walk_in:6 or in:4 (a dash)")
    ap.add_argument("--add1", nargs="*", default=[], metavar="STATE=MOVE,MOVE", help="extra moves for P1")
    ap.add_argument("--add2", nargs="*", default=[], metavar="STATE=MOVE,MOVE", help="extra moves for P2")
    ap.add_argument("--workers", type=int, default=28)
    ap.add_argument("--tt-mb", type=int, default=400)
    ap.add_argument("--out")
    args = ap.parse_args()
    add1, add2 = ({k: tuple(v.split(",")) for k, v in (x.split("=") for x in xs)} or None for xs in (args.add1, args.add2))
    pre = tuple(m for x in args.pre for m in [x.split(":")[0]] * int((x.split(":") + ["1"])[1]))
    r = solve(args.gap, args.ledge, args.frames, args.payoff, args.shield_cost, args.hop, args.shield, args.workers,
              args.tt_mb, args.out, args.must_exit, args.no_shield, args.trap, args.grain, args.first, add1, add2,
              args.away, pre, args.dodge, args.edge)
    unit = {"hit": "chance of a clean first hit for P1", "net": "P1's clean first hits minus P2's",
            "percent": "percent for P1"}[args.payoff]
    print(f"gap {r['gap']}, P1 height {r['p1_y']} ({r['p1_state']} against {r['p2_state']}), {r['frames']} frames: value {r['value']:+.4f} ({unit})  "
          f"[{r['positions']:,} positions, {r['seconds']}s, {r['workers']} processes, "
          f"{r['resumed']} of {r['jobs']} jobs from an earlier run]")
    print(f"   P1 plays {r['p1']}\n   P2 plays {r['p2']}")
    print("   value of each first pair of inputs (rows P1, columns P2):")
    print("   " + " " * 8 + "".join(f"{d[:8]:>9s}" for d in r["dfn"]))
    for a, row in zip(r["att"], r["matrix"]):
        print(f"   {a:8s}" + "".join(f"{v:9.2f}" for v in row), flush=True)


if __name__ == "__main__":
    main()
