"""Brute force with Sim.save/restore (no rollback, no table, own recursion) against Nash.forced and Nash.value."""
import sys, time; sys.path.insert(0, __file__.rsplit("/", 1)[0])
import numpy as np
from melee_llm.solver import force, nash
from melee_llm.solver.matrix import solve as solve_matrix
from melee_llm.solver.game import Sim
sim = Sim()
def leaf(base):
    a, b = sim.players()
    d1 = float(a["percent"]) - base[0] + (int(a["action_id"]) in nash._HELD); d2 = float(b["percent"]) - base[1] + (int(b["action_id"]) in nash._HELD)
    return None if d1 == 0 and d2 == 0 else float(d2 > 0 and d1 == 0)
def kids(state, base, no_shield):
    sim.restore(state); s = sim.players()
    att, dfn = nash._menus(s, nash.MENUS, nash.MENUS, no_shield)
    toward = 1 if float(s[1]["pos_x"]) >= float(s[0]["pos_x"]) else -1
    out = np.empty((len(att), len(dfn)), dtype=object)
    for i, a in enumerate(att):
        for j, d in enumerate(dfn):
            sim.restore(state)
            b, x, y, r = nash.MOVES[a]; db, dx, dy, dr = nash.MOVES[d]
            sim.step([(b, x * toward, y, r), (db, -dx * toward, dy, dr)])
            v = leaf(base)
            out[i, j] = (v, sim.save() if v is None else None)
    return out
def forced(state, base, frames, attacking, ns):
    if frames <= 0: return not attacking
    k = kids(state, base, ns); want = 1.0 if attacking else 0.0
    k = k if attacking else k.T
    return any(all((v == want) if v is not None else forced(st, base, frames - 1, attacking, ns) for v, st in row) for row in k)
def value(state, base, frames, ns):
    if frames <= 0: return 0.0
    k = kids(state, base, ns)
    m = np.array([[v if v is not None else value(st, base, frames - 1, ns) for v, st in row] for row in k])
    return float(solve_matrix(m).value)
frames = int(sys.argv[1])
ROOTS = {"shield12 @12.59": (14, 0, 12), "standing @12.59": (14, 0, 0), "hop9": (11.5, 9, 0), "standing @7.8": (9, 0, 0), "hop11": (11.5, 11, 0)}
for name, (gap, hop, sh) in ROOTS.items():
    root = force.corner(sim, gap, 12, hop, sh); a, b = sim.players(); base = (float(a["percent"]), float(b["percent"])); ns = "hop" in name
    s = nash.Nash(root, frames, no_shield=ns)
    att, dfn = s.menus()
    bad = 0; n = 0; t = time.time()
    k = kids(root, base, ns)
    for i, a in enumerate(att):
        for j, d in enumerate(dfn):
            v, st = k[i, j]
            s.rb.checkpoint(0); s.joint(a, d); lv = s.leaf()
            if lv != v: bad += 1; print("  LEAF differs", name, a, d, lv, v)
            if v is None:
                for f in range(1, frames):
                    for attacking in (True, False):
                        got = s.forced(1, f, attacking); want = forced(st, base, f, attacking, ns); n += 1
                        if got != want: bad += 1; print("  FORCED differs", name, a, d, f, attacking, got, want)
                    if f <= 2 and (i * 7 + j) % 5 == 0:
                        got = s.value(1, f); want = value(st, base, f, ns); n += 1
                        if abs(got - want) > 1e-9: bad += 1; print("  VALUE differs", name, a, d, f, got, want)
            s.back(0)
    print(f"{name}: {n} comparisons over {len(att) * len(dfn)} first pairs, horizons 1..{frames - 1}: {bad} disagreements  ({time.time() - t:.0f}s)", flush=True)
    del s
