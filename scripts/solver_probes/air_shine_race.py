from melee_llm.solver.game import Sim, A, B, X, R
N = (0, 0, 0, 0); SHINE = (B, 0, -80, 0)
sim = Sim(); st = sim.setup(7)
def run(W, p2kind, hold_jump=1):
    """P1 hops, shines on W, double-jumps on W+3, shines on W+4. P2: 'same' shines on W and then re-shines as fast as he can,
    'hold' shines on W and keeps the reflector up, 'early' shines on W-1, 'wait' does nothing."""
    sim.restore(st)
    log = []
    for f in range(W + 40):
        p1 = (X, 0, 0, 0) if f < hold_jump else SHINE if f in (W, W + 4) else (X, 0, 0, 0) if f == W + 3 else N
        if p2kind == "same": p2 = SHINE if f in (W, W + 7) else (X, 0, 0, 0) if f == W + 3 else N
        elif p2kind == "hold": p2 = (B, 0, -80, 0) if f >= W else N
        elif p2kind == "early": p2 = SHINE if f == W - 1 else N
        elif p2kind == "shield": p2 = (R, 0, 0, 255) if f >= W - 1 else N
        else: p2 = N
        sim.step([p1, p2]); a, b = sim.players()
        if f in (W, W + 4): log.append((f, round(float(a["pos_y"]), 1), round(float(b["pos_x"] - a["pos_x"]), 1)))
    a, b = sim.players()
    return float(a["percent"]), float(b["percent"]), log
for W in range(5, 13):
    row = []
    for k in ("wait", "same", "hold", "early", "shield"):
        p1, p2, log = run(W, k); row.append(f"{k}: P1 {p1:.0f}% P2 {p2:.0f}%")
    print(f"shine on hop frame {W:2d} (y, dx at the two shines {log}): " + " | ".join(row))
