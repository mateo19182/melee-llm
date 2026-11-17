"""Claim D: transposition key and `forced`, checked against searches without a table and an independent brute force."""
import sys, time; sys.path.insert(0, __file__.rsplit("/", 1)[0])
import numpy as np
from melee_llm.solver import force, nash
from melee_llm.solver.matrix import solve as solve_matrix
from melee_llm.solver.game import Sim

class Null(dict):
    def __setitem__(self, k, v): pass
FIELDS = ("pos_x", "pos_y", "speed_air_x_self", "speed_ground_x_self", "speed_y_self", "speed_x_attack", "speed_y_attack",
          "percent", "shield_hp", "action_id", "action_frame", "hitlag", "hitstun", "stocks", "facing", "on_ground",
          "jumps_left", "hurtbox_state", "invulnerable")
def full(s): return tuple(float(s[f]) for f in FIELDS)  # every observed field, unrounded

sim = Sim()
ROOTS = {"shield12 @12.59": force.corner(sim, 14, 12, shield=12), "standing @12.59": force.corner(sim, 14, 12),
         "hop9": force.corner(sim, 11.5, 12, hop=9), "standing @7.8": force.corner(sim, 9, 12)}
which = sys.argv[1]; frames = int(sys.argv[2])
for name, root in ROOTS.items():
    if which not in name: continue
    out = {}
    for label in sys.argv[3:]:
        s = nash.Nash(root, frames, no_shield="hop" in name, key=full if label == "full" else force._key)
        if label == "none": s.values, s.yes, s.no = Null(), Null(), Null()
        t = time.time(); s.expansions = 0
        att, dfn, m = s.matrix(0, frames)
        out[label] = m
        print(f"{name} {frames}f {label:5s}: value {solve_matrix(m).value:.4f}  {s.expansions:,} steps {time.time()-t:.0f}s", flush=True)
        del s
    labs = list(out)
    for l in labs[1:]:
        diff = np.abs(out[l] - out[labs[0]]).max()
        print(f"   max |{l} - {labs[0]}| over the root matrix {out[l].shape}: {diff:.6f}", flush=True)
