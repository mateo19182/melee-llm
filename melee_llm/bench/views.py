"""What the web UI's Bench pages show: the board (standings + progress) and one entrant's detail."""
from __future__ import annotations

import json
import time
from pathlib import Path

from melee_llm.bench import imports, ratings, recount
from melee_llm.bench.entrants import CATEGORIES, GROUPS, TRACKS, by_id
from melee_llm.bench.scheduler import DATA, read_results

_cache: dict = {"imports": (0.0, [], {})}


def _imports() -> tuple[list[dict], dict]:
    t, games, exc = _cache["imports"]
    if time.time() - t > 120:
        games, exc = imports.load()
        _cache["imports"] = (time.time(), games, exc)
    return games, exc


def _json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def standings() -> dict:
    st = _json(DATA / "standings.json")
    if st is None or "board" not in st:  # missing, or written before the single board
        imp, exc = _imports()
        st = ratings.standings(recount.apply(read_results(DATA / "results.jsonl")), imp, exc, boot=200)
    return st


def board() -> dict:
    status = _json(DATA / "status.json") or {"phase": "not started"}
    if status.get("phase") == "running" and time.time() - status.get("updated", 0) > 120:
        status["phase"] = "stale"  # the scheduler stopped writing: crashed or killed
    return {"standings": standings(), "status": status, "categories": CATEGORIES, "clocks": TRACKS, "groups": GROUPS}


def _game_id(replay: str | None) -> str | None:
    if not replay or not Path(replay).exists():
        return None
    from melee_llm.web.games import game_id
    return game_id(Path(replay))


def _samples(rec: dict, port: int, n: int = 6) -> list[dict]:
    """A few decisions spread over the game, as the model saw and answered them."""
    from melee_llm.web.logs import read
    s = (rec.get("sides") or {}).get(str(port))
    if not s or not s.get("log"):
        return []
    decs = [r for r in read(Path(s["log"])) if r.get("type") == "decision"]
    if not decs:
        return []
    step = max(1, len(decs) // n)
    out = []
    for r in decs[step // 2::step][:n]:
        out.append({"frame": r.get("frame"), "state": (r.get("obs_text") or r.get("state") or "")[:900],
                    "action": r.get("action") or r.get("command"), "phrase": r.get("phrase"),
                    "reason": r.get("reason") or r.get("why"), "latency_s": r.get("latency_s"),
                    "latency_frames": r.get("latency_frames"), "error": r.get("error") or None})
    return out


def entrant(eid: str) -> dict | None:
    ents = by_id()
    e = ents.get(eid)
    if not e:
        return None
    results = read_results(DATA / "results.jsonl")
    imp, _ = _imports()
    st = standings()
    row = next((r for r in st["board"]["players"] if r["id"] == eid), None)
    mine = [g for g in results + imp if eid in (g["p1"], g["p2"])]
    mine.sort(key=lambda g: g.get("ts") or 0, reverse=True)
    games = []
    for g in mine[:60]:
        me = 1 if g["p1"] == eid else 2
        opp = g[f"p{3 - me}"]
        games.append({"id": g["id"], "ts": g.get("ts"), "opponent": opp,
                      "opponent_label": ents[opp].label if opp in ents else opp, "port": me, "stage": g.get("stage"),
                      "mode": g.get("mode"), "status": g.get("status"), "imported": bool(g.get("imported")),
                      "source": g.get("source", "bench"), "result": None if g.get("status") != "ok" else
                      {me: "win", 3 - me: "loss"}.get(ratings.winner(g), "draw"),
                      "stocks": g.get("stocks"), "frames": g.get("frames"), "fps": g.get("fps"),
                      "tokens": sum(s.get("prompt_tokens", 0) + s.get("completion_tokens", 0)
                                    for p, s in (g.get("sides") or {}).items() if p == str(me)),
                      "error": g.get("error"), "game_id": _game_id(g.get("replay"))})
    samples, sample_game = [], None
    for g in mine:
        if g.get("imported") or g.get("status") != "ok":
            continue
        samples = _samples(g, 1 if g["p1"] == eid else 2)
        if samples:
            sample_game = {"id": g["id"], "game_id": _game_id(g.get("replay")),
                           "opponent": ents[g["p2" if g["p1"] == eid else "p1"]].label}
            break
    return {"entrant": e.view(), "row": row, "spend": st.get("spend", {}).get(eid),
            "labels": {k: v.label for k, v in ents.items()}, "games": games, "total_games": len(mine),
            "samples": samples, "sample_game": sample_game}
