"""One queued match, run in its own process group by the worker.

    python -m melee_llm.web.runjob --job '<json>' --dir replays/jobs/<id> --port 51441

Replays and decision logs go to --dir; each finished game appends a line to <dir>/results.jsonl.
"""
from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--job", required=True)
    ap.add_argument("--dir", required=True)
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--iso", required=True)
    a = ap.parse_args()
    job, out = json.loads(a.job), Path(a.dir)
    out.mkdir(parents=True, exist_ok=True)

    import melee

    from melee_llm.players import make
    from melee_llm.runner import play
    from melee_llm.util import append_jsonl, exit_on_term

    exit_on_term()  # so play()'s cleanup stops Dolphin and the bots
    agents = {1: make(job["p1"], job["char1"], out), 2: make(job["p2"], job["char2"], out)}

    def on(event: str, info: dict) -> None:
        if event == "game_end":
            r = info["result"]
            append_jsonl(out / "results.jsonl", {"game": info["game"], "time": time.strftime("%Y-%m-%dT%H:%M:%S"), **asdict(r)})

    play(agents, a.iso, melee.Stage[job["stage"]], job["mode"], job["games"], replay_dir=out, slippi_port=a.port,
         observer=on, meta={"source": "job", "label": f"job #{job['id']}", "job_id": job["id"],
                            "specs": {1: job["p1"], 2: job["p2"]}})


if __name__ == "__main__":
    main()
