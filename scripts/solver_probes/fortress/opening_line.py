"""The line from the opening that makes the waiting defender guess: P1 walks in for 182 frames and turns.
Replayed in the raw simulator (game.Sim), then solved with the fortress rules and with nash.py's own rules.
Run with PYTHONPATH=. ; argument: the deepest horizon (default 8)."""
import sys
import time

from melee_llm.solver import force, fortress, nash
from melee_llm.solver.game import Sim

DEEP = int(sys.argv[1]) if len(sys.argv) > 1 else 8
WALK, OUT = (0, 30, 0, 0), (0, -80, 0, 0)
sim = Sim()
start = sim.start()
for f in range(183):
    sim.step([WALK if f < 182 else OUT, force.N])
a, b = sim.players()
print(f"after 182 frames of walking and one of stick away: gap {sim.gap():.2f}, P1 {fortress.name(int(a['action_id']))} "
      f"frame {int(a['action_frame'])}, P2 {fortress.name(int(b['action_id']))}, both at 0%: {float(a['percent']) + float(b['percent']) == 0}")
state, last = sim.save(), (OUT, force.N)
sim.world.close()
fz = fortress.Fortress(state, 12, add1=fortress.WALK, last=last)
print("safe inputs for P2, lookahead 6 and 8:", fz.safe_moves(6), fz.safe_moves(8))
for h in range(6, DEEP + 1, 2):
    t = time.time()
    print(f"fortress rules, {h} frames: value {fz.value(0, h):.4f}  ({time.time() - t:.0f}s)", flush=True)
att, row, dfn, col, v = fz.mix(8)
print("   P1 plays", {m: round(float(p), 3) for m, p in zip(att, row) if p > 1e-6})
print("   P2 plays", {m: round(float(p), 3) for m, p in zip(dfn, col) if p > 1e-6})
plain = nash.Nash(state, 12, dodge=True, add1=fortress.WALK)
plain.last = last
for h in (6, 8):
    print(f"nash.py rules (any shield allowed, no door, --dodge), {h} frames: value {plain.value(0, h):.4f}", flush=True)
