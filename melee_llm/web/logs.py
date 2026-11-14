"""Decision logs (*.llm.jsonl, *.coach.jsonl): find, read, and turn into token / cost estimates."""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

# USD per million tokens (input, output), list prices by model family; an estimate only. Edit as prices change.
PRICES = {"haiku": (1.0, 5.0), "sonnet": (3.0, 15.0), "opus": (5.0, 25.0), "jev": (0.042, 0.0)}


def logs_for(slp: Path) -> list[Path]:
    """Decision logs written next to a replay: <stem>.p<port>.<llm|coach>.jsonl."""
    return sorted(p for p in slp.parent.glob(slp.stem + ".p*.jsonl") if p.name.endswith((".llm.jsonl", ".coach.jsonl")))


def read(path: Path) -> list[dict]:
    out = []
    try:
        with path.open() as f:
            for line in f:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    pass  # a line being written
    except OSError:
        pass
    return out


def log_kind(path: str | Path) -> str:
    return "coach" if str(path).endswith(".coach.jsonl") else "llm"


def price(model: str, prompt: int, completion: int) -> float | None:
    fam = next((f for f in PRICES if f in (model or "")), None)
    if fam is None:
        return None
    pin, pout = PRICES[fam]
    return round((prompt * pin + completion * pout) / 1e6, 4)


def tokens(paths: list[Path]) -> dict | None:
    """Token totals over decision records, per model, with an estimated cost where the model's price is known."""
    by = defaultdict(lambda: {"prompt": 0, "completion": 0, "calls": 0})
    for p in paths:
        model = ""
        for r in read(p):
            if r.get("type") == "game_start":
                model = r.get("model") or r.get("coach") or model
            if r.get("type") == "decision" and (r.get("prompt_tokens") or r.get("completion_tokens")):
                m = by[r.get("model") or model or "?"]
                m["prompt"] += r.get("prompt_tokens") or 0
                m["completion"] += r.get("completion_tokens") or 0
                m["calls"] += 1
    if not by:
        return None
    costs = [price(m, v["prompt"], v["completion"]) for m, v in by.items()]
    return {"prompt": sum(v["prompt"] for v in by.values()), "completion": sum(v["completion"] for v in by.values()),
            "calls": sum(v["calls"] for v in by.values()), "by_model": dict(by),
            "est_usd": round(sum(c for c in costs if c), 4) if any(c is not None for c in costs) else None}


SLIM_DROP = ("obs",)


def slim(rec: dict) -> dict:
    """A record for the browser: the bulky structured observation goes (obs_text / state carry the same)."""
    return {k: v for k, v in rec.items() if k not in SLIM_DROP}
