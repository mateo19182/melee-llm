"""What the live slot is playing: data/live.json (read by the web server) and the stream overlay strip.

The process that owns display :99 (a job or an arena game) creates a `LiveReporter` and passes
`reporter.observer(agents)` to `runner.play`. Writes are atomic and throttled to ~5 per second.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from melee_llm.web.paths import LIVE
from melee_llm.web.specs import char_name, kind_of, label, stage_name

OVERLAY = Path("/tmp/melee-arena/overlay.txt")  # drawn under the video by scripts/stream.sh


def write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(text)
    tmp.replace(path)  # ffmpeg's drawtext and the server never read a half-written file


def write_overlay(text: str) -> None:
    write_atomic(OVERLAY, text)


def write_status(status: dict) -> None:
    write_atomic(LIVE, json.dumps({**status, "updated": round(time.time(), 3)}, default=str))


def read_status() -> dict:
    try:
        return json.loads(LIVE.read_text())
    except (OSError, ValueError):
        return {"source": "idle", "phase": "idle", "updated": 0}


def idle(next_up: str = "") -> None:
    write_status({"source": "idle", "phase": "idle", "next": next_up})
    write_overlay(next_up)


def _plain(d: dict) -> dict:
    return {k: v for k, v in d.items() if isinstance(v, (str, int, float, bool, type(None)))}


class LiveReporter:
    def __init__(self, source: str, p1: str, p2: str, char1: str, char2: str, stage: str, mode: str, games: int = 1,
                 job_id: int | None = None, overlay: str | None = None, extra: dict | None = None):
        self.status = {
            "source": source, "job_id": job_id, "phase": "starting", "mode": mode, "stage": stage,
            "stage_name": stage_name(stage), "game": 0, "games": games, "started": round(time.time(), 3),
            "players": {str(p): {"spec": s, "label": label(s), "kind": kind_of(s), "character": c, "char_name": char_name(c)}
                        for p, s, c in ((1, p1, char1), (2, p2, char2))},
            "frame": None, "stocks": {}, "percent": {}, "logs": [], "steer": {}, "replay": None, "results": [],
            **(extra or {})}
        self.overlay = overlay
        self.last = 0.0
        self._overlay()
        write_status(self.status)

    def _overlay(self) -> None:
        if self.overlay is not None:
            return write_overlay(self.overlay)
        s, pl = self.status, self.status["players"]
        tag = f"job #{s['job_id']}" if s["job_id"] else s["source"]
        games = f"   |   game {s['game'] + 1}/{s['games']}" if s["games"] > 1 else ""
        write_overlay(f"{pl['1']['label']} ({pl['1']['char_name']})  vs  {pl['2']['label']} ({pl['2']['char_name']})"
                      f"   |   {s['stage_name']}   |   {tag}{games}")

    def observer(self, agents: dict):
        def on(event: str, info: dict) -> None:
            s = self.status
            if event == "game_start":
                s.update(phase="in_game", game=info["game"], replay=str(info["replay"]) if info["replay"] else None,
                         logs=[], steer={})
                self._overlay()
                self._sample(info["gs"], agents)
            elif event == "frame":
                if time.time() - self.last >= 0.2:
                    self._sample(info["gs"], agents)
            elif event == "game_end":
                r = info["result"]
                s["results"].append({"winner": r.winner, "stocks": {str(k): int(v) for k, v in r.stocks.items()},
                                     "percent": {str(k): round(float(v), 1) for k, v in r.percent.items()},
                                     "frames": r.frames, "replay": r.replay})
                s.update(phase="between", stocks=s["results"][-1]["stocks"], percent=s["results"][-1]["percent"],
                         replay=r.replay)
                write_status(s)
        return on

    def _sample(self, gs, agents: dict) -> None:
        s = self.status
        s["frame"] = int(gs.frame)
        for p in agents:
            if p in gs.players:
                s["stocks"][str(p)] = int(gs.players[p].stock)
                s["percent"][str(p)] = round(float(gs.players[p].percent), 1)
        logs = []
        for p, a in agents.items():
            log = getattr(a, "log", None)
            path = getattr(log, "path", None)
            if path is not None and hasattr(log, "suffix"):
                logs.append({"port": p, "kind": log.suffix, "path": str(path)})
            body = getattr(a, "body", a)
            steer = getattr(body, "applied_steer", None)
            if steer:
                st = _plain(steer)
                if isinstance(steer.get("reply"), dict):
                    st["router"] = _plain(steer["reply"])
                if hasattr(a, "current"):
                    st["coach_command"] = a.current
                s["steer"][str(p)] = st
        if logs:
            s["logs"] = logs
        self.last = time.time()
        write_status(s)

    def done(self, error: str | None = None) -> None:
        self.status.update(phase="finished", error=error)
        write_status(self.status)
