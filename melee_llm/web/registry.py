"""Read the match registry (data/matches/*.json, written by every runner.play(); see melee_llm.matches).

Files are re-read only when their mtime changes. A file still saying it runs whose process is gone is
rewritten as "crashed". Ended matches stay listed for KEEP_S seconds (at most KEEP_N of them), then go.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from melee_llm.matches import DIR
from melee_llm.web import games
from melee_llm.web.specs import char_name, kind_of, label, stage_name

ENDED = ("finished", "failed", "crashed")
KEEP_S, KEEP_N = 3 * 3600, 24

_cache: dict[str, tuple[int, dict]] = {}
_decisions: dict[str, tuple[int, dict | None]] = {}


def _alive(pid: int) -> bool:
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            return b"python" in f.read()
    except OSError:
        return False


def _last_decision(path: str) -> dict | None:
    """Latest decision record of a decision log, read from its tail (cached by file size)."""
    try:
        size = os.path.getsize(path)
    except OSError:
        return None
    hit = _decisions.get(path)
    if hit and hit[0] == size:
        return hit[1]
    found = None
    try:
        with open(path, "rb") as f:
            f.seek(max(0, size - 16384))
            for line in reversed(f.read().decode(errors="replace").splitlines()):
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if rec.get("type") == "decision":
                    found = {k: rec.get(k) for k in ("frame", "ts", "action", "reason", "command", "why", "changed",
                                                     "latency_s", "error") if rec.get(k) is not None}
                    if rec.get("decision") and "action" not in found:
                        found["action"] = rec["decision"].get("action")
                    break
    except OSError:
        pass
    _decisions[path] = (size, found)
    return found


def _view(m: dict) -> dict:
    for p, pl in (m.get("players") or {}).items():
        spec = pl.get("spec")
        pl["label"] = label(spec) if spec else f"CPU {pl['cpu_level']}" if pl.get("cpu_level") else pl.get("name") or f"P{p}"
        pl["kind"] = kind_of(spec) if spec else ("cpu" if pl.get("cpu_level") else "bot")
        pl["char_name"] = char_name(pl.get("character") or "")
    m["stage_name"] = stage_name(m.get("stage") or "")
    m["speed"] = round(m["fps"] / 60, 1) if m.get("fps") else None
    m["stale"] = m.get("phase") == "in_game" and time.time() - (m.get("updated") or 0) > 600
    m["decisions"] = [{"port": lg["port"], "kind": lg["kind"], **d} for lg in m.get("logs") or []
                      if (d := _last_decision(lg["path"]))]
    replay = m.get("replay") or (m.get("results") or [{}])[-1].get("replay")
    m["game_id"] = games.game_id(Path(replay)) if replay and m.get("phase") in ENDED + ("between",) else None
    return m


_snap: tuple[float, list[dict]] = (0.0, [])


def snapshot(max_age: float = 0.08) -> list[dict]:
    """scan(), shared by every client polling within `max_age` seconds."""
    global _snap
    if time.monotonic() - _snap[0] > max_age:
        _snap = (time.monotonic(), scan())
    return _snap[1]


def scan() -> list[dict]:
    """Every registered match, newest first, with a `ring` of recent frames (only for running ones)."""
    now, out, ended = time.time(), [], []
    try:
        names = [n for n in os.listdir(DIR) if n.endswith(".json") and not n.startswith(".")]
    except OSError:
        names = []
    for name in names:
        path = DIR / name
        try:
            mtime = path.stat().st_mtime_ns
        except OSError:
            continue
        hit = _cache.get(name)
        if hit and hit[0] == mtime:
            m = hit[1]
        else:
            try:
                m = json.loads(path.read_text())
            except (OSError, ValueError):
                continue  # replaced while reading: next scan
            _cache[name] = (mtime, m)
        if m.get("phase") not in ENDED and not _alive(m.get("pid", 0)):
            m = {**m, "phase": "crashed", "finished": m.get("updated"), "error": m.get("error") or "process died"}
            _write(path, m)
            _cache[name] = (path.stat().st_mtime_ns, m)
        if m.get("phase") in ENDED:
            ended.append((m.get("finished") or m.get("updated") or 0, name, m))
        else:
            out.append(m)
    ended.sort(reverse=True)
    for i, (t, name, m) in enumerate(ended):
        if i >= KEEP_N or now - t > KEEP_S:
            try:
                (DIR / name).unlink()
            except OSError:
                pass
            _cache.pop(name, None)
        else:
            out.append(m)
    for name in set(_cache) - set(names):
        _cache.pop(name, None)
    out.sort(key=lambda m: (m.get("phase") in ENDED, -(m.get("started") or 0)))
    return [_view({**m, "players": {p: dict(pl) for p, pl in (m.get("players") or {}).items()}}) for m in out]


def _write(path: Path, m: dict) -> None:
    tmp = path.with_name(f".{path.name}.srv.tmp")
    try:
        tmp.write_text(json.dumps(m, separators=(",", ":")))
        tmp.replace(path)
    except OSError:
        pass
