"""Older results that already meet the bench standard, read in place and tagged `imported`.

The standard: Fox vs Fox on Battlefield or Final Destination, a full game (4 stocks, 8-minute timer), both players
bench entrants with the bench's spec options. A game with a wall-clock player (live LLM, Jev live, coach) counts
only if it ran at real-time speed (mean ≥ MIN_FPS), since a slower game gives that player more game time per
decision. Everything else is counted as excluded, by reason.
"""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime
from pathlib import Path

from melee_llm.bench.entrants import BOTWRITER, Entrant, by_id, resolve
from melee_llm.paths import ARENA, DATA, ROOT
from melee_llm.util import read_jsonl as _jsonl

STAGES = ("BATTLEFIELD", "FINAL_DESTINATION")
# other runs of the bench scheduler (own out dir); a run never imports its own dir (Bench drops source == out.name)
SIDE_BENCHES = ("bench-deepdive",)
MIN_FPS = 50.0


def _abs(p: str | None) -> str | None:
    if not p:
        return None
    path = Path(p)
    return str(path if path.is_absolute() else ROOT / path)


class _Collector:
    def __init__(self):
        self.entrants: dict[str, Entrant] = by_id()
        self.games: list[dict] = []
        self.excluded: Counter = Counter()

    def add(self, source: str, n: int, p1: str, p2: str, r: dict, *, stage: str, chars=("FOX", "FOX"), mode: str,
            ts: float | None, replay: str | None, check_fps: bool = True) -> None:
        if stage not in STAGES or tuple(chars) != ("FOX", "FOX"):
            self.excluded[f"{source}: not Fox ditto on BF/FD"] += 1
            return
        a, b = resolve(p1, self.entrants), resolve(p2, self.entrants)
        if not a or not b:
            self.excluded[f"{source}: player not a bench entrant ({p1 if not a else p2})"] += 1
            return
        if a == b:
            self.excluded[f"{source}: self-play"] += 1
            return
        frames, secs = r.get("frames"), r.get("seconds")
        fps = round(frames / secs, 1) if frames and secs else None
        if check_fps and mode != "fast" and (self.entrants[a].wall_clock or self.entrants[b].wall_clock) \
                and (fps is None or fps < MIN_FPS):
            self.excluded[f"{source}: wall-clock player below {MIN_FPS:.0f} fps"] += 1
            return
        self.games.append({
            "id": f"import:{source}:{n}", "source": source, "imported": True, "status": "ok", "p1": a, "p2": b,
            "stage": stage, "mode": mode, "winner": r.get("winner"), "stocks": r.get("stocks"),
            "percent": r.get("percent"), "frames": frames, "seconds": secs, "fps": fps, "replay": _abs(replay),
            "ts": ts})


def _ts(s: str | None) -> float | None:
    try:
        return datetime.fromisoformat(s).timestamp() if s else None
    except ValueError:
        return None


def load() -> tuple[list[dict], dict[str, int]]:
    c = _Collector()
    # LLM vs LLM arena (llm_paused, fast mode): only games that ended before the frame cap are full games
    for f in sorted((ROOT / "data/llm-arena").glob("*/results.jsonl")):
        src = f"llm-arena/{f.parent.name}"
        for n, r in enumerate(_jsonl(f)):
            if r.get("status") != "ok":
                continue
            if any(s.get("capped_at") is not None for s in (r.get("sides") or {}).values()):
                c.excluded[f"{src}: capped at {r.get('cap_frames')} frames (not a full game)"] += 1
                continue
            if any("," in r[k] for k in ("p1", "p2")):
                c.excluded[f"{src}: non-default player options"] += 1
                continue
            c.add(src, n, r["p1"], r["p2"], r, stage=r["stage"], mode="fast", ts=r.get("ts"), replay=r.get("replay"))
    # coach and Jev pilots (lockstep on :98, scripts/coach_pilot.py)
    for f in sorted((ROOT / "replays/coach-pilot").glob("*/results.jsonl")) + \
            sorted((ROOT / "replays/jev-pilot").glob("*/results.jsonl")):
        src = f"{f.parent.parent.name}/{f.parent.name}"
        for n, r in enumerate(_jsonl(f)):
            if "winner" not in r:
                continue
            c.add(src, n, r["p1"], r["p2"], r, stage=r["stage"], chars=(r.get("char1"), r.get("char2")),
                  mode=r.get("mode", "lockstep"), ts=Path(f).stat().st_mtime, replay=r.get("replay"))
    # learned-bot arena on the live slot (random characters and stages: only the Fox dittos on BF/FD qualify)
    for n, r in enumerate(_jsonl(ARENA / "results.jsonl")):
        c.add("arena", n, r["p1"], r["p2"], r, stage=r["stage"], chars=(r["char1"], r["char2"]), mode="lockstep",
              ts=_ts(r.get("time")), replay=r.get("replay"))
    # bot-writer ladders (fast mode, Fox ditto BF/FD, full games)
    for cfg_path in sorted((BOTWRITER / "ladders").glob("*.json")):
        try:
            cfg = json.loads(cfg_path.read_text())
        except (OSError, ValueError):
            continue
        paths = cfg.get("entrants", {})
        src = f"ladder/{cfg_path.stem}"
        for n, r in enumerate(_jsonl(BOTWRITER / "ladders" / cfg_path.stem / "games.jsonl")):
            if r.get("error") or "winner" not in r:
                continue
            if r.get("forfeit"):
                c.excluded[f"{src}: forfeit (bot failed to load)"] += 1
                continue
            a = paths.get(r["a"], r["a"])
            pa, pb = r["a_port"], 3 - r["a_port"]
            names = {pa: a, pb: r["b"]}
            rr = {"winner": {"a": pa, "b": pb}.get(r["winner"]), "frames": r.get("frames"), "seconds": r.get("seconds"),
                  "stocks": {str({"a": pa, "b": pb}[k]): v for k, v in (r.get("stocks") or {}).items()},
                  "percent": {str({"a": pa, "b": pb}[k]): v for k, v in (r.get("percent") or {}).items()}}
            c.add(src, n, names[1], names[2], rr, stage=r["stage"], mode="fast", ts=r.get("ts"), replay=r.get("replay"))
    # side runs of the bench itself (same scheduler and rules), e.g. the coach deep-dive's ablations
    for name in SIDE_BENCHES:
        for n, r in enumerate(_jsonl(DATA / name / "results.jsonl")):
            if r.get("status") == "ok":
                c.add(name, n, r["p1"], r["p2"], r, stage=r["stage"], mode=r["mode"], ts=r.get("ts"), replay=r.get("replay"))
    return c.games, dict(c.excluded)

