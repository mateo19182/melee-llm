"""Read-only views over every result source: one game index (all .slp files, enriched by whichever results
file knows them), arena standings, coach pilot summaries, bot-writer sessions and ladder boards."""
from __future__ import annotations

import hashlib
import json
import statistics
import threading
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from melee_llm.web import jobs, logs
from melee_llm.web.paths import ARENA, BOTWRITER, ROOT
from melee_llm.web.slp import header
from melee_llm.web.specs import char_name, label, stage_name

REPLAY_ROOTS = [ROOT / "replays", BOTWRITER / "ladders"]


def game_id(path: Path) -> str:
    return hashlib.sha1(str(path.resolve()).encode()).hexdigest()[:12]


def _jsonl(path: Path) -> list[dict]:
    try:
        return [json.loads(ln) for ln in path.read_text().splitlines() if ln.strip()]
    except (OSError, ValueError):
        return []


def _fmt_time(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")


def _ladder_label(name: str) -> str:
    if name.startswith("agent:melee_llm.bots:"):
        parts = name.split(":")[2:]
        return " ".join(parts)
    return label(name)


def _source_from_path(path: Path) -> str:
    for base, kind in ((BOTWRITER / "ladders", "ladder"), (ROOT / "replays/coach-pilot", "coach-pilot"),
                       (ROOT / "replays/jobs", "job")):
        if path.is_relative_to(base.resolve()):
            return f"{kind}:{path.relative_to(base.resolve()).parts[0]}"
    return "replays"


class Index:
    """All games, rebuilt at most every `ttl` seconds; .slp headers are cached by (mtime, size)."""

    def __init__(self, ttl: float = 15.0):
        self.ttl, self.built, self.lock = ttl, 0.0, threading.Lock()
        self.games: list[dict] = []
        self.by_id: dict[str, dict] = {}
        self.headers: dict[Path, tuple[tuple, dict | None]] = {}

    def _header(self, path: Path) -> dict | None:
        try:
            st = path.stat()
        except OSError:
            return None
        key = (st.st_mtime, st.st_size)
        hit = self.headers.get(path)
        if hit and hit[0] == key:
            return hit[1]
        h = header(path)
        if h is not None:
            h["mtime"] = st.st_mtime
        self.headers[path] = (key, h)
        return h

    def get(self) -> list[dict]:
        with self.lock:
            if time.time() - self.built > self.ttl:
                self._build()
                self.built = time.time()
            return self.games

    def find(self, gid: str) -> dict | None:
        self.get()
        return self.by_id.get(gid)

    def _build(self) -> None:
        known: dict[Path, dict] = {}

        def add(replay, **rec):
            if not replay:
                return
            path = Path(replay)
            path = (path if path.is_absolute() else ROOT / path).resolve()
            known[path] = rec

        for j in jobs.listing(limit=1000):
            for r in j["results"]:
                add(r.get("replay"), source=f"job:{j['id']}", source_label=f"Job #{j['id']}", p1=j["p1"], p2=j["p2"],
                    char1=j["char1"], char2=j["char2"], stage=j["stage"], mode=j["mode"], winner=r.get("winner"),
                    stocks=r.get("stocks"), percent=r.get("percent"), frames=r.get("frames"), time=r.get("time"),
                    job_id=j["id"])
        for r in _jsonl(ARENA / "results.jsonl"):
            add(r.get("replay"), source="arena", source_label="Arena", p1=r["p1"], p2=r["p2"], char1=r["char1"],
                char2=r["char2"], stage=r["stage"], mode="lockstep", winner=r["winner"], stocks=r["stocks"],
                percent=r["percent"], frames=r["frames"], time=r["time"].replace("T", " "))
        for f in sorted((ROOT / "replays/coach-pilot").glob("*/results.jsonl")):
            for r in _jsonl(f):
                add(r.get("replay"), source=f"coach-pilot:{f.parent.name}", source_label=f"Coach pilot {f.parent.name}",
                    p1=r["p1"], p2=r["p2"], char1=r["char1"], char2=r["char2"], stage=r["stage"], mode=r.get("mode"),
                    winner=r.get("winner"), stocks=r.get("stocks"), percent=r.get("percent"), frames=r.get("frames"))
        for f in sorted((BOTWRITER / "ladders").glob("*/games.jsonl")):
            for r in _jsonl(f):
                if "error" in r or not r.get("replay"):
                    continue
                ports = {"a": r["a_port"], "b": 3 - r["a_port"]}
                names = {ports["a"]: r["a"], ports["b"]: r["b"]}
                add(r["replay"], source=f"ladder:{f.parent.name}", source_label=f"Ladder {f.parent.name}",
                    p1=names[1], p2=names[2], label1=_ladder_label(names[1]), label2=_ladder_label(names[2]),
                    stage=r["stage"], mode="fast", winner=ports.get(r.get("winner")),
                    stocks={str(ports[k]): v for k, v in (r.get("stocks") or {}).items()},
                    percent={str(ports[k]): v for k, v in (r.get("percent") or {}).items()}, frames=r.get("frames"),
                    time=_fmt_time(r["ts"]) if r.get("ts") else None)
        games = []
        for root in REPLAY_ROOTS:
            for path in root.rglob("*.slp"):
                path = path.resolve()
                h = self._header(path) or {}
                rec = dict(known.get(path) or {})
                hp = h.get("players", {})
                if not rec:
                    src = _source_from_path(path)
                    rec = {"source": src, "source_label": src.replace(":", " "), "stage": h.get("stage"),
                           "p1": "cpu" if hp.get(1, {}).get("type") == "cpu" else "?",
                           "p2": "cpu" if hp.get(2, {}).get("type") == "cpu" else "?"}
                for p in (1, 2):
                    rec.setdefault(f"char{p}", hp.get(p, {}).get("character"))
                    rec.setdefault(f"label{p}", label(rec[f"p{p}"]) if rec.get(f"p{p}") not in (None, "?", "cpu")
                                   else {"cpu": "CPU", "?": "Player"}.get(rec.get(f"p{p}"), "?"))
                    rec[f"char{p}_name"] = char_name(rec[f"char{p}"]) if rec.get(f"char{p}") else "?"
                if not rec.get("time"):
                    ts = h.get("mtime") or path.stat().st_mtime
                    if h.get("start_at"):
                        try:
                            ts = datetime.fromisoformat(h["start_at"].replace("Z", "+00:00")).timestamp()
                        except ValueError:
                            pass
                    rec["time"] = _fmt_time(ts)
                rec["stage"] = rec.get("stage") or h.get("stage")
                rec["stage_name"] = stage_name(rec["stage"]) if rec.get("stage") else "?"
                rec.setdefault("frames", h.get("last_frame"))
                lg = logs.logs_for(path)
                rec.update(id=game_id(path), path=str(path), name=path.name,
                           logs=[{"name": p.name, "kind": logs.log_kind(p)} for p in lg])
                games.append(rec)
        games.sort(key=lambda g: g["time"] or "", reverse=True)
        self.games, self.by_id = games, {g["id"]: g for g in games}


INDEX = Index()


def query(q: str = "", source: str = "", mode: str = "", char: str = "", stage: str = "", since: str = "",
          until: str = "", logs_only: bool = False, limit: int = 100, offset: int = 0) -> dict:
    out = []
    ql = q.lower().strip()
    for g in INDEX.get():
        if ql and not any(ql in str(g.get(k) or "").lower() for k in ("p1", "p2", "label1", "label2", "name")):
            continue
        if source and not (g["source"] == source or g["source"].startswith(source + ":")):
            continue
        if mode and g.get("mode") != mode:
            continue
        if char and char not in (g.get("char1"), g.get("char2")):
            continue
        if stage and g.get("stage") != stage:
            continue
        if since and (g["time"] or "") < since:
            continue
        if until and (g["time"] or "")[:len(until)] > until:
            continue
        if logs_only and not g["logs"]:
            continue
        out.append(g)
    sources = sorted({g["source"].split(":")[0] for g in INDEX.games})
    return {"total": len(out), "games": out[offset:offset + limit], "sources": sources}


def game_detail(gid: str) -> dict | None:
    g = INDEX.find(gid)
    if g is None:
        return None
    path = Path(g["path"])
    out = []
    for p in logs.logs_for(path):
        recs = logs.read(p)
        port = next((r.get("port") for r in recs if r.get("type") == "game_start"), None)
        out.append({"name": p.name, "kind": logs.log_kind(p), "port": port, "records": [logs.slim(r) for r in recs]})
    return {**g, "decision_logs": out, "tokens": logs.tokens(logs.logs_for(path))}


# --------------------------------------------------------------------------- dashboards

def arena() -> dict:
    try:
        standings = json.loads((ARENA / "standings.json").read_text())
    except (OSError, ValueError):
        standings = {"table": [], "games": 0, "updated": "never"}
    by_path = {Path(g["path"]): g["id"] for g in INDEX.get() if g["source"] == "arena"}
    recent = []
    for r in reversed(_jsonl(ARENA / "results.jsonl")[-40:]):
        r = dict(r)
        r["id"] = by_path.get(Path(r["replay"]).resolve()) if r.get("replay") else None
        r["label1"], r["label2"] = label(r["p1"]), label(r["p2"])
        r["char1_name"], r["char2_name"], r["stage_name"] = char_name(r["char1"]), char_name(r["char2"]), stage_name(r["stage"])
        recent.append(r)
    # head-to-head win rates
    h2h = defaultdict(lambda: [0, 0])
    for r in _jsonl(ARENA / "results.jsonl"):
        for me, opp, port in ((r["p1"], r["p2"], 1), (r["p2"], r["p1"], 2)):
            cell = h2h[f"{me}|{opp}"]
            cell[0] += 1 if r["winner"] == port else 0.5 if r["winner"] is None else 0
            cell[1] += 1
    return {**standings, "recent": recent, "h2h": {k: {"score": v[0], "n": v[1]} for k, v in h2h.items()}}


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return round(statistics.fmean(xs), 3) if xs else None


def coach_pilots() -> list[dict]:
    by_path = {Path(g["path"]): g["id"] for g in INDEX.get()}
    out = []
    for f in sorted((ROOT / "replays/coach-pilot").glob("*/results.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True):
        rows = _jsonl(f)
        groups = defaultdict(list)
        for r in rows:
            groups[(r["cond"], r["p2"])].append(r)
        conds = []
        for (cond, p2), rs in sorted(groups.items()):
            coach = [r["coach"] for r in rs if r.get("coach")]
            conds.append({
                "cond": cond, "p2": p2, "label": label(cond), "opp": label(p2), "n": len(rs),
                "wins": sum(r["winner"] == 1 for r in rs), "losses": sum(r["winner"] == 2 for r in rs),
                "stock_diff": _mean([r["stocks"]["1"] - r["stocks"]["2"] for r in rs]),
                "pct_diff": _mean([r["percent"]["2"] - r["percent"]["1"] for r in rs]),
                "frames": _mean([r["frames"] for r in rs]),
                "mean_dx": _mean([r.get("behaviour", {}).get("mean_dx") for r in rs]),
                "laser": _mean([r.get("behaviour", {}).get("frac_laser") for r in rs]),
                "coach": {"decisions": sum(c.get("decisions", 0) for c in coach), "changes": sum(c.get("changes", 0) for c in coach),
                          "errors": sum(c.get("errors", 0) for c in coach),
                          "prompt_tokens": sum(c.get("prompt_tokens", 0) for c in coach),
                          "completion_tokens": sum(c.get("completion_tokens", 0) for c in coach),
                          "mean_latency_s": _mean([c.get("mean_latency_s") for c in coach])} if coach else None,
                "games": [by_path.get((ROOT / r["replay"]).resolve()) for r in rs if r.get("replay")],
            })
        out.append({"name": f.parent.name, "updated": _fmt_time(f.stat().st_mtime), "games": len(rows), "conditions": conds})
    return out


def botwriter_sessions() -> list[dict]:
    out = []
    for meta in sorted((BOTWRITER / "sessions").glob("*/meta.json"), reverse=True):
        try:
            m = json.loads(meta.read_text())
        except (OSError, ValueError):
            continue
        out.append({k: m.get(k) for k in ("id", "name", "harness", "model", "effort", "minutes", "budget_usd", "cost_usd",
                                          "wall_s", "num_turns", "exit", "bot_lines", "started", "result_subtype")}
                   | {"valid": (m.get("validation") or {}).get("ok"),
                      "flagged": (m.get("smashbot_similarity") or {}).get("flagged"),
                      "started_at": _fmt_time(m["started"]) if m.get("started") else None,
                      "id": m.get("id") or meta.parent.name})
    return out


def botwriter_session(sid: str) -> dict | None:
    d = BOTWRITER / "sessions" / sid
    if "/" in sid or ".." in sid or not (d / "meta.json").exists():
        return None
    meta = json.loads((d / "meta.json").read_text())
    bot = d / "final/bot.py"
    files = sorted(str(p.relative_to(d)) for p in d.rglob("*") if p.is_file() and "sandbox" not in p.name)
    return {"meta": meta, "source": bot.read_text() if bot.exists() else None, "files": files}


_boards: dict[str, tuple[float, dict]] = {}


def ladders() -> list[dict]:
    from melee_llm.botwriter import ladder  # read-only use of the ladder's own scoring

    out = []
    for cfg_path in sorted((BOTWRITER / "ladders").glob("*.json")):
        try:
            cfg = ladder.load_config(cfg_path)
        except Exception as e:  # a config being edited
            out.append({"name": cfg_path.stem, "error": str(e)})
            continue
        games = Path(cfg["out"]) / "games.jsonl"
        mtime = games.stat().st_mtime if games.exists() else 0
        hit = _boards.get(cfg_path.stem)
        if not hit or hit[0] != mtime:
            board = ladder.leaderboard(cfg, ladder.read_games(Path(cfg["out"])))
            board["jobs_total"] = sum(j["games"] for j in ladder.make_jobs(cfg))
            board["updated_games"] = _fmt_time(mtime) if mtime else None
            _boards[cfg_path.stem] = hit = (mtime, board)
        out.append({"name": cfg_path.stem, "board": hit[1], "entrants": cfg["entrants"]})
    return out
