"""Raw-simulator lab: only game.Sim (env.step with raw rows), no Search/Nash."""
import melee
from melee_llm.solver.game import Sim, A, B, X, Z, R
from melee_llm.solver.force import corner
N = (0, 0, 0, 0); SH = (R, 0, 0, 255)
def name(a):
    try: return melee.Action(int(a)).name
    except ValueError: return str(int(a))
def st(sim):
    a, b = sim.players()
    return (f"P1 {name(a['action_id']):18s}f{int(a['action_frame']):3d} x{float(a['pos_x']):7.2f} y{float(a['pos_y']):5.1f} {float(a['percent']):4.0f}% | "
            f"P2 {name(b['action_id']):18s}f{int(b['action_frame']):3d} x{float(b['pos_x']):7.2f} y{float(b['pos_y']):5.1f} {float(b['percent']):4.0f}% sh{float(b['shield_hp']):5.1f}")
def run(sim, root, p1, p2, frames, show=False):
    """p1, p2: f -> 4-tuple with x in absolute coords. Returns (dp1, dp2, first hit frame)."""
    sim.restore(root); a, b = sim.players(); base = (float(a["percent"]), float(b["percent"])); hit = None
    for f in range(frames):
        sim.step([p1(f), p2(f)])
        a, b = sim.players()
        if show: print(f"{f:3d} {st(sim)}")
        d = (float(a["percent"]) - base[0], float(b["percent"]) - base[1])
        if hit is None and (d[0] or d[1]): hit = f
    return d[0], d[1], hit
def prog(d, default=N): return lambda f: d.get(f, default)
