"""The LLM player's input macros (melee_llm/actions.py) played in the real game: melee-sim-light runs Melee's
gameplay code, so a macro that presses on the wrong frame does what Melee does with that input.

Run `uv run python tests/test_macros.py` to print the traces.
"""
from __future__ import annotations

import melee
import pytest
from melee import Action as A

from melee_llm.actions import DIGITAL, Executor
from melee_llm.sim import scenes, world

pytestmark = pytest.mark.skipif(not world.available(), reason="melee-sim-light's game data is not extracted (docs/simulator.md)")


@pytest.fixture(scope="module")
def sim():
    w = world.World({1: melee.Character.FOX, 2: melee.Character.FALCO}, melee.Stage.BATTLEFIELD)
    yield w, {"center": scenes.center(w), "dashing": scenes.dashing(w), "ledge": scenes.ledge(w)}
    w.close()


def _inputs(inp) -> str:
    btn = "".join(b.value for b in DIGITAL if b in inp.buttons) or "-"
    fmt = lambda t: f"{t[0]:.2f},{t[1]:.2f}"
    return f"{btn:4} main({fmt(inp.main)}) c({fmt(inp.c)})" + (f" L{inp.l:.1f}" if inp.l else "")


def play(sim, decision: dict, scene: str = "center", frames: int = 120):
    """Run one macro from a saved scene. Returns the executor, port 1's final state and one line per frame:
    the state the macro saw, then what it pressed."""
    w, saved = sim
    gs = w.restore(saved[scene])
    ex = Executor(w.controllers[1], 1, 2)
    ex.ctx.gs = gs
    ex.start(decision)
    trace = []
    for _ in range(frames):
        me = gs.players[1]
        before = f"{me.action.name.lower()[:16]:16} f{me.action_frame:<2} y{me.position.y:6.1f}"
        inp = ex.step(gs)
        trace.append(f"{before} -> {_inputs(inp)}")
        gs = w.step()
        if ex.idle:
            break
    return ex, gs.players[1], trace


def _first(trace, needle):
    return next(i for i, line in enumerate(trace) if needle in line.split("->")[1])


def test_short_hop_fair_lcancels(sim):
    ex, me, tr = play(sim, {"action": "fair", "jump": "short", "dir": "toward"})
    assert ex.idle, tr
    outcome = ex.drain()[-1]
    assert outcome[0] == "fair" and "l-cancel" in outcome[1], (outcome, tr)
    assert sum("Y" in line.split("->")[1] for line in tr) == 1  # one-frame jump press = short hop
    assert sum(line.startswith("fair_landing") for line in tr) == 11, tr  # Fox's 22 frames, halved by the L-cancel


def test_wavedash_presses_airdodge_after_jumpsquat(sim):
    ex, me, tr = play(sim, {"action": "wavedash", "dir": "toward"})
    i = _first(tr, "L")
    assert "knee_bend" in tr[i] and "f3" in tr[i], tr  # pressed on the last jumpsquat frame
    assert any("landing_special" in line for line in tr), tr


def test_shine_jump_cancel(sim):
    ex, me, tr = play(sim, {"action": "shine", "then": "jump"})
    assert "B" in tr[0].split("->")[1] and "0.00)" in tr[0], tr  # down+B
    assert ex.drain()[-1][1] == "jump-cancelled", tr
    assert me.action == A.KNEE_BEND, tr


def test_grab_whiffs_on_nobody(sim):
    ex, me, tr = play(sim, {"action": "grab", "throw": "b"})
    assert "Z" in "".join(tr) and ex.drain()[-1][1] == "whiffed", tr


def test_roll_away(sim):
    ex, me, tr = play(sim, {"action": "roll", "dir": "away"})
    assert any("roll_backward" in line or "roll_forward" in line for line in tr), tr


def test_ledge_getup_and_drop_work_with_the_stick_still_held_from_the_grab(sim):
    ex, me, tr = play(sim, {"action": "ledge", "ledge": "getup"}, scene="ledge")
    assert ex.drain()[-1][1] == "ok" and any("edge_getup" in line for line in tr), tr
    assert me.on_ground and abs(me.position.y) < 1, tr
    ex, me, tr = play(sim, {"action": "ledge", "ledge": "drop"}, scene="ledge", frames=10)
    assert any(line.startswith("fall") for line in tr), tr  # let go (then the offstage reflex takes over)


def test_jab_from_dash_stops_first(sim):
    ex, me, tr = play(sim, {"action": "jab"}, scene="dashing")
    assert any("neutral_attack_1" in line for line in tr) and not any("dash_attack" in line for line in tr), tr


if __name__ == "__main__":
    w = world.World({1: melee.Character.FOX, 2: melee.Character.FALCO}, melee.Stage.BATTLEFIELD)
    s = (w, {"center": scenes.center(w), "dashing": scenes.dashing(w), "ledge": scenes.ledge(w)})
    for d, scene in [({"action": "fair", "jump": "short"}, "center"), ({"action": "wavedash", "dir": "toward"}, "center"),
                     ({"action": "shine", "then": "jump"}, "center"), ({"action": "grab", "throw": "d"}, "center"),
                     ({"action": "roll", "dir": "away"}, "center"), ({"action": "jab"}, "dashing"),
                     ({"action": "laser", "jump": "short"}, "center"), ({"action": "dash_dance", "frames": 16}, "center"),
                     ({"action": "ledge", "ledge": "getup"}, "ledge"), ({"action": "ledge", "ledge": "jump"}, "ledge")]:
        ex, me, tr = play(s, d, scene)
        print(f"== {d} from {scene} → {ex.drain()}")
        print("\n".join(tr[:40]))
