"""Registry of running matches: every runner.play() publishes data/matches/<pid>-<port>-<start>.json.

The file holds who plays (source, label, players, characters, stage, mode), the score, the speed in game
frames per wall second, decision-log paths and a ring of recent compact frames for the web UI's live 2D
view. It is rewritten atomically at most WRITE_HZ times per wall second; per-frame work is one sample
(skipped when the game runs faster than SAMPLE_FPS). On exit the file says "finished" or "failed"; a
file whose pid is dead while it still says running is a crashed match (the web server marks it).

MELEE_MATCHES=0 turns publishing off (benchmarks); MELEE_MATCHES_DIR moves the directory.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from pathlib import Path

from melee_llm.paths import BOTWRITER, DATA, LIVE_DISPLAY, LIVE_PORT

DIR = Path(os.environ.get("MELEE_MATCHES_DIR", DATA / "matches"))
ENABLED = os.environ.get("MELEE_MATCHES", "1") != "0"
WRITE_HZ = 15
SAMPLE_FPS = 60  # at most this many samples per wall second (fast mode runs several times real time)
RING = 45  # samples kept in the file: enough for a client polling at a few Hz to never see gaps

_SHIELD = {178, 179, 181, 182}  # SHIELD_START, SHIELD, SHIELD_STUN, SHIELD_REFLECT


def _guess_source(replay_dir: Path | None) -> tuple[str, str]:
    script = Path(sys.argv[0]).name if sys.argv and sys.argv[0] else "python"
    if script in ("-m", "-c", ""):
        script = "python"
    rd = str(replay_dir or "")
    bw = str(BOTWRITER)
    if rd.startswith(bw):
        parts = Path(rd).relative_to(bw).parts
        kind = parts[0].rstrip("s") if parts else "botwriter"  # ladders → ladder, sessions → session, rounds → round
        return "botwriter", f"{kind} {parts[1]}" if len(parts) > 1 else kind
    if "coach_pilot" in script:
        return "coach", f"coach pilot {Path(rd).name}" if rd else "coach pilot"
    if "practice" in " ".join(sys.argv) or "botwriter" in " ".join(sys.argv):
        return "botwriter", script
    return "script", script


def _plain(d: dict) -> dict:
    return {k: v for k, v in d.items() if isinstance(v, (str, int, float, bool, type(None)))}


class MatchPublisher:
    """Created by runner.play(); `frame(gs)` is called on every in-game frame and must stay cheap."""

    def __init__(self, agents: dict, stage, mode: str, games: int, slippi_port: int, replay_dir: Path | None,
                 meta: dict | None = None):
        meta = dict(meta or {})
        self.t0 = time.time()
        self.path = DIR / f"{os.getpid()}-{slippi_port}-{int(self.t0 * 1000)}.json"
        self.agents = agents
        source, label = _guess_source(replay_dir)
        display = os.environ.get("DISPLAY", "")
        specs = meta.pop("specs", {}) or {}
        self.status = {
            "id": self.path.stem, "pid": os.getpid(), "port": slippi_port, "source": meta.pop("source", source),
            "label": meta.pop("label", label), "mode": mode, "stage": getattr(stage, "name", str(stage)),
            "games": games, "game": 0, "phase": "starting", "started": round(self.t0, 3), "game_started": None,
            "live_slot": mode != "fast" and display == LIVE_DISPLAY and slippi_port == LIVE_PORT,
            "argv": " ".join(sys.argv)[:300], "replay_dir": str(replay_dir) if replay_dir else None,
            "players": {str(p): {"name": a.name, "spec": specs.get(p) or specs.get(str(p)), "character": a.character.name,
                                 "cpu_level": a.cpu_level} for p, a in agents.items()},
            "frame": None, "fps": None, "stocks": {}, "percent": {}, "logs": [], "steer": {}, "replay": None, "results": [],
            "ring": [], **meta}
        self.ring: list = []
        self.ports = sorted(agents)
        self.last_write = 0.0
        self.last_sample_t = 0.0
        self.rate_t, self.rate_n = 0.0, 0
        self.cost_s, self.cost_n = 0.0, 0  # time spent in frame(): reported as overhead_us (mean per frame)
        self._pending, self._thread, self._wake, self._lock = None, None, threading.Event(), threading.Lock()
        self.commentary = None  # melee_llm.commentary.Commentary, live slot only
        self.write()

    # ------------------------------------------------------------------ events from play()

    def game_start(self, game: int, gs, replay) -> None:
        s = self.status
        s.update(phase="in_game", game=game, game_started=round(time.time(), 3), replay=str(replay) if replay else None,
                 fps=None, steer={})
        self.ring = []
        self.rate_t, self.rate_n = time.monotonic(), 0
        for p in self.ports:
            if p in gs.players:
                s["players"][str(p)]["character"] = gs.players[p].character.name
        if s["live_slot"]:
            self._end_commentary()
            try:
                from melee_llm.commentary import for_match
                self.commentary = for_match(s, replay)
            except Exception as e:  # noqa: BLE001 - commentary is a nicety: never break a game over it
                print(f"commentary disabled: {type(e).__name__}: {e}", file=sys.stderr)
        s["logs"] = self._logs()
        self._sample(gs)
        self.write()

    def frame(self, gs) -> None:
        t = time.perf_counter()
        now = time.monotonic()
        self.rate_n += 1
        if self.commentary:
            self.commentary.update(gs)
        if now - self.last_sample_t >= 1 / SAMPLE_FPS:
            self.last_sample_t = now
            self._sample(gs)
        if now - self.last_write >= 1 / WRITE_HZ:
            self._flush(gs, now)
        self.cost_s += time.perf_counter() - t
        self.cost_n += 1

    def game_end(self, game: int, result) -> None:
        r = {"winner": result.winner, "stocks": {str(k): int(v) for k, v in result.stocks.items()},
             "percent": {str(k): round(float(v), 1) for k, v in result.percent.items()}, "frames": result.frames,
             "seconds": round(result.seconds, 1), "replay": result.replay}
        s = self.status
        s["results"].append(r)
        s.update(phase="between", stocks=r["stocks"], percent=r["percent"], replay=result.replay)
        self.write()
        if self.commentary:
            w = str(result.winner) if result.winner else None
            if w:
                o = next(p for p in s["players"] if p != w)
                self._end_commentary(f"Game! {self.commentary.names[int(w)]} wins, {r['stocks'].get(w, 0)} stocks to {r['stocks'].get(o, 0)}")
            else:
                self._end_commentary("Game! It ends in a draw")

    def close(self, error: BaseException | None = None) -> None:
        s = self.status
        if error is not None and not (isinstance(error, SystemExit) and error.code in (0, None)):
            s["error"] = f"{type(error).__name__}: {error}"[:500]
        s.update(phase="failed" if s.get("error") and len(s["results"]) < s["games"] else "finished",
                 finished=round(time.time(), 3))
        self.write()
        if self.commentary:  # let the last line about the result land before the process exits
            self._end_commentary()
            self.commentary.join()

    # ------------------------------------------------------------------ internals

    def _sample(self, gs) -> None:
        row = [int(gs.frame)]
        for p in self.ports:
            ps = gs.players.get(p)
            if ps is None:
                row.append(None)
                continue
            a = ps.action
            av = a.value if hasattr(a, "value") else -1
            flags = (1 if ps.invulnerable else 0) | (2 if ps.hitstun_frames_left > 0 else 0) | (4 if ps.on_ground else 0) \
                | (8 if av in _SHIELD else 0) | (16 if ps.off_stage else 0)
            pos = ps.position
            row.append([round(float(pos.x), 1), round(float(pos.y), 1), 1 if ps.facing else -1, av, int(ps.action_frame),
                        int(ps.percent), int(ps.stock), int(ps.shield_strength), flags, ps.character.value])
        self.ring.append(row)
        if len(self.ring) > RING:
            del self.ring[0]

    def _flush(self, gs, now: float) -> None:
        s = self.status
        s["frame"] = int(gs.frame)
        dt = now - self.rate_t
        if dt >= 1.0:  # game frames per wall second over the last second or so
            fps = self.rate_n / dt
            s["fps"] = round(fps if s["fps"] is None else 0.5 * s["fps"] + 0.5 * fps, 1)
            self.rate_t, self.rate_n = now, 0
        for p in self.ports:
            ps = gs.players.get(p)
            if ps is not None:
                s["stocks"][str(p)] = int(ps.stock)
                s["percent"][str(p)] = round(float(ps.percent), 1)
        if not s["logs"]:
            s["logs"] = self._logs()
        steer = self._steer()
        if steer:
            s["steer"] = {**s["steer"], **steer}
        if self.cost_n:
            s["overhead_us"] = round(self.cost_s / self.cost_n * 1e6, 1)
        self.last_write = now
        # serialising and writing (~0.1-0.3 ms) happen on a thread, mostly while the game loop waits on Dolphin
        self._pending = {**s, "ring": list(self.ring), "stocks": dict(s["stocks"]), "percent": dict(s["percent"]),
                         "updated": round(time.time(), 3)}
        if self._thread is None:
            self._thread = threading.Thread(target=self._writer, name="match-registry", daemon=True)
            self._thread.start()
        self._wake.set()

    def _writer(self) -> None:
        while True:
            self._wake.wait()
            self._wake.clear()
            with self._lock:
                data, self._pending = self._pending, None
                if data is not None:
                    self._dump(data)

    def _end_commentary(self, text: str | None = None) -> None:
        if self.commentary:
            self.commentary.end(text)

    def _logs(self) -> list[dict]:
        out = []
        if self.commentary:
            out.append({"port": 0, "kind": "commentary", "path": str(self.commentary.path)})
        for p, a in self.agents.items():
            log = getattr(a, "log", None)
            path = getattr(log, "path", None)
            if path is not None and hasattr(log, "suffix"):
                out.append({"port": p, "kind": log.suffix, "path": str(path)})
        return out

    def _steer(self) -> dict:
        """What each steerable bot is currently told to do (and by which coach command), for the Live page."""
        out = {}
        for p, a in self.agents.items():
            steer = getattr(getattr(a, "body", a), "applied_steer", None)
            if steer:
                st = _plain(steer)
                if isinstance(steer.get("reply"), dict):
                    st["router"] = _plain(steer["reply"])
                if hasattr(a, "current"):
                    st["coach_command"] = a.current
                out[str(p)] = st
        return out

    def write(self) -> None:
        """Synchronous write (start, game boundaries, exit): drops any older pending threaded write."""
        self.last_write = time.monotonic()
        with self._lock:
            self._pending = None
            self._dump({**self.status, "ring": self.ring, "updated": round(time.time(), 3)})

    def _dump(self, data: dict) -> None:
        try:
            DIR.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_name(f".{self.path.name}.tmp")
            tmp.write_text(json.dumps(data, separators=(",", ":"), default=str))
            tmp.replace(self.path)
        except OSError:
            pass  # the registry is best-effort: never break a game over it


def publisher(agents, stage, mode, games, slippi_port, replay_dir, meta) -> MatchPublisher | None:
    if not ENABLED:
        return None
    try:
        return MatchPublisher(agents, stage, mode, games, slippi_port, replay_dir, meta)
    except Exception as e:  # noqa: BLE001 - best-effort
        print(f"match registry disabled: {type(e).__name__}: {e}", file=sys.stderr)
        return None
