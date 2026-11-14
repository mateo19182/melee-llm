"""Token spend recounted from the decision logs, for games recorded before dropped replies carried their usage.

results.jsonl stays as written. `python -m melee_llm.bench recount` re-reads every game's logs with the current
`side_stats` (dropped replies counted, or estimated at the log's mean tokens per call) into data/bench/recount.json;
the standings' per-entrant spend and status.json's `spent_recounted` use it, while `spent` (the budget counter)
stays what the scheduler counted at the time.
"""
from __future__ import annotations

import json
from pathlib import Path

from melee_llm.bench.game import side_stats
from melee_llm.paths import ROOT

PATH = ROOT / "data/bench/recount.json"
KEYS = ("decisions", "dropped", "calls", "prompt_tokens", "completion_tokens", "tokens_estimated", "usd")


def recount(results: list[dict]) -> dict[str, dict[str, dict]]:
    """{game id: {port: side}}: each side as recorded, with its counts re-read from the logs."""
    out = {}
    for r in results:
        if not r.get("sides") or not r.get("dir") or not Path(r["dir"]).is_dir():
            continue
        sides = {}
        for port, s in r["sides"].items():
            new = side_stats(Path(r["dir"]), int(port))
            sides[port] = {**s, **{k: new[k] for k in KEYS}} if new else s
        out[r["id"]] = sides
    return out


def load(path: Path = PATH) -> dict:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def apply(results: list[dict], rc: dict | None = None) -> list[dict]:
    """Results with recounted sides where a recount exists (games logged since the fix are already complete)."""
    rc = load() if rc is None else rc
    return [{**r, "sides": rc[r["id"]]} if r.get("id") in rc and "dropped" not in next(iter(r["sides"].values()), {})
            else r for r in results]
