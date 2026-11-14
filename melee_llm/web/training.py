"""Own-bot training runs (lane B): data/train/runs/<name>/, written by train/meleebot/train.py.

run.json is written once at start (args, size, total steps); train.jsonl gets a point every 100 steps
and log.jsonl one per validation. Runs started before run.json existed have their stdout in
runs/<name>.out, which stands in for train.jsonl.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from melee_llm.paths import DATA

RUNS = DATA / "train" / "runs"
STALE_S = 180
_STEP = re.compile(r"^step (\d+) loss ([\d.]+) lr ([\d.e+-]+) (\d+)k frames/s, ([\d.]+) min")


def _jsonl(p: Path) -> list[dict]:
    if not p.exists():
        return []
    out = []
    for ln in p.read_text().splitlines():
        try:
            out.append(json.loads(ln))
        except ValueError:
            pass
    return out


def _from_stdout(p: Path) -> tuple[list[dict], dict]:
    points, meta = [], {}
    if not p.exists():
        return points, meta
    for ln in p.read_text(errors="replace").splitlines():
        if m := _STEP.match(ln):
            points.append({"step": int(m[1]), "loss": float(m[2]), "lr": float(m[3]),
                           "frames_per_s": int(m[4]) * 1000, "minutes": float(m[5])})
        elif "M params" in ln:
            meta["summary"] = ln.strip()
    return points, meta


def run(d: Path) -> dict:
    info = json.loads((d / "run.json").read_text()) if (d / "run.json").exists() else {}
    points = _jsonl(d / "train.jsonl")
    legacy = {}
    if not points:
        points, legacy = _from_stdout(d.parent / f"{d.name}.out")
    evals = _jsonl(d / "log.jsonl")
    files = [p for p in (d / "train.jsonl", d / "log.jsonl", d.parent / f"{d.name}.out") if p.exists()]
    updated = max((p.stat().st_mtime for p in files), default=d.stat().st_mtime)
    step = max([p["step"] for p in points] + [e["step"] for e in evals] + [0])
    steps = info.get("steps") or (info.get("args") or {}).get("steps")
    if info.get("finished_at") or (steps and step >= steps):
        state = "done"
    elif time.time() - updated > STALE_S:
        state = "stopped"
    else:
        state = "running"
    last = points[-1] if points else {}
    eta = None
    if state == "running" and steps and last.get("minutes") and step:
        eta = (steps - step) * last["minutes"] * 60 / step
    return {"name": d.name, "state": state, "step": step, "steps": steps, "updated": updated, "eta_s": eta,
            "frames_per_s": last.get("frames_per_s"), "params": info.get("params"),
            "summary": info.get("summary") or legacy.get("summary"), "args": info.get("args"),
            "train": points, "evals": evals}


def runs() -> list[dict]:
    if not RUNS.exists():
        return []
    out = [run(d) for d in RUNS.iterdir() if d.is_dir()]
    return sorted(out, key=lambda r: (r["state"] != "running", -r["updated"]))
