"""One queued match, run in its own process group by the worker.

    python -m melee_llm.web.runjob --job '<json>' --dir replays/jobs/<id> --port 51441 [--live]

Replays and decision logs go to --dir; each finished game appends a line to <dir>/results.jsonl.
"""
from __future__ import annotations

import argparse
import json
import signal
import sys
import time
from dataclasses import asdict
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--job", required=True)
    ap.add_argument("--dir", required=True)
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--iso", required=True)
    ap.add_argument("--live", action="store_true", help="this job owns display :99: report to data/live.json")
    a = ap.parse_args()
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))  # so play()'s cleanup stops Dolphin and the bots
    job, out = json.loads(a.job), Path(a.dir)
    out.mkdir(parents=True, exist_ok=True)

    import melee

    from match import make
    from melee_llm.runner import play
    from melee_llm.web.live import LiveReporter

    agents = {1: make(job["p1"], job["char1"]), 2: make(job["p2"], job["char2"])}
    for ag in agents.values():
        if hasattr(ag, "log_dir"):
            ag.log_dir = out  # keep decision logs next to this job's replays (and away from parallel jobs)
    reporter = observer = None
    if a.live:
        reporter = LiveReporter("job", job["p1"], job["p2"], job["char1"], job["char2"], job["stage"], job["mode"],
                                job["games"], job_id=job["id"])
        observer = reporter.observer(agents)

    def on(event: str, info: dict) -> None:
        if observer:
            observer(event, info)
        if event == "game_end":
            r = info["result"]
            rec = {"game": info["game"], "time": time.strftime("%Y-%m-%dT%H:%M:%S"), **asdict(r)}
            with (out / "results.jsonl").open("a") as f:
                f.write(json.dumps(rec, default=float) + "\n")

    error = None
    try:
        play(agents, a.iso, melee.Stage[job["stage"]], job["mode"], job["games"], replay_dir=out, slippi_port=a.port,
             observer=on, meta={"source": "job", "label": f"job #{job['id']}", "job_id": job["id"],
                                "specs": {1: job["p1"], 2: job["p2"]}})
    except BaseException as e:
        error = f"{type(e).__name__}: {e}"
        raise
    finally:
        if reporter:
            reporter.done(error)


if __name__ == "__main__":
    main()
