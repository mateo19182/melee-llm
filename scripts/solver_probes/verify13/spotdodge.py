"""Spotdodge lemma: is a spotdodge next to a Fox always punished at its end? Raw simulator, scripted attacker."""
import sys; sys.path.insert(0, __file__.rsplit("/", 1)[0])
from lab import *
sim = Sim()
SHINE = (B, 0, -80, 0); SPOT = (R, 0, -80, 255); USM = (A, 0, 80, 0); JAB = (A, 0, 0, 0)
# 1. the dodge itself: frames, intangibility, can it be cancelled?
root = corner(sim, 14, 12, shield=12)
sim.restore(root); row = []
for f in range(30):
    sim.step([N, SPOT if f == 0 else N]); a, b = sim.players()
    row.append(f"{f}:{name(b['action_id'])[:5]}{int(b['action_frame'])}/h{int(b['hurtbox_state'])}i{int(b['invulnerable'])}")
print(" ".join(row))
acts = set()
for f in range(1, 24):
    for inp in (SH, (X,0,0,0), (R|X,0,0,255), SHINE, JAB, (R,80,0,255), (0,80,0,0), (Z,0,0,0), SPOT):
        sim.restore(root)
        for g in range(f + 1): sim.step([N, SPOT if g == 0 else (inp if g == f else N)])
        a, b = sim.players(); acts.add((f, name(b["action_id"])))
first_other = min((f for f, n in acts if n != "SPOTDODGE"), default=None)
print("first frame on which an input changes the state:", first_other, sorted(n for f, n in acts if f == first_other))
# 2. punish by an attacker in each state when the dodge starts. P1 line: pre (his frame-0 and frame-1 inputs), then scripted
def best(root, p2, pre, tag, LAST=21):
    """p2: defender program. pre: dict of P1's forced early inputs. Search P1 continuations."""
    found = []
    for kind, inp in (("usmash", USM), ("shine", SHINE), ("jab", JAB), ("grab", (Z,0,0,0))):
        for d in range(2, 26):
            for walk in (0, 30, 80):
                for jc in ((None,) if not any(v == SHINE for v in pre.values()) else (4, 5, 6, 8)):
                    def p1(f):
                        if f in pre: return pre[f]
                        if jc is not None and f == jc: return (X, 0, 0, 0)
                        if f == d: return inp
                        if f < d: return (0, walk, 0, 0)
                        return N
                    d1, d2, hit = run(sim, root, p1, p2, 40)
                    if d2 > 0 and d1 == 0 and hit <= LAST: found.append((d2, kind, d, walk, jc, hit))
    found.sort(reverse=True)
    print(f"   {tag}: {len(found)} clean punishing lines; best {found[:3]}")
    return found
for gap in (8, 9, 10, 11.5, 13, 14, 15, 16, 18):
    for age in (12,):
        root = corner(sim, gap, 12, shield=age); print(f"gap {sim.gap():.2f} shield age {age}")
        dodge = prog({0: SPOT})
        best(root, dodge, {0: N, 1: N}, "P1 standing, waits")
        best(root, dodge, {0: SHINE}, "P1 shines on the dodge's first frame")
        best(root, prog({1: SPOT}), {0: N, 1: SHINE}, "release, then dodge as P1 shines (frame 1)", 22)
        best(root, prog({1: SPOT}), {0: N, 1: JAB}, "release, then dodge as P1 jabs (frame 1)", 22)
        best(root, prog({1: SPOT}), {0: N, 1: USM}, "release, then dodge as P1 up-smashes (frame 1)", 22)
