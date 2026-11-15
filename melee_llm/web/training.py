"""Own-bot training runs (lane B): data/train/runs/<name>/, written by train/meleebot/train.py (behaviour cloning)
or train/meleebot/rl/ppo.py (self-play RL, run.json kind "rl").

run.json is written once at start (args, size, total steps); train.jsonl gets a point every 100 steps
and log.jsonl one per validation. Runs started before run.json existed have their stdout in
runs/<name>.out, which stands in for train.jsonl. RL runs log one line per iteration to rl.jsonl and
record sample games as .slp under the replays folder named in run.json.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from melee_llm.paths import DATA
from melee_llm.web.games import game_id

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


def _state(updated: float, finished: bool) -> str:
    return "done" if finished else "stopped" if time.time() - updated > STALE_S else "running"


def rl_run(d: Path, info: dict) -> dict:
    points = _jsonl(d / "rl.jsonl")
    log = d / "rl.jsonl"
    updated = log.stat().st_mtime if log.exists() else d.stat().st_mtime
    iters = (info.get("args") or {}).get("iters")
    it = points[-1]["iter"] if points else 0
    slps = sorted(Path(info["replays"]).glob("*.slp"), key=lambda p: p.stat().st_mtime) if info.get("replays") else []
    replays = [{"name": p.stem, "id": game_id(p), "time": p.stat().st_mtime} for p in slps[-12:][::-1]]
    last = points[-1] if points else {}
    return {"name": d.name, "kind": "rl", "state": _state(updated, bool(iters and it >= iters)), "step": it,
            "steps": None, "updated": updated, "frames_per_s": last.get("fps"), "params": info.get("params"),
            "args": info.get("args"), "init": info.get("init"), "pool": info.get("pool"), "train": points,
            "replays": replays, "n_replays": len(slps)}


def run(d: Path) -> dict:
    info = json.loads((d / "run.json").read_text()) if (d / "run.json").exists() else {}
    if info.get("kind") == "rl":
        return rl_run(d, info)
    points = _jsonl(d / "train.jsonl")
    legacy = {}
    if not points:
        points, legacy = _from_stdout(d.parent / f"{d.name}.out")
    evals = _jsonl(d / "log.jsonl")
    files = [p for p in (d / "train.jsonl", d / "log.jsonl", d.parent / f"{d.name}.out") if p.exists()]
    updated = max((p.stat().st_mtime for p in files), default=d.stat().st_mtime)
    step = max([p["step"] for p in points] + [e["step"] for e in evals] + [0])
    steps = info.get("steps") or (info.get("args") or {}).get("steps")
    state = _state(updated, bool(info.get("finished_at") or (steps and step >= steps)))
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
