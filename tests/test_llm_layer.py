"""Offline tests for the LLM-player layer: state rendering on replays, macros on a toy sim and replays.

Run: uv run --with pytest pytest -q tests/ ; or `uv run python tests/test_llm_layer.py` to print traces.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parent.parent), str(Path(__file__).parent)]

from melee import Action as A  # noqa: E402

from melee_llm import actions  # noqa: E402
from melee_llm.actions import Executor, RecordingController  # noqa: E402
from melee_llm.runner import replay_states  # noqa: E402
from melee_llm.state import EventTracker, observe, render  # noqa: E402
from fakesim import FakeSim  # noqa: E402

REPLAYS = Path(__file__).resolve().parent.parent / "replays"
SAMPLE = REPLAYS / "sample-slippi-js-itemExport.slp"  # Falco vs Samus, Battlefield, stock loss


def _frames(path=SAMPLE, every=1):
    gss = list(replay_states(path))
    return gss[::every]


def sample_renderings(n=3):
    gss = _frames()
    p1, p2 = sorted(gss[0].players)
    tr, out = EventTracker(p1, p2), []
    picks = {len(gss) * k // (n + 1) for k in range(1, n + 1)}
    for i, gs in enumerate(gss):
        tr.update(gs)
        if i in picks:
            out.append(render(observe(gs, p1, p2), tr.drain()))
    return out


def test_render_on_replays():
    for slp in sorted(REPLAYS.glob("sample-slippi-js-*.slp")):
        gss = _frames(slp, every=7)
        p1, p2 = sorted(gss[0].players)[:2]
        tr = EventTracker(p1, p2)
        for gs in gss:
            tr.update(gs)
            o = observe(gs, p1, p2)
            txt = render(o, tr.drain())
            json.dumps(o)  # must be JSON-serialisable for logs
            assert "YOU" in txt and "OPP" in txt
            assert len(txt) < 1400, txt  # ≈ ≤350 tokens


def test_events_detect_stock_loss_and_hits():
    gss = _frames()
    p1, p2 = sorted(gss[0].players)
    tr, all_events = EventTracker(p1, p2), []
    for gs in gss:
        tr.update(gs)
        if gs.frame % 60 == 0:
            all_events.append(tr.drain())
    text = " ".join(all_events)
    assert "LOST A STOCK" in text and "you hit opp" in text and "got hit" in text


def sim_trace(decision, frames=90, **sim_kw):
    sim = FakeSim(**sim_kw)
    ex = Executor(sim.ctrl, 1, 2)
    trace = sim.run(ex, frames, decision)
    return sim, ex, trace


def _first(trace, needle):
    return next(i for i, line in enumerate(trace) if needle in line.split("->")[1])


def test_short_hop_fair_lcancels():
    sim, ex, tr = sim_trace({"action": "fair", "jump": "short", "dir": "toward"})
    assert ex.idle, tr
    outcome = ex.drain()[-1]
    assert outcome[0] == "fair" and "l-cancel" in outcome[1], (outcome, tr)
    assert any("fair_landing" in line for line in tr)
    assert sum("Y" in line.split("->")[1] for line in tr) == 1  # one-frame jump press = short hop


def test_wavedash_presses_airdodge_after_jumpsquat():
    sim, ex, tr = sim_trace({"action": "wavedash", "dir": "toward"})
    i = _first(tr, "L")
    assert "knee_bend" in tr[i] and "f3" in tr[i], tr  # pressed on the last jumpsquat frame
    assert any("landing_special" in line for line in tr), tr


def test_shine_jump_cancel():
    sim, ex, tr = sim_trace({"action": "shine", "then": "jump"})
    assert "B" in tr[0].split("->")[1] and "0.00)" in tr[0]  # down+B
    assert ex.drain()[-1][1] == "jump-cancelled"
    assert sim.me.action == A.KNEE_BEND


def test_grab_whiff_and_roll_and_ledge():
    sim, ex, tr = sim_trace({"action": "grab", "throw": "b"})
    assert "Z" in "".join(tr) and ex.drain()[-1][1] == "whiffed"
    sim, ex, tr = sim_trace({"action": "roll", "dir": "away"})
    assert any("roll_backward" in line or "roll_forward" in line for line in tr), tr
    sim, ex, tr = sim_trace({"action": "ledge", "ledge": "getup"}, x=-71.3, y=-5, action=A.EDGE_HANGING)
    assert ex.drain()[-1][1] == "ok", tr


def test_jab_from_dash_stops_first():
    sim, ex, tr = sim_trace({"action": "jab"}, action=A.DASHING)
    assert any("neutral_attack_1" in line for line in tr) and not any("dash_attack" in line for line in tr), tr


def test_every_action_runs_on_replay_states():
    """Each macro, started on varied real replay states, yields valid Inputs and never raises."""
    gss = _frames(every=3)
    p1, p2 = sorted(gss[0].players)
    for name in actions.ACTIONS:
        for start in range(0, len(gss) - 200, 97):
            ctrl = RecordingController()
            ex = Executor(ctrl, p1, p2)
            ex.ctx.gs = gss[start]
            ex.start({"action": name})
            for gs in gss[start:start + 60]:
                inp = ex.step(gs)
                assert all(0 <= v <= 1 for v in (*inp.main, *inp.c)), (name, inp)
                ctrl.flush()


def test_tool_schema_roundtrip():
    sch = actions.tool_schema()
    json.dumps(sch)
    props = sch["function"]["parameters"]["properties"]
    assert set(actions.ACTIONS) == set(props["action"]["enum"])
    for spec in actions.ACTIONS.values():
        assert set(spec.params) <= set(props)


if __name__ == "__main__":
    for r in sample_renderings():
        print(r, f"\n  (~{len(r) // 4} tokens)\n")
    for d, kw in [({"action": "fair", "jump": "short"}, {}), ({"action": "wavedash", "dir": "toward"}, {}),
                  ({"action": "shine", "then": "jump"}, {}), ({"action": "grab", "throw": "d"}, {}),
                  ({"action": "laser", "jump": "short"}, {}), ({"action": "dash_dance", "frames": 16}, {}),
                  ({"action": "recover"}, {"x": -110., "y": -30., "action": A.FALLING}),
                  ({"action": "ledge", "ledge": "jump"}, {"x": -71.3, "y": -5, "action": A.EDGE_HANGING})]:
        sim, ex, tr = sim_trace(d, **kw)
        print(f"== {d} → {ex.drain()}")
        print("\n".join(tr[:40]))
