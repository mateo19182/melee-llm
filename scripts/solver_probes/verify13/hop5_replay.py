"""hop-5 claim: the attacker's forced strategy (from Nash.forced) played in the raw simulator against scripted
and random defenders, with options outside the default menu."""
import sys, time; sys.path.insert(0, __file__.rsplit("/", 1)[0])
import numpy as np
from lab import *
from melee_llm.solver import force, nash
FR = int(sys.argv[1]) if len(sys.argv) > 1 else 10
EXTRA = {"ground": ("usmash", "dsmash", "crouch", "walk_out", "walk_in")}
sim = Sim()
root = corner(sim, 11.5, 12, hop=5)
print(st(sim), "gap %.2f" % sim.gap(), flush=True)

def strat(s, depth, frames):
    att, dfn = s.menus()
    s.rb.checkpoint(depth)
    for a in (["shine"] if depth == 0 else []) + list(att):
        ok = True
        for d in dfn:
            s.joint(a, d); v = s.leaf()
            ok = s.forced(depth + 1, frames - 1, True) if v is None else v == 1.0
            s.back(depth)
            if not ok: break
        if ok: return a
    return None

def playout(s, policy, tag):
    """policy(depth, dfn) -> defender move. Returns a line of text."""
    sim.restore(root); base = [float(p["percent"]) for p in sim.players()]; seq = []; lost = False
    for depth in range(FR + 12):
        a = strat(s, depth, FR - depth) if depth < FR else None
        if a is None: lost = lost or depth; a = "wait"
        att, dfn = s.menus(); d = policy(depth, dfn)
        s.rb.checkpoint(depth); s.joint(a, d); sim.step(list(s.last)); seq.append(f"{a}/{d}")
        if s.leaf() is not None: break
        if depth >= s.max_depth - 3: break
    v = s.leaf(); p = sim.players(); raw = (float(p[0]["percent"]) - base[0], float(p[1]["percent"]) - base[1])
    s.back(0)
    return f"{tag:26s} solver {v}  raw P1 +{raw[0]:.0f}% P2 +{raw[1]:.0f}%  {'(no forced move from frame %d)' % lost if lost else ''} {' '.join(seq)}"

s = nash.Nash(root, FR + 14, no_shield=True, add2=EXTRA)
t = time.time(); print("forced from the root (extras in P2's menu):", s.forced(0, FR, True), f"{s.expansions:,} steps {time.time()-t:.0f}s", flush=True)
att, dfn = s.menus(); print("defender menu:", dfn)
for d0 in dfn:
    for cont in ("wait", "same"):
        pol = lambda depth, menu, d0=d0, cont=cont: d0 if depth == 0 and d0 in menu else (d0 if cont == "same" and d0 in menu else menu[0])
        print(playout(s, pol, f"{d0} then {cont}"), flush=True)
for name_, first in (("hop away, double jump", ["hop", "out", "out", "out", "jump", "out", "out", "out", "out", "out"]),
                     ("full hop away", ["hop", "out", "out", "out", "out", "out", "out", "out", "out", "out"]),
                     ("hop, shine out of squat", ["hop", "wait", "shine", "jump", "out", "out", "out", "out"]),
                     ("dash under and through", ["in"] * 12), ("dash away", ["out"] * 12),
                     ("turn, then up smash", ["walk_out", "usmash"]), ("crouch", ["crouch"] * 12)):
    pol = lambda depth, menu, first=first: first[depth] if depth < len(first) and first[depth] in menu else menu[0]
    print(playout(s, pol, name_), flush=True)
rng = np.random.default_rng(1); wins = 0; N_R = 300
for i in range(N_R):
    line = playout(s, lambda depth, menu: menu[rng.integers(len(menu))], "random")
    wins += "solver 1.0  raw P1 +0% P2 +" in line and "P2 +0%" not in line
    if "solver 1.0" not in line or "P1 +0%" not in line: print("  FAIL", line, flush=True)
print(f"random adaptive defenders: attacker landed the clean first hit in the raw simulator in {wins} of {N_R}", flush=True)
del s
# rolls and a spotdodge need the shield button: allowed here for the defender's scripted line only
s = nash.Nash(root, FR + 14, add2=EXTRA)
for name_, first in (("shield, roll away", ["shield", "roll_out"]), ("shield, roll in", ["shield", "roll_in"]), ("shield, spotdodge", ["shield", "spotdodge"]),
                     ("shield 1 frame, release", ["shield", "release"]), ("hold shield", ["shield"] * 30)):
    pol = lambda depth, menu, first=first: first[depth] if depth < len(first) and first[depth] in menu else menu[0]
    print(playout(s, pol, name_), flush=True)
