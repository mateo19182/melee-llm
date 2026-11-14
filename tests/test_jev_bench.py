"""Live Jev benchmark (real API calls, costs ~$0.01): latency and decisions/sec from this host.

  uv run python tests/test_jev_bench.py [--n 30] [--concurrency 1 4 8]

Uses a real player request (rendered replay state + the fan-out questions) and a real coach request (Reyn's
Fox/Battlefield menu). Skipped under pytest unless JEV_BENCH=1.
"""
from __future__ import annotations

import argparse
import os
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def requests() -> dict[str, tuple]:
    import melee

    from melee_llm import jev as J
    from melee_llm.agents.coach import reyn_commands
    from melee_llm.agents.jev_coach import KEEP, NONE
    from melee_llm.agents.jev_player import JevPaused
    from melee_llm.runner import replay_states
    from melee_llm.state import observe, render, stage_text

    gs = list(replay_states(ROOT / "replays/sample-slippi-js-itemExport.slp"))[600]
    ports = sorted(gs.players)
    situation = render(observe(gs, ports[0], ports[1]))
    p = JevPaused()
    p.brief = {"game": f"YOU play FOX against FALCO. {stage_text(gs.stage)}"}
    full, single = p.questions(), {"action": p.questions()["action"]}
    menu = {c.id: c.name for c in reyn_commands(melee.Character.FOX, melee.Stage.BATTLEFIELD)} | {"keep": KEEP, "none": NONE}
    coach = {"command": J.choice(menu, "Which strategy command should the bot (YOU) follow?")}
    p.close()
    state = {**p.brief, "situation": situation}
    return {"player_fanout": (state, full), "player_action_only": (state, single), "coach_108": (state, coach)}


def bench(n: int, concurrency: list[int]) -> None:
    from melee_llm.jev import Jev
    reqs = requests()
    jev = Jev(timeout=5, retries=0)
    jev.ask("warm-up", {"q": {"type": "noul", "instructions": "Is this a test?"}})
    for name, (state, qs) in reqs.items():
        lat, tok = [], []
        for _ in range(n):
            r = jev.ask(state, qs)
            if r.ok:
                lat.append(r.latency_s * 1000)
                tok.append(r.input_tokens)
        lat.sort()
        print(f"{name:20s} questions {len(qs)} options {sum(len(q.get('criteria', {})) for q in qs.values())}: "
              f"ok {len(lat)}/{n}, ms p50 {lat[len(lat) // 2]:.0f} p90 {lat[int(len(lat) * .9)]:.0f} "
              f"max {lat[-1]:.0f}, input tokens {statistics.fmean(tok):.0f} (${statistics.fmean(tok) * 0.042e-6:.6f}/call)")
    state, qs = reqs["player_fanout"]
    for c in concurrency:
        errs, t0 = [], time.perf_counter()
        with ThreadPoolExecutor(c) as pool:
            reps = list(pool.map(lambda _: jev.ask(state, qs), range(n)))
        dt = time.perf_counter() - t0
        lat = sorted(r.latency_s * 1000 for r in reps if r.ok)
        errs = [r.error[:60] for r in reps if not r.ok]
        print(f"concurrency {c}: {len(lat)}/{n} ok in {dt:.1f}s = {len(lat) / dt:.1f} decisions/s, "
              f"ms p50 {lat[len(lat) // 2] if lat else 0:.0f} p90 {lat[int(len(lat) * .9)] if lat else 0:.0f}"
              + (f", errors {sorted(set(errs))}" if errs else ""))
    print("totals", jev.stats())
    jev.close()


@pytest.mark.skipif(os.environ.get("JEV_BENCH") != "1", reason="real API calls; set JEV_BENCH=1")
def test_bench():
    bench(10, [1, 4])


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=30)
    ap.add_argument("--concurrency", type=int, nargs="+", default=[1, 4, 8])
    a = ap.parse_args()
    bench(a.n, a.concurrency)
