"""Run a matrix of coding-agent sessions, a few at a time, each slot with its own Slippi port range.

  python -m melee_llm.botwriter.batch --plan plan.json --log runs.jsonl

plan.json: {"minutes": 30, "concurrency": 3, "ports_start": 51560, "ports_per_slot": 4, "max_retries": 2,
            "runs": [{"name": "opus-5.5/run1", "harness": "claude", "model": "claude-opus-5-5", "budget_usd": 40}, ...]}

Each run is `session run` in its own process. A run counts as a plumbing failure (and is retried) if
it ends in under `min_wall_frac` of its time, or the agent never got a turn in. Every attempt is
appended to the log; runs already logged as ok are skipped, so the batch is resumable.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import threading
import time
from pathlib import Path


def _ok(res: dict, minutes: float, min_wall_frac: float) -> str | None:
    """None if the run looks like a real session, else the reason it looks like a plumbing failure."""
    if "error" in res:
        return res["error"]
    if (res.get("wall_s") or 0) < min_wall_frac * minutes * 60:
        return f"ended after {res.get('wall_s')}s ({res.get('exit')})"
    turns = res.get("num_turns") or (res.get("usage") or {}).get("turns") or 0
    if turns < 3:
        return f"only {turns} agent turns"
    return None


def run_one(run: dict, plan: dict, ports: str) -> dict:
    cmd = [sys.executable, "-m", "melee_llm.botwriter.session", "run", "--harness", run["harness"],
           "--model", run["model"], "--minutes", str(run.get("minutes", plan["minutes"])), "--name", run["name"],
           "--slippi-ports", ports]
    for flag, key in (("--budget-usd", "budget_usd"), ("--effort", "effort"), ("--iso", "iso"), ("--base-url", "base_url")):
        if run.get(key) or plan.get(key):
            cmd += [flag, str(run.get(key) or plan.get(key))]
    if run.get("cliproxy", plan.get("cliproxy")):
        cmd.append("--cliproxy")
    p = subprocess.run(cmd, capture_output=True, text=True)
    try:
        lines = p.stdout.splitlines()
        start = max(i for i, line in enumerate(lines) if line == "{")  # session prints its summary last
        return json.loads("\n".join(lines[start:]))
    except ValueError:
        return {"error": f"exit {p.returncode}: {(p.stdout + p.stderr)[-1500:]}"}


def main() -> None:
    ap = argparse.ArgumentParser(prog="batch")
    ap.add_argument("--plan", required=True)
    ap.add_argument("--log", required=True)
    a = ap.parse_args()
    plan = {"concurrency": 3, "ports_start": 51560, "ports_per_slot": 4, "max_retries": 2, "min_wall_frac": 0.5,
            **json.loads(Path(a.plan).read_text())}
    log = Path(a.log)
    done = set()
    if log.exists():
        done = {r["name"] for r in map(json.loads, log.read_text().splitlines()) if r.get("ok")}
    queue = [r for r in plan["runs"] if r["name"] not in done]
    lock = threading.Lock()

    def slot(i: int) -> None:
        lo = plan["ports_start"] + i * plan["ports_per_slot"]
        ports = f"{lo}-{lo + plan['ports_per_slot'] - 1}"
        while True:
            with lock:
                if not queue:
                    return
                run = queue.pop(0)
            for attempt in range(plan["max_retries"] + 1):
                t0 = time.time()
                res = run_one(run, plan, ports)
                minutes = run.get("minutes", plan["minutes"])
                why = _ok(res, minutes, plan["min_wall_frac"])
                rec = {"name": run["name"], "attempt": attempt, "slot": i, "ports": ports, "started": t0,
                       "ok": why is None, "failure": why, **res}
                with lock, open(log, "a") as f:
                    f.write(json.dumps(rec, default=str) + "\n")
                print(f"{run['name']} attempt {attempt}: {'ok' if why is None else 'FAILED ' + why}", flush=True)
                if why is None:
                    break

    threads = [threading.Thread(target=slot, args=(i,)) for i in range(plan["concurrency"])]
    for t in threads:
        t.start()
    for t in threads:
        t.join()


if __name__ == "__main__":
    main()
