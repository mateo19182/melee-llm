"""Can an attacking Fox force the first hit? An AND/OR search on the real game code (melee-sim-light).

The attacker (P1) wins a position if he has a move such that, whatever the defender (P2) answers, he either lands
the first hit or reaches a position he also wins, within `--frames` frames. The defender picks *after* seeing the
attacker's pick on every decision, so a "yes" is a forced win even against a defender who reads inputs: no guessing
is involved. A "no" only says no forced win exists with these moves inside the horizon.

Moves depend on the fighter's state (standing, airborne, in shield, in the shine, jumpsquat); in every other state
the only move is to wait a frame. Most moves last one or two frames, so both sides decide almost every frame.

Memory: each process remembers decided positions in a table capped at `--tt-mb` (it is emptied when full), and
the number of processes is cut to what the free memory can hold. Finished jobs go to `--out` as they complete, and
a rerun with the same file skips them. Launch long runs with `scripts/search.sh`, which adds a hard memory limit.

Speed: the search plays on one simulator match and takes moves back with `sim/rollback.py` (our patch to
melee-sim-light: about 9 µs per rollback, against 300 µs for the library's lane copy). Each process is exact by
check: after every root job it verifies that no memory page outside the rollback set changed.

    uv run python -m melee_llm.solver.force --gap 14 --ledge 12 --frames 16
"""
from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import os
import time

import melee
import numpy as np

from melee_llm.solver.game import A, B, R, X, Z, Sim

N = (0, 0, 0, 0)
# name -> (frames, input(frame, toward)); stick x is multiplied by `toward` (+1: the opponent is to the right)
def _m(frames, *rows):
    return frames, rows

MOVES = {
    "wait": _m(1, N), "wait2": _m(2, N, N), "in": _m(1, (0, 80, 0, 0)), "out": _m(1, (0, -80, 0, 0)),
    "in2": _m(2, (0, 80, 0, 0), (0, 80, 0, 0)), "out2": _m(2, (0, -80, 0, 0), (0, -80, 0, 0)),
    "shine": _m(1, (B, 0, -80, 0)), "hold_b": _m(1, (B, 0, -80, 0)), "jab": _m(1, (A, 0, 0, 0)),
    "grab": _m(1, (Z, 0, 0, 0)), "usmash": _m(1, (A, 0, 80, 0)), "hop": _m(1, (X, 0, 0, 0)),
    "hop_in": _m(1, (X, 80, 0, 0)), "fullhop": _m(3, (X, 0, 0, 0), (X, 0, 0, 0), (X, 0, 0, 0)),
    "shield2": _m(2, (R, 0, 0, 255), (R, 0, 0, 255)), "hold_shield": _m(2, (R, 0, 0, 255), (R, 0, 0, 255)),
    "roll_in": _m(1, (R, 80, 0, 255)), "roll_out": _m(1, (R, -80, 0, 255)), "spotdodge": _m(1, (R, 0, -80, 255)),
    "shield_grab": _m(1, (R | A, 0, 0, 255)), "jump": _m(1, (X, 0, 0, 0)), "nair": _m(1, (A, 0, 0, 0)),
}
NAMES = list(MOVES)
LEN = np.array([MOVES[n][0] for n in NAMES])
MENUS = {
    "ground": ("wait2", "in2", "out2", "shine", "jab", "hop", "hop_in", "fullhop", "shield2", "grab", "usmash"),
    "air": ("wait2", "in2", "out2", "shine", "jump", "nair"),
    "squat": ("wait", "in", "out"),
    "shine": ("wait", "hold_b", "jump"),
    "shield": ("hold_shield", "wait", "jump", "roll_in", "roll_out", "spotdodge", "shield_grab"),
    "locked": ("wait",),
}
MENU_IDS = {k: tuple(NAMES.index(n) for n in v) for k, v in MENUS.items()}
_ACT = melee.Action
_GROUND = {a.value for a in (_ACT.STANDING, _ACT.WALK_SLOW, _ACT.WALK_MIDDLE, _ACT.WALK_FAST, _ACT.DASHING,
                             _ACT.RUNNING, _ACT.TURNING, _ACT.TURNING_RUN, _ACT.RUN_BRAKE, _ACT.CROUCH_START,
                             _ACT.CROUCHING, _ACT.CROUCH_END, _ACT.LANDING)}
_FREE = _GROUND - {_ACT.LANDING.value, _ACT.RUN_BRAKE.value, _ACT.TURNING_RUN.value}
_AIR = set(range(_ACT.JUMPING_FORWARD.value, _ACT.FALLING_AERIAL_BACKWARD.value + 1))
_SHIELD = {178, 179, 181, 182}
_SHINE = {360, 361, 364, 365, 366, 368}


def menu(slot) -> tuple[int, ...]:
    a = int(slot["action_id"])
    kind = ("ground" if a in _GROUND else "air" if a in _AIR else "squat" if a == _ACT.KNEE_BEND.value
            else "shield" if a in _SHIELD else "shine" if a in _SHINE else "locked")
    return MENU_IDS[kind]


def _key(s) -> tuple:
    return (round(float(s["pos_x"]), 2), round(float(s["pos_y"]), 2), round(float(s["speed_ground_x_self"]), 2),
            round(float(s["speed_air_x_self"]), 2), round(float(s["speed_y_self"]), 2), int(s["action_id"]),
            int(s["action_frame"]), int(s["hitlag"]), round(float(s["shield_hp"]), 1), int(s["facing"]),
            int(s["jumps_left"]))


TT_BYTES = 140  # measured memory per remembered position
WORKER_MB = 600  # a search process before its table grows
RESERVE_MB = 10_000  # memory left for everything else on the machine


def fit_workers(workers: int, tt_mb: int) -> int:
    """As many processes as the free memory holds with their tables full."""
    with open("/proc/meminfo") as f:
        avail = next(int(x.split()[1]) for x in f if x.startswith("MemAvailable")) // 1024
    return max(1, min(workers, (avail - RESERVE_MB) // (WORKER_MB + tt_mb)))


_WARMUP = [N, (B, 0, -80, 0), (X, 0, 0, 0), (A, 0, 0, 0), (0, 80, 0, 0), (0, -80, 0, 0), (R, 0, 0, 255), (B, 0, 0, 0),
           (A, 0, 80, 0), (X, 80, 0, 0), (Z, 0, 0, 0), (R, 80, 0, 255), (R, -80, 0, 255), (R, 0, -80, 255)]


class Search:
    """Depth-first search on one simulator match: make a move, look, take it back (`sim/rollback.py`)."""

    def __init__(self, root: bytes, max_depth: int = 64, trap: bool = False, tt_mb: int = 400):
        import melee_sim as msl
        from melee_llm.sim.rollback import Rollback
        from melee_llm.sim.state import SIM_STAGE
        from melee_llm.sim.world import DATA_DIR
        self.trap, self.max_depth = trap, max_depth
        self.env = msl.EnvBatch(batch_size=1, length=64, action_format="raw", data_dir=str(DATA_DIR))
        players = tuple(msl.PlayerConfig(melee.Character.FOX.value, controller_port=p) for p in (0, 1))
        self.env.configure_match(stage=SIM_STAGE[melee.Stage.FINAL_DESTINATION], seed=0, max_frame=28800,
                                 players=players)
        self.env.reset_all()
        self.env.restore(0, root)
        self.env.reset_cursor()
        self.env.observe()
        s = self.slots()
        self.base = (float(s[0]["percent"]), float(s[1]["percent"]), int(s[0]["stocks"]), int(s[1]["stocks"]))
        # decided positions, by hash of the position: fewest frames proven a yes, most frames proven a no
        self.yes: dict[int, int] = {}
        self.no: dict[int, int] = {}
        self.cap = tt_mb * 1_000_000 // TT_BYTES
        self.expansions = 0
        self.rb = Rollback(self.env, depth=max_depth)
        rng = np.random.default_rng(0)  # learn which pages a frame can change, from 3000 frames of random inputs
        for f in range(3000):
            i, j = rng.integers(len(_WARMUP), size=2)
            self.step(_WARMUP[i], _WARMUP[j])
            if f % 100 == 99:
                self.rb.add(self.rb.changed())
        self.rb.reset()
        self.observe()

    def slots(self):
        return self.env.current_frame[0]["slots"]

    def step(self, p1, p2) -> None:
        env = self.env
        if env.t >= env.length:
            env.reset_cursor()
        row = env.raw_action_view[env.t, 0]["players"]
        for i, (b, mx, my, r) in enumerate((p1, p2)):
            row[i]["buttons"], row[i]["main_x"], row[i]["main_y"] = b, mx, my
            row[i]["c_x"], row[i]["c_y"], row[i]["l"], row[i]["r"] = 0, 0, 0, r
        env.step()

    def observe(self) -> None:
        if self.env.t >= self.env.length:
            self.env.reset_cursor()
        self.env.observe()

    def back(self, level: int) -> None:
        self.rb.rollback(level)
        self.observe()

    def _outcome(self) -> int:
        """+1 the attacker landed the first hit, -1 he was hit or it was a trade, 0 nobody hit yet."""
        s = self.slots()
        d1 = float(s[0]["percent"]) - self.base[0] + 100 * (self.base[2] - int(s[0]["stocks"]))
        d2 = float(s[1]["percent"]) - self.base[1] + 100 * (self.base[3] - int(s[1]["stocks"]))
        return 0 if d1 == 0 and d2 == 0 else 1 if d2 > d1 else -1

    def play(self, pa, pd):
        """Play attacker move `pa` against defender move `pd` from the current state until one of them ends or
        someone is hit. Moves are (id, frame, toward). Returns (outcome, frames used, attacker's rest,
        defender's rest)."""
        self.expansions += 1
        arows, drows = MOVES[NAMES[pa[0]]][1], MOVES[NAMES[pd[0]]][1]
        run = min(len(arows) - pa[1], len(drows) - pd[1])
        out = used = 0
        for f in range(run):
            b, mx, my, r = arows[pa[1] + f]
            db, dx, dy, dr = drows[pd[1] + f]
            self.step((b, mx * pa[2], my, r), (db, dx * pd[2], dy, dr))
            used += 1
            out = self._outcome()
            if out:
                break
        ra = (pa[0], pa[1] + used, pa[2]) if pa[1] + used < len(arows) else None
        rd = (pd[0], pd[1] + used, pd[2]) if pd[1] + used < len(drows) else None
        return out, used, ra, rd

    def options(self, pa, pd):
        s = self.slots()
        toward = 1 if float(s[1]["pos_x"]) >= float(s[0]["pos_x"]) else -1
        att = [pa] if pa else [(m, 0, toward) for m in menu(s[0])]
        dfn = [pd] if pd else [(m, 0, -toward) for m in menu(s[1])]
        return att, dfn

    def _room(self) -> None:
        if len(self.yes) + len(self.no) >= self.cap:
            self.yes.clear()
            self.no.clear()

    def trapped(self, s) -> bool:
        """The shield trap (docs/optimal-play.md, section 9): P2 is in shield and P1 stands next to him, free to
        act. Measured there: every exit from shield loses to a reaction, and a held shield breaks."""
        return (int(s[1]["action_id"]) in (178, 179) and int(s[0]["action_id"]) in _FREE
                and abs(float(s[1]["pos_x"]) - float(s[0]["pos_x"])) <= 10.0
                and float(s[0]["pos_y"]) == float(s[1]["pos_y"]))

    def safe(self, depth: int, pa, pd, frames: int) -> bool:
        """The mirror question: does the defender have a move that survives every attacker move, with the
        attacker picking after seeing it, for `frames` frames? Surviving the horizon counts as safe."""
        if frames <= 0 or depth >= self.max_depth - 1:
            return True
        s = self.slots()
        if self.trap and pa is None and self.trapped(s):
            return False
        key = hash(_key(s[0]) + _key(s[1]) + (pa, pd, "safe"))  # here "yes" is: proven unsafe
        if frames >= self.yes.get(key, 10 ** 6):
            return False
        if frames <= self.no.get(key, -1):
            return True
        att, dfn = self.options(pa, pd)
        self.rb.checkpoint(depth)
        for d in dfn:
            kids = []
            for a in att:
                kids.append(self.play(a, d))
                self.back(depth)
                if kids[-1][0] > 0:
                    break
            if kids[-1][0] > 0:
                continue
            ok = True
            for a, (o, u, ra, rd) in zip(att, kids):
                if o < 0:
                    continue
                self.play(a, d)
                ok = self.safe(depth + 1, ra, rd, frames - u)
                self.back(depth)
                if not ok:
                    break
            if ok:
                self._room()
                self.no[key] = frames
                return True
        self._room()
        self.yes[key] = frames
        return False

    def win(self, depth: int, pa, pd, frames: int) -> bool:
        """Does the attacker force the first hit from the current state within `frames`? Leaves the state as
        it found it."""
        if frames <= 0 or depth >= self.max_depth - 1:
            return False
        s = self.slots()
        if self.trap and pa is None and self.trapped(s):
            return True
        key = hash(_key(s[0]) + _key(s[1]) + (pa, pd))
        if frames >= self.yes.get(key, 10 ** 6):
            return True
        if frames <= self.no.get(key, -1):
            return False
        att, dfn = self.options(pa, pd)
        self.rb.checkpoint(depth)
        for a in att:
            kids = []
            for d in dfn:  # look at every answer first: one that hits the attacker refutes the move at once
                kids.append(self.play(a, d))
                self.back(depth)
                if kids[-1][0] < 0:
                    break
            if kids[-1][0] < 0:
                continue
            ok = True
            for d, (o, u, ra, rd) in zip(dfn, kids):
                if o > 0:
                    continue
                self.play(a, d)
                ok = self.win(depth + 1, ra, rd, frames - u)
                self.back(depth)
                if not ok:
                    break
            if ok:
                self._room()
                self.yes[key] = frames
                return True
        self._room()
        self.no[key] = frames
        return False


def corner(sim: Sim, gap: float, ledge: float, hop: int = 0, shield: int = 0) -> bytes:
    """P2 stands `ledge` units from the right ledge of Final Destination, facing P1, who stands `gap` away.
    With `hop`, P1 has then short-hopped toward P2 and is `hop` frames into it, P2 not having moved.
    With `shield`, P2 has then held his shield for that many frames, P1 standing still."""
    edge = 85.57
    sim.restore(sim.start())
    for _ in range(600):  # P2 walks right
        if float(sim.players()[1]["pos_x"]) >= edge - ledge:
            break
        sim.step([N, (0, 30, 0, 0)])
    sim.idle(20)
    for _ in range(3):  # and turns back to face the stage
        sim.step([N, (0, -25, 0, 0)])
    sim.idle(25)
    for _ in range(900):  # P1 walks in
        if sim.gap() <= gap + 1.0:
            break
        sim.step([(0, 30, 0, 0), N])
    sim.idle(30)
    for f in range(hop):
        sim.step([(X, 40, 0, 0) if f == 0 else (0, 40, 0, 0), N])
    for _ in range(shield):
        sim.step([N, (R, 0, 0, 255)])
    return sim.save()


_S: Search | None = None
_ARGS = None
_MODE = "win"


def _init(root: bytes, frames: int, trap: bool, mode: str, tt_mb: int) -> None:
    global _S, _ARGS, _MODE
    _MODE = mode
    _S, _ARGS = Search(root, max_depth=2 * frames + 8, trap=trap, tt_mb=tt_mb), frames


def _clean(run):
    """Run `run()` and repeat it, with the page added, if the final check finds a page the rollbacks missed."""
    while True:
        out = run()
        missed = _S.rb.verify()
        if not len(missed):
            return out
        _S.rb.add(missed)
        _S.rb.reset()
        _S.observe()
        _S.yes.clear()
        _S.no.clear()


def _open(job):
    """A root joint move: whether it is decided at once (True: for the side being asked about), and the next
    options of the side that picks first."""
    def run():
        a, d = job
        _S.rb.checkpoint(0)
        o, u, ra, rd = _S.play(a, d)
        trapped = o == 0 and _S.trap and ra is None and _S.trapped(_S.slots())
        if _MODE == "win":
            done = True if o > 0 or trapped else False if o < 0 else None
        else:
            done = True if o < 0 else False if o > 0 or trapped else None
        nxt = [] if done is not None else _S.options(ra, rd)[0 if _MODE == "win" else 1]
        _S.back(0)
        return a, d, done, nxt
    return _clean(run)


def _task(job):
    """After root (a, d): does the first picker's next move `m` hold against every reply?"""
    def run():
        a, d, m = job
        _S.rb.checkpoint(0)
        o, u, ra, rd = _S.play(a, d)
        att, dfn = _S.options(m if _MODE == "win" else ra, rd if _MODE == "win" else m)
        _S.rb.checkpoint(1)
        ok = True
        for a2 in att:
            for d2 in dfn:
                o2, u2, ra2, rd2 = _S.play(a2, d2)
                left = _ARGS - u - u2
                if _MODE == "win":
                    ok = o2 > 0 or (o2 == 0 and _S.win(2, ra2, rd2, left))
                else:
                    ok = o2 < 0 or (o2 == 0 and _S.safe(2, ra2, rd2, left))
                _S.back(1)
                if not ok:
                    break
            if not ok:
                break
        _S.back(0)
        n, _S.expansions = _S.expansions, 0
        return a, d, m, ok, n
    return _clean(run)


def solve(gap: float, ledge: float, frames: int, workers: int = 28, trap: bool = False, mode: str = "win",
          hop: int = 0, shield: int = 0, tt_mb: int = 400, out: str | None = None) -> dict:
    """`mode` "win": can the attacker force the first hit against a defender who sees his inputs? "safe": can the
    defender hold against an attacker who sees his? Jobs are split two decisions deep, one per (root joint move,
    first picker's next move), so the workers stay evenly loaded. Each finished job is appended to `out`; jobs already
    in that file (same question) are not run again."""
    t0 = time.time()
    workers = fit_workers(workers, tt_mb)
    sim = Sim()
    root = corner(sim, gap, ledge, hop, shield)
    s = sim.players()
    info = {"p1_y": round(float(s[0]["pos_y"]), 1), "gap": round(sim.gap(), 2), "p2_x": round(float(s[1]["pos_x"]), 2), "p2_facing": int(s[1]["facing"]),
            "frames": frames, "mode": mode, "workers": workers}
    ask = {"gap": gap, "ledge": ledge, "frames": frames, "trap": trap, "mode": mode, "hop": hop, "shield": shield}
    done_jobs: dict[str, tuple[bool, int]] = {}
    if out and os.path.exists(out):
        with open(out) as f:
            for row in map(json.loads, f):
                if row["ask"] == ask:
                    done_jobs[json.dumps(row["job"])] = (row["ok"], row["n"])
    log = open(out, "a") if out else None
    toward = 1 if float(s[1]["pos_x"]) >= float(s[0]["pos_x"]) else -1
    att = [(m, 0, toward) for m in menu(s[0])]
    dfn = [(m, 0, -toward) for m in menu(s[1])]
    sim.world.close()
    result: dict[tuple, bool] = {}
    total = 0
    with mp.get_context("spawn").Pool(workers, initializer=_init, initargs=(root, frames, trap, mode, tt_mb)) as pool:
        jobs = []
        for a, d, done, nxt in pool.imap_unordered(_open, [(a, d) for a in att for d in dfn]):
            result[(a, d)] = bool(done)
            jobs += [(a, d, m) for m in nxt] if done is None else []
        np.random.default_rng(0).shuffle(jobs)
        todo = []
        for a, d, m in jobs:
            if (old := done_jobs.get(json.dumps([a, d, m]))) is None:
                todo.append((a, d, m))
            else:
                result[(a, d)] = result[(a, d)] or old[0]
                total += old[1]
        info["resumed"] = len(jobs) - len(todo)
        for a, d, m, ok, n in pool.imap_unordered(_task, todo):
            result[(a, d)] = result[(a, d)] or ok
            total += n
            if log:
                log.write(json.dumps({"ask": ask, "job": [a, d, m], "ok": ok, "n": n}) + "\n")
                log.flush()
    if log:
        log.close()
    first, second = (0, 1) if mode == "win" else (1, 0)  # which side's move heads each row
    table: dict[str, dict[str, bool]] = {}
    for pair, ok in result.items():
        table.setdefault(NAMES[pair[first][0]], {})[NAMES[pair[second][0]]] = ok
    info["forced"] = [x for x, row in table.items() if all(row.values())]
    info["refuted_by"] = {x: [y for y, ok in row.items() if not ok] for x, row in table.items()}
    info["expansions"], info["seconds"], info["jobs"] = total, round(time.time() - t0, 1), len(jobs)
    return info


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--gap", type=float, nargs="+", default=[14])
    ap.add_argument("--ledge", type=float, default=12, help="how far the defender stands from the ledge behind him")
    ap.add_argument("--frames", type=int, default=12)
    ap.add_argument("--workers", type=int, default=28)
    ap.add_argument("--hop", type=int, default=0, help="start with the attacker this many frames into a short hop")
    ap.add_argument("--safe", action="store_true",
                    help="ask instead whether the defender has a defence that needs no guessing")
    ap.add_argument("--trap", action="store_true", help="count the measured shield trap as a win for the attacker")
    ap.add_argument("--shield", type=int, default=0, help="start with the defender this many frames into his shield")
    ap.add_argument("--tt-mb", type=int, default=400, help="memory for remembered positions, per process")
    ap.add_argument("--out", help="file that collects finished jobs; a rerun continues from it")
    args = ap.parse_args()
    for g in args.gap:
        r = solve(g, args.ledge, args.frames, args.workers, args.trap, "safe" if args.safe else "win", args.hop,
                  args.shield, args.tt_mb, args.out)
        where = (f"gap {r['gap']}, P1 height {r['p1_y']} (P2 at x={r['p2_x']}, facing {'left' if not r['p2_facing'] else 'right'}), "
                 f"{r['frames']} frames: ")
        if args.safe:
            verdict = f"SAFE with {r['forced']}" if r["forced"] else "NO SAFE DEFENCE: the defender must guess"
        else:
            verdict = f"FORCED WIN with {r['forced']}" if r["forced"] else "no forced win"
        print(where + verdict + f"  [{r['expansions']:,} positions, {r['seconds']}s, {r['workers']} processes, "
              f"{r['resumed']} of {r['jobs']} jobs from an earlier run]", flush=True)
        for m, ds in r["refuted_by"].items():
            print(f"     {m:8s} " + ("holds against everything" if not ds else "beaten by: " + ", ".join(ds)))


if __name__ == "__main__":
    main()
