"""The bound behind `Fortress.far`: how far away can P1 be one frame before he hits a standing P2 who only waits,
and how fast does he move? Every line of P1's menus (plus walking and the full hop) to `DEPTH` frames, from
standing, dashing, running and hopping starts. Run with PYTHONPATH=.

Prints the largest gap one frame before a hit (REACH), per frames-before-hit the largest gap, and the largest
horizontal step in a frame (SPEED)."""
import sys

from melee_llm.solver import force, fortress, nash

DEPTH = int(sys.argv[1]) if len(sys.argv) > 1 else 9
sim = force.Sim()
roots = []
for gap, pre in ((14, []), (18, []), (24, ["in"] * 4), (30, ["in"] * 4), (40, ["in"] * 12), (50, ["in"] * 16),
                 (26, ["hop"] + ["in"] * 4), (30, ["hop"] + ["in"] * 10), (36, ["in"] * 6 + ["hop"] + ["in"] * 3),
                 (30, ["hop", "jump", "jump"] + ["in"] * 12), (24, ["shield", "roll_in"])):
    force.corner(sim, gap, 60)
    for m in pre:
        b, x, y, r = nash.MOVES[m]
        sim.step([(b, x, y, r), force.N])
    roots.append((gap, pre, sim.save()))
sim.world.close()
fz = fortress.Fortress(roots[0][2], DEPTH, reach=False, add1=dict(fortress.WALK, **fortress.FULL))
before = [0.0] * (DEPTH + 1)  # before[k]: largest gap k frames before a hit
speed = 0.0
seen = set()


def dfs(depth, gaps):
    global speed
    key = hash(fz.where())
    if key in seen:
        return
    seen.add(key)
    x0 = float(fz.slots()[0]["pos_x"])
    fz.rb.checkpoint(depth)
    for a in fz.menus()[0]:
        fz.joint(a, "wait")
        d1, d2 = fz.damage()
        if not d1:
            speed = max(speed, abs(float(fz.slots()[0]["pos_x"]) - x0))
        if d2:
            for k in range(1, len(gaps) + 1):
                before[k] = max(before[k], gaps[-k])
        elif not d1 and depth + 1 < DEPTH:
            dfs(depth + 1, gaps + [fz.gap()])
        fz.back(depth)


for gap, pre, root in roots:
    fz.load(root)
    seen.clear()
    dfs(0, [fz.gap()])
    print(f"from {gap} after {len(pre)} frames of {pre[:1]}: reach {before[1]:.2f}, speed {speed:.2f}, "
          f"by frames before the hit {[round(b, 1) for b in before[1:]]}", flush=True)
