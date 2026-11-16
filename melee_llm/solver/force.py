"""Can an attacking Fox force the first hit? An AND/OR search on the real game code (melee-sim-light).

The attacker (P1) wins a position if he has a move such that, whatever the defender (P2) answers, he either lands
the first hit or reaches a position he also wins, within `--frames` frames. The defender picks *after* seeing the
attacker's pick on every decision, so a "yes" is a forced win even against a defender who reads inputs: no guessing
is involved. A "no" only says no forced win exists with these moves inside the horizon.

Moves depend on the fighter's state (standing, airborne, in shield, in the shine, jumpsquat); in every other state
the only move is to wait a frame. Most moves last one or two frames, so both sides decide almost every frame.

Speed: the search never serializes a state. All positions live in lanes of one simulator batch; branching is an
in-batch lane copy (about 0.3 ms against 2.5 ms for save/restore), and each attacker move is tried against all
defender answers in one batched step. One core does about 2,700 positions/s; the machine tops out near 10,500/s
at 8 processes, because every branch copies the simulator's 1 MB state and that saturates memory bandwidth.
Python is about 5% of the time.

    uv run python -m melee_llm.solver.force --gap 14 --ledge 12 --frames 16
"""
from __future__ import annotations

import argparse
import multiprocessing as mp
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


class Search:
    BLOCK = 12  # lanes per depth: one per defender answer

    def __init__(self, root: bytes, max_depth: int = 48, trap: bool = False):
        self.trap = trap
        import melee_sim as msl
        from melee_llm.sim.state import SIM_STAGE
        from melee_llm.sim.world import DATA_DIR
        self.n = 1 + self.BLOCK * max_depth
        self.max_depth = max_depth
        self.env = msl.EnvBatch(batch_size=self.n, length=64, action_format="raw", data_dir=str(DATA_DIR))
        players = tuple(msl.PlayerConfig(melee.Character.FOX.value, controller_port=p) for p in (0, 1))
        self.env.configure_match(stage=SIM_STAGE[melee.Stage.FINAL_DESTINATION], seed=0, max_frame=28800,
                                 players=players)
        self.env.reset_all()
        self.env.restore(0, root)
        self.env.reset_cursor()
        self.env.observe()
        s = self.slots(0)
        self.base = (float(s[0]["percent"]), float(s[1]["percent"]), int(s[0]["stocks"]), int(s[1]["stocks"]))
        self.tt: dict[tuple, list[int]] = {}  # key -> [fewest frames proven a win, most frames proven not a win]
        self.expansions = 0
        self.inputs = np.zeros((self.n, 2, 4), dtype=np.int32)

    def slots(self, lane: int):
        return self.env.current_frame[lane]["slots"]

    def _step(self, mask: np.ndarray) -> None:
        env = self.env
        if env.t >= env.length:
            env.reset_cursor()
        row = env.raw_action_view[env.t]["players"]
        for p in (0, 1):
            row["buttons"][:, p], row["main_x"][:, p] = self.inputs[:, p, 0], self.inputs[:, p, 1]
            row["main_y"][:, p], row["r"][:, p] = self.inputs[:, p, 2], self.inputs[:, p, 3]
            row["c_x"][:, p], row["c_y"][:, p], row["l"][:, p] = 0, 0, 0
        env.step(mask)

    def _outcome(self, lane: int) -> int:
        """+1 the attacker landed the first hit, -1 he was hit or it was a trade, 0 nobody hit yet."""
        s = self.slots(lane)
        d1 = float(s[0]["percent"]) - self.base[0] + 100 * (self.base[2] - int(s[0]["stocks"]))
        d2 = float(s[1]["percent"]) - self.base[1] + 100 * (self.base[3] - int(s[1]["stocks"]))
        return 0 if d1 == 0 and d2 == 0 else 1 if d2 > d1 else -1

    def expand(self, lane: int, depth: int, pa, pd_list):
        """Play attacker move `pa` against every defender move in `pd_list` from `lane`. Moves are
        (id, frame, toward). Returns per child: (lane, outcome, frames used, attacker's rest, defender's rest)."""
        k = len(pd_list)
        lanes = np.arange(k, dtype=np.uint32) + 1 + depth * self.BLOCK
        self.env.copy_matches_from(self.env, lanes, np.full(k, lane, dtype=np.uint32))
        self.expansions += k
        run = np.array([min(LEN[pa[0]] - pa[1], LEN[d[0]] - d[1]) for d in pd_list])
        out, used = np.zeros(k, dtype=int), np.zeros(k, dtype=int)
        mask = np.zeros(self.n, dtype=np.uint8)
        for f in range(int(run.max())):
            live = (out == 0) & (f < run)
            if not live.any():
                break
            mask[:] = 0
            mask[lanes[live]] = 1
            b, mx, my, r = MOVES[NAMES[pa[0]]][1][pa[1] + f] if pa[1] + f < LEN[pa[0]] else N
            for c in np.flatnonzero(live):
                d = pd_list[c]
                db, dx, dy, dr = MOVES[NAMES[d[0]]][1][d[1] + f]
                self.inputs[lanes[c], 0] = (b, mx * pa[2], my, r)
                self.inputs[lanes[c], 1] = (db, dx * d[2], dy, dr)
            self._step(mask)
            for c in np.flatnonzero(live):
                used[c] += 1
                out[c] = self._outcome(int(lanes[c]))
        res = []
        for c in range(k):
            d, u = pd_list[c], int(used[c])
            ra = (pa[0], pa[1] + u, pa[2]) if pa[1] + u < LEN[pa[0]] else None
            rd = (d[0], d[1] + u, d[2]) if d[1] + u < LEN[d[0]] else None
            res.append((int(lanes[c]), int(out[c]), u, ra, rd))
        return res

    def options(self, lane: int, pa, pd):
        s = self.slots(lane)
        toward = 1 if float(s[1]["pos_x"]) >= float(s[0]["pos_x"]) else -1
        att = [pa] if pa else [(m, 0, toward) for m in menu(s[0])]
        dfn = [pd] if pd else [(m, 0, -toward) for m in menu(s[1])]
        return att, dfn

    def trapped(self, s) -> bool:
        """The shield trap (docs/optimal-play.md, section 9): P2 is in shield and P1 stands next to him, free to
        act. Measured there: every exit from shield loses to a reaction, and a held shield breaks."""
        return (int(s[1]["action_id"]) in (178, 179) and int(s[0]["action_id"]) in _FREE
                and abs(float(s[1]["pos_x"]) - float(s[0]["pos_x"])) <= 10.0 and float(s[0]["pos_y"]) == float(s[1]["pos_y"]))

    def win(self, lane: int, depth: int, pa, pd, frames: int) -> bool:
        if frames <= 0 or depth >= self.max_depth - 1:
            return False
        s = self.slots(lane)
        if self.trap and pa is None and self.trapped(s):
            return True
        key = _key(s[0]) + _key(s[1]) + (pa, pd)
        seen = self.tt.setdefault(key, [10 ** 6, -1])
        if frames >= seen[0]:
            return True
        if frames <= seen[1]:
            return False
        att, dfn = self.options(lane, pa, pd)
        for a in att:
            kids = self.expand(lane, depth, a, dfn)
            if any(o < 0 for _, o, _, _, _ in kids):
                continue
            if all(o > 0 or self.win(ln, depth + 1, ra, rd, frames - u) for ln, o, u, ra, rd in kids):
                seen[0] = frames
                return True
        seen[1] = frames
        return False


def corner(sim: Sim, gap: float, ledge: float) -> bytes:
    """P2 stands `ledge` units from the right ledge of Final Destination, facing P1, who stands `gap` away."""
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
    return sim.save()


_S: Search | None = None
_ARGS = None


def _init(root: bytes, frames: int, trap: bool) -> None:
    global _S, _ARGS
    _S, _ARGS = Search(root, max_depth=frames + 4, trap=trap), frames


def _task(job):
    """Replay a path of joint moves from the root, then search below it."""
    path, frames = job
    lane, pa, pd = 0, None, None
    for depth, (a, d) in enumerate(path):
        (lane, o, u, pa, pd), = _S.expand(lane, depth, a, [d])
        frames -= u
        if o != 0:
            return path, o > 0, _S.expansions
    return path, _S.win(lane, len(path), pa, pd, frames), _S.expansions


def solve(gap: float, ledge: float, frames: int, workers: int = 8, trap: bool = False) -> dict:
    """One job per root (attacker move, defender answer). More than about 8 workers adds nothing: the
    simulator's state copy saturates memory bandwidth."""
    t0 = time.time()
    sim = Sim()
    root = corner(sim, gap, ledge)
    b = sim.players()[1]
    info = {"gap": round(sim.gap(), 2), "p2_x": round(float(b["pos_x"]), 2), "p2_facing": int(b["facing"]),
            "frames": frames}
    sim.world.close()
    s = Search(root, max_depth=2, trap=trap)
    att, dfn = s.options(0, None, None)
    del s
    jobs = [(((a, d),), frames) for a in att for d in dfn]
    table: dict[str, dict[str, bool]] = {}
    with mp.get_context("spawn").Pool(workers, initializer=_init, initargs=(root, frames, trap)) as pool:
        for path, ok, _ in pool.imap_unordered(_task, jobs):
            (a, d), = path
            table.setdefault(NAMES[a[0]], {})[NAMES[d[0]]] = ok
        total = sum(pool.map(_count, range(workers * 4)))
    info["forced"] = [x for x, row in table.items() if all(row.values())]
    info["refuted_by"] = {x: [y for y, ok in row.items() if not ok] for x, row in table.items()}
    info["expansions"], info["seconds"] = total, round(time.time() - t0, 1)
    return info


def _count(_):
    n, _S.expansions = _S.expansions, 0
    time.sleep(0.05)  # let every worker take a share of these
    return n


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--gap", type=float, nargs="+", default=[14])
    ap.add_argument("--ledge", type=float, default=12, help="how far the defender stands from the ledge behind him")
    ap.add_argument("--frames", type=int, default=12)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--trap", action="store_true", help="count the measured shield trap as a win for the attacker")
    args = ap.parse_args()
    for g in args.gap:
        r = solve(g, args.ledge, args.frames, args.workers, args.trap)
        print(f"gap {r['gap']} (P2 at x={r['p2_x']}, facing {'left' if not r['p2_facing'] else 'right'}), "
              f"{r['frames']} frames: " + (f"FORCED WIN with {r['forced']}" if r["forced"] else "no forced win")
              + f"  [{r['expansions']:,} positions, {r['seconds']}s]", flush=True)
        for a, ds in r["refuted_by"].items():
            print(f"     {a:8s} " + ("wins against every answer" if not ds else "answered by: " + ", ".join(ds)))


if __name__ == "__main__":
    main()
