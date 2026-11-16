"""Ness's yo-yo glitch against Fox, on melee-sim-light.

1. Setup: a charged up smash that hits Fox (at 60%) once, released `release` frames after the input, leaves the
   yo-yo's last hitbox behind Ness (`ftNs_AttackHi4`: the rehit refresh never schedules its own removal).
2. Deathline: Ness runs past Fox so Fox stands between him and the dropped hitbox, turns, and jabs or forward
   smashes: the attack's hitbox stretches back to the dropped one for a frame and hits along the line.
3. Fox reacts on frame d >= 1 with each of probe.REACTIONS; does any reaction escape?

    uv run python -m melee_llm.solver.yoyo
"""
from __future__ import annotations

import melee

from melee_llm.solver.game import NONE, A, Sim, move
from melee_llm.solver.probe import REACTIONS, _hurt, _row

ATTACKS = {"jab": (A, 0, 0, 0, 0, 0), "fsmash": (0, 0, 0, -80, 0, 0)}


def setup(sim: Sim, start: bytes, release: int) -> bytes:
    """Up smash on Fox from a gap of about 13, A held until `release`, then both idle until Fox has landed."""
    sim.restore(sim.setup(13, start))
    for f in range(100):
        sim.step([(A, 0, 80 if f == 0 else 0, 0, 0, 0) if f < release else NONE, NONE])
    sim.idle(90)
    return sim.save()


def behind(sim: Sim, state: bytes, past: float) -> bytes:
    """Ness runs right until he is `past` units beyond Fox, stops and turns to face him."""
    sim.restore(state)
    for _ in range(400):
        a, b = sim.players()
        if float(a["pos_x"]) > float(b["pos_x"]) + past:
            break
        sim.step([(0, 80, 0, 0, 0, 0), NONE])
    sim.idle(25)
    sim.step([(0, -40, 0, 0, 0, 0), NONE])
    sim.idle(11)
    return sim.save()


def attack(sim: Sim, state: bytes, name: str, react: str = "wait", delay: int = 0) -> int | None:
    """First frame (1-based) Fox is hit by Ness's `name`, with Fox answering `react` from frame `delay`."""
    sim.restore(state)
    fn = move(react)
    for f in range(40):
        a, b = sim.players()
        pb = _row(b)
        sim.step([ATTACKS[name] if f == 0 else NONE, fn(f - delay, -1, b) if f >= delay else NONE])
        if _hurt(pb, sim.players()[1]):
            return f + 1
    return None


def main() -> None:
    sim = Sim(melee.Character.NESS, melee.Character.FOX, (0, 60))
    start = sim.start()
    for glitch, release in ((True, 25), (False, 40)):
        st = setup(sim, start, release)
        for past in (15, 30):
            far = behind(sim, st, past)
            sim.restore(far)
            a, b = sim.players()
            dist = float(a["pos_x"] - b["pos_x"])
            for name in ATTACKS:
                idle = attack(sim, far, name)
                escapes = [r for r in REACTIONS
                           if idle and any(attack(sim, far, name, r, d) is None for d in range(1, idle))]
                print(f"glitch={glitch!s:5s} distance {dist:5.1f} {name:6s} idle Fox hit on "
                      f"{'f' + str(idle) if idle else '-'}; reactions that escape: {escapes if idle else '-'}")
    sim.world.close()


if __name__ == "__main__":
    main()
