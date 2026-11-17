"""P1 walks in from the opening, P2 waits: at each of the last frames before the crack of opening_line.py, P2's
inputs that hold for H frames against a P1 who reads them, with the positions marked by the learning games
counted as lost (argument 2: the file of marks). Run with PYTHONPATH=. ; argument 1: H."""
import sys
import time

from melee_llm.solver import force, fortress
from melee_llm.solver.game import Sim

H = int(sys.argv[1]) if len(sys.argv) > 1 else 8
WALK = (0, 30, 0, 0)
sim = Sim()
sim.restore(sim.start())
states = {}
for f in range(183):
    if f >= 150 and (f % 4 == 2 or f >= 176):
        states[f] = sim.save()
    sim.step([WALK, force.N])
sim.world.close()
fz = fortress.Fortress(states[150], 12, add1=fortress.WALK)
if len(sys.argv) > 2:
    fz.learn(sys.argv[2])
for f in sorted(states, reverse=True):
    fz.load(states[f], (WALK, force.N))
    t = time.time()
    print(f"frame {f}: gap {fz.gap():.2f}, safe for {H} frames: {' '.join(fz.safe_moves(H)) or 'NONE'}  ({time.time() - t:.0f}s)", flush=True)
