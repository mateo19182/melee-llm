"""Claim C: the four pure cells of the hop-9 coin flip. Solver line for each, then the same inputs in the raw simulator."""
import sys; sys.path.insert(0, __file__.rsplit("/", 1)[0])
import numpy as np
from lab import *
from melee_llm.solver import force, nash
from melee_llm.solver.matrix import solve as solve_matrix
FR = int(sys.argv[1]) if len(sys.argv) > 1 else 7
sim = Sim()
root = corner(sim, 11.5, 12, hop=9)
s = nash.Nash(root, FR, no_shield=True)
att, dfn, m = s.matrix(0, FR)
print("root value", solve_matrix(m).value, solve_matrix(m).row.round(2), solve_matrix(m).col.round(2))
print("        " + "".join(f"{d[:8]:>9s}" for d in dfn))
for a, row in zip(att, m): print(f"{a:8s}" + "".join(f"{v:9.2f}" for v in row))
def line(depth, frames):
    v = s.leaf()
    if v is not None or frames <= 0: return [], v
    att, dfn, m = s.matrix(depth, frames); sol = solve_matrix(m)
    a, d = att[int(np.argmax(sol.row))], dfn[int(np.argmax(sol.col))]
    mixed = sol.row.max() < 0.999 or sol.col.max() < 0.999
    s.rb.checkpoint(depth); s.joint(a, d)
    rest, v = line(depth + 1, frames - 1)
    return [(a, d, "mixed" if mixed else "")] + rest, v
for a in ("wait", "shine"):
    for d in ("out", "shine", "spotdodge"):
        s.rb.checkpoint(0); s.joint(a, d)
        rest, v = line(1, FR - 1); s.back(0)
        seq = [(a, d, "")] + rest
        # the same inputs in the raw simulator (P1 left of P2 throughout? toward recomputed each frame)
        sim.restore(root); log = []
        for x, y, _ in seq:
            p = sim.players(); t = 1 if float(p[1]["pos_x"]) >= float(p[0]["pos_x"]) else -1
            (b, mx, my, r), (db, dx, dy, dr) = nash.MOVES[x], nash.MOVES[y]
            sim.step([(b, mx * t, my, r), (db, -dx * t, dy, dr)])
        p = sim.players()
        print(f"cell ({a}, {d}) = {m[att.index(a), dfn.index(d)]:.2f}: line {' '.join(f'{x}/{y}{chr(42) if z else str()}' for x, y, z in seq)} -> solver leaf {v}; raw: P1 {float(p[0]['percent']):.0f}% P2 {float(p[1]['percent']):.0f}% ({name(p[0]['action_id'])}, {name(p[1]['action_id'])})", flush=True)
