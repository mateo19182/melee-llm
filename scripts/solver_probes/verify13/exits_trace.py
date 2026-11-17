import sys; sys.path.insert(0, __file__.rsplit("/", 1)[0])
from lab import *
sim = Sim()
root = corner(sim, 14, 12, shield=12)
SHINE = (B, 0, -80, 0)
def tr(sim, root, p1, p2, frames):
    sim.restore(root); out = []
    for f in range(frames):
        sim.step([p1(f), p2(f)]); a, b = sim.players()
        out.append(f"{name(b['action_id'])[:14]}:{int(b['action_frame'])}@{float(b['pos_x']):.1f},{float(b['pos_y']):.1f}/{float(b['percent']):.0f}%/sh{float(b['shield_hp']):.1f}")
    return out
EX = {
 "usmash_oos": prog({0: (R | X, 0, 0, 255), 1: (A, 0, 80, 0)}),
 "usmash_oos_stick": prog({0: (R | A, 0, 80, 255)}),
 "upb_oos": prog({0: (R | X, 0, 0, 255), 1: (B, 0, 80, 0)}),
 "upb_stick": prog({0: (R | B, 0, 80, 255)}),
 "tapjump": prog({0: (R, 0, 80, 255)}),
 "wd_out@2": prog({0: (R | X, 0, 0, 255), 2: (R, 70, -40, 255)}),
 "wd_out@3": prog({0: (R | X, 0, 0, 255), 3: (R, 70, -40, 255)}),
 "wd_in@3": prog({0: (R | X, 0, 0, 255), 3: (R, -70, -40, 255)}),
 "wd_down@3": prog({0: (R | X, 0, 0, 255), 3: (R, 0, -80, 255)}),
 "fullhop": prog({0: (R | X, 0, 0, 255), 1: (X, 0, 0, 0), 2: (X, 0, 0, 0), 3: (X, 0, 0, 0)}),
 "jump_dj@3": prog({0: (R | X, 0, 0, 255), 3: (X, 0, 0, 0)}),
 "jump_dj@4": prog({0: (R | X, 0, 0, 255), 4: (X, 0, 0, 0)}),
 "jump_shine@2": prog({0: (R | X, 0, 0, 255), 2: SHINE}),
 "light": lambda f: (0, 0, 0, 100),
 "light_then_release": prog({0: (0, 0, 0, 100), 1: (0, 0, 0, 100), 2: (0, 0, 0, 100)}),
 "angle_x30": lambda f: (R, 30, 0, 255),
 "angle_x50": lambda f: (R, 50, 0, 255),
 "angle_up": lambda f: (R, 0, 50, 255),
 "angle_down40": lambda f: (R, 0, -40, 255),
 "slow_roll?": prog({0: (R, 40, 0, 255), 1: (R, 80, 0, 255)}, SH),
 "release": prog({}),
 "release_then_shield@1": prog({1: SH, 2: SH, 3: SH, 4: SH}),
 "release_jump@1": prog({1: (X, 0, 0, 0)}),
 "release_shine@1": prog({1: SHINE}),
 "release_spot@1": prog({1: (R, 0, -80, 255)}),
}
for n, ex in EX.items():
    print(f"{n:22s} noP1:", " ".join(tr(sim, root, prog({}), ex, 7)))
    print(f"{'':22s} shine@1:", " ".join(tr(sim, root, prog({1: SHINE}), ex, 5)))
