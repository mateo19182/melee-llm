"""Which key is right where they differ? Old key (no inputs), new key, and no table, on the cell that differed."""
import sys, time
from melee_llm.solver import force, nash
from melee_llm.solver.game import Sim
class Null(dict):
    def __setitem__(self, k, v): pass
class Old(nash.Nash):
    def where(self):
        s = self.slots(); return self.key(s[0]) + self.key(s[1])
sim = Sim()
for gap, sh, pair in ((14, 0, ("out", "hop")), (14, 12, ("out", "jump_oos"))):
    root = force.corner(sim, gap, 12, 0, sh)
    for frames in (3, 4, 5, 6):
        row = []
        for label in ("old", "new", "none"):
            if label == "none" and frames > 5: continue
            s = (Old if label == "old" else nash.Nash)(root, frames + 1)
            if label == "none": s.values, s.yes, s.no = Null(), Null(), Null()
            s.rb.checkpoint(0); s.joint(*pair); t = time.time()
            row.append(f"{label} {s.value(1, frames):.4f} ({time.time()-t:.0f}s)")
            del s
        print(gap, sh, pair, frames, "frames after:", "  ".join(row), flush=True)
