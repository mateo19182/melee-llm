"""Game-theoretic optimal play for short Melee exchanges, computed on the real game code (melee-sim-light).

Two players stand facing each other. Every `move_frames` frames both pick one of a few macro-actions at the same
time (wait, dash in, dash away, shine, short hop, shield, grab, jab, laser). The tree runs `depth` such joint picks deep;
an exchange ends early when someone takes damage. Each leaf lets the hit play out (`rollout` frames of nothing)
and scores damage dealt minus damage taken by P1. Backward induction solves the zero-sum matrix game at every node
exactly (`matrix.solve`), so the root gives the value and the equilibrium (often mixed) strategies.

Alongside the equilibrium the same tree scores the plan Dan Petro gave at DEF CON 24 for perfect SmashBot play,
"walk in until in range, then shine": how much a best-responding opponent wins against it, and what it scores
against itself.

    uv run python -m melee_llm.solver.neutral --gaps 8 12 16 20 --depth 2
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

A, B, X, Z, R = 0x0100, 0x0200, 0x0400, 0x0010, 0x0020
ACTIONS = ("wait", "in", "away", "shine", "hop", "shield", "grab", "jab", "laser")
WAIT, IN, SHINE = 0, 1, 3
SHINE_REACH = 11.0  # largest gap (x distance, standing Foxes) at which a standing shine hits; measured by reach()


def _input(action: int, f: int, toward: int) -> tuple[int, int, int, int]:
    """(buttons, main_x, main_y, r) on frame `f` of a macro-action; `toward` is +1 when the opponent is right."""
    name = ACTIONS[action]
    if name == "in":
        return 0, 80 * toward, 0, 0
    if name == "away":
        return 0, -80 * toward, 0, 0
    if name == "shield":
        return R, 0, 0, 255
    if f == 0:
        return {"shine": (B, 0, -80, 0), "hop": (X, 0, 0, 0), "grab": (Z, 0, 0, 0), "jab": (A, 0, 0, 0),
                "laser": (B, 0, 0, 0)}.get(
            name, (0, 0, 0, 0))
    return 0, 0, 0, 0


@dataclass
class Totals:
    nash: float
    petro_worst: float  # P1 plays Petro's plan, P2 best-responds
    petro_mirror: float  # both play Petro's plan


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
    best_vs_petro: str = ""  # P2's best answer to Petro's first move
    notes: list[str] = field(default_factory=list)


class Sim:
    """One raw melee-sim-light match: restore, step with raw inputs, read both players."""

    def __init__(self):
        from melee_llm.sim.world import World
        self.world = World({1: melee.Character.FOX, 2: melee.Character.FOX}, stage=melee.Stage.FINAL_DESTINATION)
        self.env = self.world.env

    def players(self):
        s = self.env.current_frame[0]["slots"]
        return s[0], s[1]

    def step(self, inputs) -> None:
        env = self.env
        if env.t >= env.length:
            env.reset_cursor()
        row = env.raw_action_view[env.t, 0]["players"]
        for i, (b, mx, my, r) in enumerate(inputs):
            row[i]["buttons"], row[i]["main_x"], row[i]["main_y"] = b, mx, my
            row[i]["c_x"], row[i]["c_y"], row[i]["l"], row[i]["r"] = 0, 0, 0, r
        env.step()

    def save(self) -> bytes:
        return self.env.save(0)

    def restore(self, state: bytes) -> None:
        self.env.restore(0, state)
        self.env.reset_cursor()  # observe() writes at the cursor, which may sit at the ring's end
        self.env.observe()

    def setup(self, gap: float) -> bytes:
        """Both Foxes walk in from their spawns at the same speed and come to a stop, standing, about `gap` apart
        (the closest reachable gap at or above it: walking stops in steps of about 1.2)."""
        w = self.world
        gs = w.reset(0)
        while gs.frame < 0 or gs.players[1].action != melee.Action.STANDING:
            gs = w.step()
        start = self.save()
        for frames in range(400, -1, -1):  # walk less and less until the gap after stopping reaches `gap`
            self.restore(start)
            for _ in range(frames):
                self.step([(0, 30, 0, 0), (0, -30, 0, 0)])
            for _ in range(30):
                self.step([(0, 0, 0, 0), (0, 0, 0, 0)])
            a, b = self.players()
            if b["pos_x"] - a["pos_x"] >= gap:
                return self.save()
        return start


def _key(p, q) -> tuple:
    def one(s):
        return (round(float(s["pos_x"]), 3), round(float(s["pos_y"]), 3), round(float(s["speed_ground_x_self"]), 3),
                round(float(s["speed_air_x_self"]), 3), round(float(s["speed_y_self"]), 3), int(s["action_id"]),
                int(s["action_frame"]), round(float(s["percent"]), 2), int(s["hitlag"]), int(s["hitstun"]),
                round(float(s["shield_hp"]), 2), int(s["facing"]), int(s["jumps_left"]))
    return one(p) + one(q)


class Solver:
    def __init__(self, sim: Sim, depth: int, move_frames: int, rollout: int):
        self.sim, self.depth, self.k, self.rollout = sim, depth, move_frames, rollout
        self.cache: dict[tuple, tuple[Totals, int]] = {}
        self.nodes = 0

    def _score(self, base) -> float:
        a, b = self.sim.players()
        return float((b["percent"] - base[1]) - (a["percent"] - base[0]) + 100 * (
            (int(a["stocks"]) - base[2]) - (int(b["stocks"]) - base[3])))

    def _base(self):
        a, b = self.sim.players()
        return float(a["percent"]), float(b["percent"]), int(a["stocks"]), int(b["stocks"])

    def petro(self) -> tuple[int, int]:
        """Each player's move under "walk in until in range, then shine"."""
        a, b = self.sim.players()
        close = abs(float(b["pos_x"]) - float(a["pos_x"])) <= SHINE_REACH
        return (SHINE, SHINE) if close else (IN, IN)

    def play(self, i: int, j: int) -> bool:
        """Play joint macro (i, j) from the current state; True if someone was hit (the exchange is decided)."""
        a, b = self.sim.players()
        toward = 1 if b["pos_x"] >= a["pos_x"] else -1
        hit = False
        p0 = (float(a["percent"]), float(b["percent"]))
        for f in range(self.k):
            self.sim.step([_input(i, f, toward), _input(j, f, -toward)])
            a, b = self.sim.players()
            hit = hit or (float(a["percent"]), float(b["percent"])) != p0 or int(a["stocks"]) + int(b["stocks"]) == 0
        return hit

    def finish(self, base) -> float:
        for _ in range(self.rollout):
            self.sim.step([(0, 0, 0, 0), (0, 0, 0, 0)])
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
        pi, pj = self.petro()
        n = len(ACTIONS)
        nash, worst, mirror = np.zeros((n, n)), np.zeros((n, n)), np.zeros((n, n))
        for i in range(n):
            for j in range(n):
                t = self.child(state, i, j, depth, base)
                nash[i, j], worst[i, j], mirror[i, j] = t.nash, t.petro_worst, t.petro_mirror
        self.nodes += 1
        out = Totals(matrix.solve(nash).value, float(worst[pi].min()), float(mirror[pi, pj]))
        self.cache[key] = (out, self.nodes)
        return out


_SIM: Sim | None = None


def _init() -> None:
    global _SIM
    _SIM = Sim()


def _subtree(args) -> tuple[int, int, Totals, int, tuple[int, int]]:
    """One root joint action, solved below it in a worker process."""
    state, i, j, depth, k, rollout, base = args
    solver = Solver(_SIM, depth, k, rollout)
    t = solver.child(state, i, j, depth, base)
    _SIM.restore(state)
    return i, j, t, solver.nodes, solver.petro()


def solve_root(gap: float, depth: int = 2, move_frames: int = 3, rollout: int = 25, workers: int = 8) -> Root:
    t0 = time.time()
    sim = Sim()
    state = sim.setup(gap)
    a, b = sim.players()
    real_gap = float(b["pos_x"] - a["pos_x"])
    root = Solver(sim, depth, move_frames, rollout)
    base, (pi, pj) = root._base(), root.petro()
    n = len(ACTIONS)
    jobs = [(state, i, j, depth, move_frames, rollout, base) for i in range(n) for j in range(n)]
    nash, worst, mirror = np.zeros((n, n)), np.zeros((n, n)), np.zeros((n, n))
    nodes = 1
    with mp.get_context("spawn").Pool(workers, initializer=_init) as pool:
        for i, j, t, k, _ in pool.imap_unordered(_subtree, jobs):
            nash[i, j], worst[i, j], mirror[i, j] = t.nash, t.petro_worst, t.petro_mirror
            nodes += k
    sim.world.close()
    sol = matrix.solve(nash)
    mix = lambda v: {ACTIONS[k]: round(float(p), 4) for k, p in enumerate(v) if p > 1e-4}
    return Root(gap=round(real_gap, 2), depth=depth, move_frames=move_frames, rollout=rollout,
                totals=Totals(round(float(sol.value), 3), float(worst[pi].min()), float(mirror[pi, pj])),
                p1=mix(sol.row), p2=mix(sol.col), matrix=nash.round(2).tolist(), nodes=nodes,
                seconds=round(time.time() - t0, 1), best_vs_petro=ACTIONS[int(np.argmin(worst[pi]))])


def reach(gaps=np.arange(6.0, 20.0, 0.5)) -> list[tuple[float, bool]]:
    """Does a standing shine hit a standing opponent at each gap? Calibrates SHINE_REACH."""
    sim, out = Sim(), []
    for g in gaps:
        sim.restore(sim.setup(float(g)))
        a, b = sim.players()
        gap, p = float(b["pos_x"] - a["pos_x"]), float(b["percent"])
        sim.step([(B, 0, -80, 0), (0, 0, 0, 0)])
        for _ in range(5):
            sim.step([(0, 0, 0, 0), (0, 0, 0, 0)])
        out.append((round(gap, 2), float(sim.players()[1]["percent"]) > p))
    sim.world.close()
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--gaps", type=float, nargs="+", default=[10, 14, 20, 30])
    ap.add_argument("--depth", type=int, default=2)
    ap.add_argument("--move-frames", type=int, default=3)
    ap.add_argument("--rollout", type=int, default=25)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--reach", action="store_true", help="only measure the shine's reach")
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()
    if args.reach:
        for gap, hit in reach():
            print(f"gap {gap:6.2f}  {'hit' if hit else '-'}")
        return
    results = []
    for g in args.gaps:
        r = solve_root(g, args.depth, args.move_frames, args.rollout, args.workers)
        results.append(asdict(r))
        print(f"gap {r.gap:6.2f}  value {r.totals.nash:+.2f}  P1 {r.p1}  P2 {r.p2}  "
              f"Petro worst {r.totals.petro_worst:+.1f} (answer: {r.best_vs_petro})  "
              f"Petro mirror {r.totals.petro_mirror:+.1f}  [{r.nodes} nodes, {r.seconds}s]", flush=True)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(results, indent=1))


if __name__ == "__main__":
    main()
