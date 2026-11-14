"""Offline tests for the LLM-player layer: state rendering and macros on replays (macros in the real game:
test_macros.py).

Run: uv run pytest -q tests/ ; or `uv run python tests/test_llm_layer.py` to print sample renderings.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parent.parent)]


from melee_llm import actions  # noqa: E402
from melee_llm.actions import Executor, RecordingController  # noqa: E402
from melee_llm.runner import replay_states  # noqa: E402
from melee_llm.state import EventTracker, observe, render  # noqa: E402

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
