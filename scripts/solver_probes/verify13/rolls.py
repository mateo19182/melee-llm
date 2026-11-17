"""Rolls out of shield are locked for their whole length: does a waiting attacker always have a clean punish?"""
import sys; sys.path.insert(0, __file__.rsplit("/", 1)[0])
from lab import *
sim = Sim()
SHINE = (B, 0, -80, 0); USM = (A, 0, 80, 0); JAB = (A, 0, 0, 0)
for ledge in (12, 60):
  for gap in (14, 15, 16, 18, 22):
    root = corner(sim, gap, ledge, shield=12); g = sim.gap()
    for nm, ex in (("roll_in", (R, -80, 0, 255)), ("roll_out", (R, 80, 0, 255))):
        sim.restore(root); end = None; inv = []
        for f in range(45):
            sim.step([N, ex if f == 0 else N]); a, b = sim.players()
            if int(b["invulnerable"]): inv.append(f)
            if end is None and f > 0 and not name(b["action_id"]).startswith("ROLL"): end = f
        x_end = float(b["pos_x"])
        found = []
        for kind, inp in (("usmash", USM), ("shine", SHINE), ("jab", JAB)):
            for d in range(1, end):
                for stick in (0, 80, -80, 30):
                    for stop in (0, 3):
                        def p1(f):
                            if f == 0: return N
                            if f == d: return inp
                            if f < d - stop: return (0, stick, 0, 0)
                            return N
                        d1, d2, hit = run(sim, root, p1, prog({0: ex}), end)
                        if d2 > 0 and d1 == 0: found.append((d2, kind, d, stick, stop, hit))
        found.sort(reverse=True)
        print(f"ledge {ledge} gap {g:.2f} {nm}: free again on frame {end}, intangible {inv[0]}-{inv[-1]}, ends at x={x_end:.1f}; {len(found)} clean punishes before that, best {found[:2]}, earliest input {min((f[2] for f in found), default=None)}", flush=True)
