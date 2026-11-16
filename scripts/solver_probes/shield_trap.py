"""Is holding shield next to an actionable Fox a trap? P2 shields; P1 stands in shine range and reacts one frame late."""
import sys
from melee_llm.solver.game import Sim, A, B, X, Z, R
N = (0, 0, 0, 0); SH = (R, 0, 0, 255)
sim = Sim()
gap = float(sys.argv[1]) if len(sys.argv) > 1 else 9
root = sim.setup(gap)
sim.restore(root)
for _ in range(20): sim.step([N, SH])
S = sim.save(); a, b = sim.players()
print(f"gap {b['pos_x']-a['pos_x']:.2f}  P2 action {int(b['action_id'])} shield {float(b['shield_hp']):.1f}")

# P2 exits: frame -> input (toward P1 is -x for P2)
def prog(d, default=N): return lambda f: d.get(f, default)
EXITS = {
 "hold shield":   lambda f: SH,
 "drop shield":   lambda f: N,
 "jump":          prog({0: (X, 0, 0, 0)}),
 "jump>shine f3": prog({0: (X, 0, 0, 0), 3: (B, 0, -80, 0)}),
 "jump>shine f4": prog({0: (X, 0, 0, 0), 4: (B, 0, -80, 0)}),
 "jump>nair":     prog({0: (X, 0, 0, 0), 3: (A, 0, 0, 0), 4: (A, 0, 0, 0)}),
 "wavedash back": prog({0: (X, 0, 0, 0), 3: (R, 70, -40, 255), 4: (R, 70, -40, 255)}),
 "roll away":     prog({0: (R, 80, 0, 255)}, SH),
 "roll in":       prog({0: (R, -80, 0, 255)}, SH),
 "spotdodge":     prog({0: (R, 0, -80, 255)}, SH),
 "shield grab":   prog({0: (R | A, 0, 0, 255)}),
 "usmash OoS":    prog({0: (X, 0, 0, 0), 1: (A, 0, 80, 0)}),
}
def chase(stand):
    a, b = sim.players(); dx = float(b["pos_x"] - a["pos_x"])
    if stand or abs(dx) <= 9: return N
    return (0, 80 if dx > 0 else -80, 0, 0)
def run(exit_, kind, d, stand):
    sim.restore(S); a, b = sim.players(); base = (float(a["percent"]), float(b["percent"]))
    for f in range(90):
        if f < 1: p1 = N
        elif f == d: p1 = {"shine": (B, 0, -80, 0), "grab": (Z, 0, 0, 0), "jab": (A, 0, 0, 0), "usmash": (A, 0, 80, 0), "none": N}[kind]
        elif f < d: p1 = chase(stand)
        else: p1 = N
        sim.step([p1, exit_(f)])
    a, b = sim.players()
    return (float(b["percent"]) - base[1]) - (float(a["percent"]) - base[0]), int(b["stocks"])
for name, ex in EXITS.items():
    best = (-999, None)
    for kind in ("none", "shine", "grab", "jab", "usmash"):
        for d in ([0] if kind == "none" else range(1, 45)):
            for stand in (True, False):
                v, _ = run(ex, kind, d, stand)
                if v > best[0]: best = (v, f"{kind}@{d}{'' if stand else ' chasing'}")
    print(f"P2 {name:14s} -> P1 best reaction {best[1]:18s} nets {best[0]:+.0f}%")

print("\n-- one P1 reaction against every exit that looks the same on its first frame (jump family)")
fam = ["jump", "jump>shine f3", "jump>shine f4", "jump>nair", "wavedash back", "usmash OoS"]
rows = []
for kind in ("shine", "grab", "jab", "usmash"):
    for d in range(1, 12):
        vals = [run(EXITS[n], kind, d, True)[0] for n in fam]
        rows.append((min(vals), f"{kind}@{d}", vals))
rows.sort(reverse=True)
for r in rows[:4]: print("  ", r[1], "worst case", r[0], r[2])

print("\n-- how long can P2 hold shield untouched?")
sim.restore(S)
for f in range(1, 900):
    sim.step([N, SH]); a, b = sim.players()
    if f % 60 == 0 or int(b["action_id"]) not in (178, 179):
        print(f"   frame {f}: shield {float(b['shield_hp']):.1f} action {int(b['action_id'])}")
        if int(b["action_id"]) not in (178, 179): break

print("\n-- P1 multishines the shield (shine every 8 frames, jump-cancelled); P2 just holds")
sim.restore(S); a, b = sim.players(); base = (float(a["percent"]), float(b["percent"]))
for f in range(600):
    p1 = (B, 0, -80, 0) if f % 8 == 0 else ((X, 0, 0, 0) if f % 8 == 4 else N)
    sim.step([p1, SH]); a, b = sim.players()
    if f % 40 == 0 or float(b["percent"]) != base[1] or int(b["action_id"]) not in (178, 179, 181):
        print(f"   frame {f}: shield {float(b['shield_hp']):.1f} P2 action {int(b['action_id'])} P2 {float(b['percent']):.0f}% P1 action {int(a['action_id'])}")
        if float(b["percent"]) != base[1] or int(b["action_id"]) not in (178, 179, 181): break

print("\n-- P1 grabs the shield; P2 reacts one frame later")
for name, ex in EXITS.items():
    sim.restore(S); a, b = sim.players(); base = (float(a["percent"]), float(b["percent"]))
    for f in range(120):
        sim.step([(Z, 0, 0, 0) if f == 0 else ((A, 0, 0, 0) if f % 12 == 11 else N), SH if f < 1 else ex(f - 1)])
    a, b = sim.players()
    print(f"   P2 {name:14s}: P1 nets {(float(b['percent'])-base[1])-(float(a['percent'])-base[0]):+.0f}%")
