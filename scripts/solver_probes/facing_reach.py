"""Shine reach by facing: can one Fox hit the other from a gap where the return shine misses?"""
import melee
from melee_llm.solver.neutral import Sim, B
N = (0, 0, 0, 0)
sim = Sim(); w = sim.world
gs = w.reset(0)
while gs.frame < 0 or gs.players[1].action != melee.Action.STANDING: gs = w.step()
start = sim.save()
def shine_hits(state, who):
    sim.restore(state); a, b = sim.players(); p = (float(a["percent"]), float(b["percent"]))
    sim.step([(B, 0, -80, 0), N] if who == 0 else [N, (B, 0, -80, 0)])
    for _ in range(6): sim.step([N, N])
    a, b = sim.players()
    return float(b["percent"]) > p[1] if who == 0 else float(a["percent"]) > p[0]
seen = {}
for turn1 in (False, True):
  for turn2 in (False, True):
    for frames, mag in [(f, m) for m in (24, 27, 30, 34, 38, 43) for f in range(40, 120)]:
        sim.restore(start)
        for _ in range(frames): sim.step([(0, mag, 0, 0), (0, -30, 0, 0)])
        for _ in range(20): sim.step([N, N])
        for _ in range(3): sim.step([(0, -25, 0, 0) if turn1 else N, (0, 25, 0, 0) if turn2 else N])
        for _ in range(30): sim.step([N, N])
        a, b = sim.players(); gap = round(float(b["pos_x"] - a["pos_x"]), 2)
        f = (int(a["facing"]), int(b["facing"]))
        if not (9.5 < gap < 13.5) or (f, gap) in seen: continue
        st = sim.save()
        seen[(f, gap)] = (shine_hits(st, 0), shine_hits(st, 1))
for f in sorted({k[0] for k in seen}):
    rows = sorted((g, v) for (ff, g), v in seen.items() if ff == f)
    lab = {(1, 0): "face to face", (1, 1): "P2 turned away", (0, 0): "P1 turned away", (0, 1): "back to back"}[f]
    p1max = max([g for g, v in rows if v[0]], default=None); p2max = max([g for g, v in rows if v[1]], default=None)
    asym = [g for g, v in rows if v[0] != v[1]]
    both=[g for g,v in rows if v[0] and v[1]]; none=[g for g,v in rows if not v[0] and not v[1]]
    print(f"   both hit up to {max(both,default=None)}, neither from {min(none,default=None)}; P1-only: {[g for g,v in rows if v[0] and not v[1]]}; P2-only: {[g for g,v in rows if v[1] and not v[0]]}")
    print(f"{lab:15s}: P1's shine reaches to {p1max}, P2's to {p2max}; gaps tested {rows[0][0]}..{rows[-1][0]} ({len(rows)}); one-sided gaps: {asym}")
