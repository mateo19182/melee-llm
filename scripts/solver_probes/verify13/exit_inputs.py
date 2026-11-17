import sys; sys.path.insert(0, __file__.rsplit("/", 1)[0])
from lab import *
sim = Sim()
root = corner(sim, 14, 12, shield=12)
SHINE = (B, 0, -80, 0); JAB = (A, 0, 0, 0)
INP = {"N": N, "SH": SH, "X": (X,0,0,0), "R|X": (R|X,0,0,255), "Bdown": SHINE, "Bup": (B,0,80,0), "B": (B,0,0,0), "Bside_in": (B,-80,0,0),
       "A": JAB, "Aup": (A,0,80,0), "Adown": (A,0,-80,0), "Aside": (A,-80,0,0), "Z": (Z,0,0,0), "R+A": (R|A,0,0,255), "R+down": (R,0,-80,255),
       "R+in": (R,-80,0,255), "R+out": (R,80,0,255), "down": (0,0,-80,0), "in": (0,-80,0,0), "out": (0,80,0,0), "up": (0,0,80,0),
       "light": (0,0,0,100), "light+down": (0,0,-80,100), "Rdig_only": (R,0,0,0)}
def after(first, second, p1):
    sim.restore(root); sim.step([N, first]); sim.step([p1, second]); a, b = sim.players()
    return name(b["action_id"]), int(b["action_frame"]), float(b["percent"]), float(a["percent"])
for fname, first in (("release", N), ("jumpsquat", (R|X,0,0,255)), ("hold", SH)):
    print(f"== frame 0: {fname}; frame 1 input -> state at frame 1 | vs shine@1 | vs jab@1(seen at frame 2)")
    seen = {}
    for k, inp in INP.items():
        s0 = after(first, inp, N); s1 = after(first, inp, SHINE)
        sim.restore(root); sim.step([N, first]); sim.step([JAB, inp]); sim.step([N, N]); a, b = sim.players()
        key = (s0[0], s0[1])
        seen.setdefault(key, []).append((k, s1[2], float(b["percent"])))
    for key, v in seen.items():
        print(f"   {key[0]:20s} f{key[1]:2d}: " + ", ".join(f"{k}(shine {int(s)}%, jab {int(j)}%)" for k, s, j in v))
