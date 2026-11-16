"""Game-theoretic optimal play for short Melee exchanges, computed on the real game code (melee-sim-light).

P1 (any character) faces Fox on Final Destination, standing `gap` apart. Every `move_frames` frames both pick one
move from their menus (names from `solver.game.MOVES`) at the same time. The tree runs `depth` such joint picks deep;
an exchange ends early when someone takes damage. Each leaf lets what was started play out for `rollout` frames,
with both fighters idle (or shielding, `--leaf shield`), and scores damage dealt minus damage taken by P1. Backward
induction solves the zero-sum matrix game at every node exactly (`matrix.solve`), so the root gives the value and the
equilibrium (often mixed) strategies. Clanks and hitlag come from the game itself: two grounded shines on the same
frame clank (both lose 4 frames), they don't whiff.

Alongside the equilibrium the same tree scores the plan Dan Petro gave at DEF CON 24 for perfect SmashBot play,
"walk in until in range, then shine", played by Fox: how much a best-responding P1 wins against it, and what it
scores against itself in the ditto. docs/optimal-play.md has the results.

    uv run python -m melee_llm.solver.neutral --gaps 8 12 16 20 --depth 2
    uv run python -m melee_llm.solver.neutral --char MARTH --moves wait in away shield jab ftilt fsmash --gaps 20
"""
from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import melee
import numpy as np

from melee_llm.solver import matrix
from melee_llm.solver.game import Sim, move

FOX_MOVES = ("wait", "in", "away", "shine", "hop", "shield", "grab", "jab", "laser")
SHINE_REACH = 11.0  # largest gap (x distance, standing Foxes) at which a standing shine hits; measured by reach()


@dataclass
class Totals:
    nash: float
    petro_worst: float  # Fox (P2) plays Petro's plan, P1 best-responds: P1's gain, so > 0 means the plan loses
    petro_mirror: float  # both play Petro's plan (P1 without a shine waits instead)


@dataclass
class Root:
    gap: float
    depth: int
    move_frames: int
    rollout: int
    totals: Totals
    p1: dict[str, float]
    p2: dict[str, float]
    matrix: list[list[float]]
    nodes: int
    seconds: float
    p1_char: str = "FOX"
    best_vs_petro: str = ""  # P1's best answer to Fox's first Petro move
    notes: list[str] = field(default_factory=list)


def _key(p, q) -> tuple:
    def one(s):
        return (round(float(s["pos_x"]), 3), round(float(s["pos_y"]), 3), round(float(s["speed_ground_x_self"]), 3),
                round(float(s["speed_air_x_self"]), 3), round(float(s["speed_y_self"]), 3), int(s["action_id"]),
                int(s["action_frame"]), round(float(s["percent"]), 2), int(s["hitlag"]), int(s["hitstun"]),
                round(float(s["shield_hp"]), 2), int(s["facing"]), int(s["jumps_left"]))
    return one(p) + one(q)


class Solver:
    def __init__(self, sim: Sim, depth: int, move_frames: int, rollout: int, moves1=FOX_MOVES, moves2=FOX_MOVES,
                 leaf: str = "wait"):
        self.sim, self.depth, self.k, self.rollout = sim, depth, move_frames, rollout
        self.leaf = move(leaf)
        self.moves = (tuple(moves1), tuple(moves2))
        self.fns = tuple(tuple(move(m) for m in ms) for ms in self.moves)
        self.cache: dict[tuple, tuple[Totals, int]] = {}
        self.nodes = 0

    def _score(self, base) -> float:
        a, b = self.sim.players()
        return float((b["percent"] - base[1]) - (a["percent"] - base[0]) + 100 * (
            (int(a["stocks"]) - base[2]) - (int(b["stocks"]) - base[3])))

    def _base(self):
        a, b = self.sim.players()
        return float(a["percent"]), float(b["percent"]), int(a["stocks"]), int(b["stocks"])

    def petro(self, side: int = 1) -> int:
        """A player's move under "walk in until in range, then shine" (wait, for a menu without a shine)."""
        if "shine" not in self.moves[side]:
            return self.moves[side].index("wait")
        a, b = self.sim.players()
        close = abs(float(b["pos_x"]) - float(a["pos_x"])) <= SHINE_REACH
        return self.moves[side].index("shine" if close else "in")

    def play(self, i: int, j: int) -> bool:
        """Play joint macro (i, j) from the current state; True if someone was hit (the exchange is decided)."""
        a, b = self.sim.players()
        toward = 1 if b["pos_x"] >= a["pos_x"] else -1
        hit = False
        p0 = (float(a["percent"]), float(b["percent"]))
        f1, f2 = self.fns[0][i], self.fns[1][j]
        for f in range(self.k):
            self.sim.step([f1(f, toward, a), f2(f, -toward, b)])
            a, b = self.sim.players()
            hit = hit or (float(a["percent"]), float(b["percent"])) != p0 or int(a["stocks"]) + int(b["stocks"]) == 0
        return hit

    def finish(self, base) -> float:
        """Both play the leaf move (idle by default, or e.g. shield) while whatever was started plays out."""
        for f in range(self.rollout):
            a, b = self.sim.players()
            toward = 1 if b["pos_x"] >= a["pos_x"] else -1
            self.sim.step([self.leaf(f, toward, a), self.leaf(f, -toward, b)])
        return self._score(base)

    def child(self, state: bytes, i: int, j: int, depth: int, base) -> Totals:
        self.sim.restore(state)
        hit = self.play(i, j)
        if hit or depth == 1:
            v = self.finish(base)
            return Totals(v, v, v)
        return self.node(self.sim.save(), depth - 1, base)

    def node(self, state: bytes, depth: int, base) -> Totals:
        key = _key(*self.sim.players()) + (depth,)
        if key in self.cache:
            return self.cache[key][0]
        pj = self.petro()
        n, m = len(self.moves[0]), len(self.moves[1])
        nash, worst, mirror = np.zeros((n, m)), np.zeros((n, m)), np.zeros((n, m))
        for i in range(n):
            for j in range(m):
                t = self.child(state, i, j, depth, base)
                nash[i, j], worst[i, j], mirror[i, j] = t.nash, t.petro_worst, t.petro_mirror
        self.nodes += 1
        out = Totals(matrix.solve(nash).value, float(worst[:, pj].max()), float(mirror[self.petro(0), pj]))
        self.cache[key] = (out, self.nodes)
        return out


_SIM: Sim | None = None


def _init(p1: melee.Character) -> None:
    global _SIM
    _SIM = Sim(p1, melee.Character.FOX)


def _subtree(args) -> tuple[int, int, Totals, int]:
    """One root joint action, solved below it in a worker process."""
    state, i, j, depth, k, rollout, base, moves1, moves2, leaf = args
    solver = Solver(_SIM, depth, k, rollout, moves1, moves2, leaf)
    t = solver.child(state, i, j, depth, base)
    return i, j, t, solver.nodes


def solve_root(gap: float, depth: int = 2, move_frames: int = 3, rollout: int = 25, workers: int = 8,
               p1: melee.Character = melee.Character.FOX, moves1=FOX_MOVES, moves2=FOX_MOVES,
               leaf: str = "wait") -> Root:
    """P1 (`p1`, menu `moves1`) against Fox (menu `moves2`), standing `gap` apart."""
    t0 = time.time()
    sim = Sim(p1, melee.Character.FOX)
    state = sim.setup(gap)
    real_gap = sim.gap()
    root = Solver(sim, depth, move_frames, rollout, moves1, moves2, leaf)
    base, pi, pj = root._base(), root.petro(0), root.petro(1)
    n, m = len(moves1), len(moves2)
    jobs = [(state, i, j, depth, move_frames, rollout, base, moves1, moves2, leaf) for i in range(n) for j in range(m)]
    nash, worst, mirror = np.zeros((n, m)), np.zeros((n, m)), np.zeros((n, m))
    nodes = 1
    with mp.get_context("spawn").Pool(workers, initializer=_init, initargs=(p1,)) as pool:
        for i, j, t, k in pool.imap_unordered(_subtree, jobs):
            nash[i, j], worst[i, j], mirror[i, j] = t.nash, t.petro_worst, t.petro_mirror
            nodes += k
    sim.world.close()
    sol = matrix.solve(nash)
    mix = lambda names, v: {names[k]: round(float(p), 4) for k, p in enumerate(v) if p > 1e-4}
    return Root(gap=round(real_gap, 2), depth=depth, move_frames=move_frames, rollout=rollout,
                totals=Totals(round(float(sol.value), 3), float(worst[:, pj].max()), float(mirror[pi, pj])),
                p1=mix(moves1, sol.row), p2=mix(moves2, sol.col), matrix=nash.round(2).tolist(), nodes=nodes,
                seconds=round(time.time() - t0, 1), p1_char=p1.name, best_vs_petro=moves1[int(np.argmax(worst[:, pj]))])


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--gaps", type=float, nargs="+", default=[10, 14, 20, 30])
    ap.add_argument("--depth", type=int, default=2)
    ap.add_argument("--move-frames", type=int, default=3)
    ap.add_argument("--rollout", type=int, default=25)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--char", default="FOX", help="P1's character; P2 is always Fox")
    ap.add_argument("--moves", nargs="+", help="P1's menu (names from solver.game.MOVES); default Fox's")
    ap.add_argument("--fox-moves", nargs="+", default=list(FOX_MOVES))
    ap.add_argument("--leaf", default="wait", help="what both do while a leaf plays out: wait (default) or shield")
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()
    p1 = melee.Character[args.char.upper()]
    moves1 = tuple(args.moves or FOX_MOVES)
    results = []
    for g in args.gaps:
        r = solve_root(g, args.depth, args.move_frames, args.rollout, args.workers, p1, moves1, tuple(args.fox_moves),
                       args.leaf)
        results.append(asdict(r))
        print(f"{r.p1_char} gap {r.gap:6.2f}  value {r.totals.nash:+.2f}  P1 {r.p1}  P2 {r.p2}  "
              f"vs Fox's Petro plan {r.totals.petro_worst:+.1f} (answer: {r.best_vs_petro})  "
              f"Petro mirror {r.totals.petro_mirror:+.1f}  [{r.nodes} nodes, {r.seconds}s]", flush=True)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(results, indent=1))


if __name__ == "__main__":
    main()
