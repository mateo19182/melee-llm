import sys; sys.path.insert(0, __file__.rsplit("/", 1)[0])
from lab import *
sim = Sim()
root = corner(sim, 14, 12, shield=12)
print(st(sim), "gap", sim.gap())
# P2 is on the right: toward P1 is -x for P2; toward P2 is +x for P1
EX = {"release": prog({}), "jump_oos": prog({0: (R | X, 0, 0, 255)}), "roll_in": prog({0: (R, -80, 0, 255)}),
      "roll_out": prog({0: (R, 80, 0, 255)}), "spotdodge": prog({0: (R, 0, -80, 255)}),
      "shield_grab": prog({0: (R | A, 0, 0, 255)})}
SHINE = (B, 0, -80, 0)
for n, ex in EX.items():
    res = []
    for d in range(1, 30):
        for kind, inp in (("shine", SHINE), ("usmash", (A, 0, 80, 0)), ("jab", (A, 0, 0, 0))):
            d1, d2, hit = run(sim, root, prog({d: inp}), ex, 60)
            if d2 > 0 and d1 == 0: res.append((d, kind, d2, hit))
    print(n, "clean punishes (attacker input frame, move, dmg, hit frame):", res[:12])
print("--- trace release vs shine@1")
run(sim, root, prog({1: SHINE}), EX["release"], 6, show=True)
print("--- trace jump_oos vs shine@1")
run(sim, root, prog({1: SHINE}), EX["jump_oos"], 6, show=True)
print("--- trace roll_out vs shine@1")
run(sim, root, prog({1: SHINE}), EX["roll_out"], 6, show=True)
