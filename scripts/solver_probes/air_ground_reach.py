"""P1 jumps next to a standing P2. On each frame of the jump: does P1's air shine hit P2, and does P2's ground shine hit P1?"""
from melee_llm.solver.neutral import Sim, B, X
N = (0, 0, 0, 0); SHINE = (B, 0, -80, 0)
sim = Sim()
for gap, hold in ((7, 1), (7, 6), (9, 6), (11.5, 6), (11.5, 1)):
    root = sim.setup(gap); sim.restore(root)
    a, b = sim.players(); g0 = float(b["pos_x"] - a["pos_x"])
    states = []
    for f in range(60):
        sim.step([(X, 40 if gap > 10 else 0, 0, 0) if f < hold else (0, 40 if gap > 10 else 0, 0, 0), N])
        a, b = sim.players()
        if not int(a["on_ground"]): states.append((f, sim.save(), float(a["pos_y"]), float(b["pos_x"] - a["pos_x"])))
        elif states: break
    out = []
    for f, st, y, dx in states:
        res = []
        for who in (0, 1):
            sim.restore(st); a, b = sim.players(); p = (float(a["percent"]), float(b["percent"]))
            sim.step([SHINE, N] if who == 0 else [N, SHINE])
            for _ in range(6): sim.step([N, N])
            a, b = sim.players(); res.append(float(b["percent"]) > p[1] if who == 0 else float(a["percent"]) > p[0])
        out.append((f, round(y, 1), round(dx, 1), res))
    kind = "short hop" if hold == 1 else "full hop"
    air_only = [(f, y, dx) for f, y, dx, r in out if r[0] and not r[1]]
    ground_only = [(f, y, dx) for f, y, dx, r in out if r[1] and not r[0]]
    both = [f for f, y, dx, r in out if r[0] and r[1]]
    print(f"start gap {g0:.1f} {kind}: airborne frames {out[0][0]}..{out[-1][0]}, peak y {max(o[1] for o in out)}")
    print(f"   both reach on frames {both[:1]}..{both[-1:]} ({len(both)})")
    print(f"   only the AIR Fox reaches (frame, height, dx): {air_only}")
    print(f"   only the GROUND Fox reaches: {ground_only}")
