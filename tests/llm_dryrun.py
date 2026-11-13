"""Drive an LLM agent with replay states (no ISO): real LLM calls, controller output recorded, not sent.

  uv run python tests/llm_dryrun.py replays/x.slp llm_paused:claude-haiku-4-5-20251001 --decisions 5
  --realtime streams frames at 60 fps (for llm_live latency in frames). The replay ignores our inputs, so
  this measures prompts, parsing and latency, not play quality.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from melee_llm.actions import RecordingController  # noqa: E402
from melee_llm.agents.llm_live import LiveLLM  # noqa: E402
from melee_llm.agents.llm_paused import PausedLLM  # noqa: E402
from melee_llm.runner import replay_states  # noqa: E402


def main():
    p = argparse.ArgumentParser()
    p.add_argument("slp")
    p.add_argument("agent", help="llm_paused:<model>[,k=v] or llm_live:<model>[,k=v]")
    p.add_argument("--decisions", type=int, default=5)
    p.add_argument("--port", type=int, default=0, help="0 = first port in the replay")
    p.add_argument("--start", type=int, default=300, help="skip this many frames")
    p.add_argument("--realtime", action="store_true")
    a = p.parse_args()
    kind, _, spec = a.agent.partition(":")
    log_dir = Path(tempfile.mkdtemp(prefix="llm-dryrun-"))
    agent = {"llm_paused": PausedLLM, "llm_live": LiveLLM}[kind](spec, log_dir=log_dir)
    states = list(replay_states(a.slp))[a.start:]
    ports = sorted(states[0].players)
    port = a.port or ports[0]
    agent.setup(RecordingController(), port, next(q for q in ports if q != port))
    step_ms = []
    for gs in states:
        t0 = time.perf_counter()
        agent.step(gs)
        dt = time.perf_counter() - t0
        step_ms.append(dt * 1000)
        agent.controller.flush()
        if len(agent.stats) >= a.decisions:
            break
        if a.realtime:
            time.sleep(max(0., 1 / 60 - dt))
    agent.on_game_end(gs)
    agent.close()
    log = next(log_dir.glob("*.jsonl"))
    recs = [json.loads(line) for line in log.read_text().splitlines()]
    for r in recs:
        if r["type"] == "decision":
            print(f"f{r['frame']:5} {r['action']:12} {json.dumps({k: v for k, v in r['decision'].items() if k != 'action'})}"
                  f" | {r['latency_s']:.2f}s in={r['prompt_tokens']} out={r['completion_tokens']}"
                  + (f" lat={r['latency_frames']}f stale={r['stale_frames']}f" if kind == "llm_live" else "")
                  + (f" ERR {r['error']}" if r["error"] else ""))
    print("summary", json.dumps(recs[-1]))
    step_ms.sort()
    print(f"step() ms: p50 {step_ms[len(step_ms) // 2]:.2f} p99 {step_ms[int(len(step_ms) * .99)]:.2f} max {step_ms[-1]:.1f}")
    print("log", log)


if __name__ == "__main__":
    main()
