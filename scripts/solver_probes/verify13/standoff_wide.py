"""Claim B with wide menus: does the defender have a pure defence that holds even when read (value 0)? And the attacker?"""
import sys, time
from melee_llm.solver import force, nash
from melee_llm.solver.game import Sim
WIDE = {"ground": ("usmash", "dsmash", "fsmash", "walk_in", "walk_out", "crouch", "ftilt", "dtilt"), "squat": ("jump",), "air": ("wd_in", "wd_out")}
sim = Sim(); root = force.corner(sim, 14, 12)
for frames in (4, 6, 8):
    for ns in (True,):
        s = nash.Nash(root, frames, no_shield=ns, add1=WIDE, add2=WIDE, tt_mb=1500)
        t = time.time()
        safe = s.forced(0, frames, False); n1 = s.expansions
        print(f"{frames} frames, defender {'never shields' if ns else 'may shield'}: defender has a pure safe defence: {safe}  ({n1:,} steps, {time.time()-t:.0f}s)", flush=True)
        if safe:  # which first moves hold?
            att, dfn = s.menus(); s.rb.checkpoint(0); good = []
            for d in dfn:
                ok = True
                for a in att:
                    s.joint(a, d); v = s.leaf(); ok = s.forced(1, frames - 1, False) if v is None else v == 0.0; s.back(0)
                    if not ok: break
                if ok: good.append(d)
            print("   first moves that hold against everything:", good, flush=True)
        del s
