"""The overnight fill: pick the most informative pairing per token, run it in an isolated child, repeat.

Active sampling. Per track, the current fit (bench + imported games) gives each entrant's strength and a Laplace
covariance. Games already running are added to the precision as if played (so a pairing is not started six
times at once). For a candidate pairing with win probability p, one more game adds Fisher information
w = p(1-p) along (e_a - e_b); by Sherman-Morrison the anchored variance of entrant k drops by
w·(c_k' Σ d)² / (1 + w·d' Σ d). The value of a pairing is the sum of those drops over entrants whose 95% CI is
still wider than the target (others weigh 2%), divided by its expected token cost plus a fixed per-game
overhead. Pairings that do not fit the free resources (mode slots, provider slots, GPU, budget) are skipped.

Isolation follows llm_arena: each game is `python -m melee_llm.bench one` in its own process group with its
own Slippi port (51920-51999) and replay dir; a wall timeout kills the group, Dolphin included.
"""
from __future__ import annotations

import json
import os
import random
import signal
import subprocess
import sys
import threading
import time
from collections import Counter, deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import numpy as np

from melee_llm.bench import imports, ratings
from melee_llm.bench.entrants import Entrant, by_id, game_mode, game_track, tracks_of
from melee_llm.bench.game import status_of
from melee_llm.llm_arena.ratings import ELO
from melee_llm.runner import ROOT

DATA = ROOT / "data/bench"
GAMES = ROOT / "replays/bench"
PORTS = range(51920, 52000)
STAGES = ("BATTLEFIELD", "FINAL_DESTINATION")
# Prior token cost per game for a side, until the entrant has its own average (full games, Fox ditto).
TOKEN_PRIOR = {"llm_paused": 900_000, "llm_live": 350_000, "coach": 80_000, "coach_jev": 0, "jev_live": 0,
               "jev_paused": 0}
OVERHEAD = 60_000  # token-equivalent of one game's machine time: keeps free games from looking infinitely cheap
TIMEOUT = {"fast": 25 * 60, "realtime": 25 * 60, "untimed_llm": 3 * 3600}
LOAD_COST = {"fast": 2.0, "realtime": 1.5, "untimed_llm": 0.3}  # rough load each kind adds
LOAD_SLACK_IDLE = 4.0  # untimed LLM games (Dolphin blocked on the API) may start up to load_cap + this


@dataclass
class Config:
    iso: str = str(Path.home() / "melee.iso")
    budget_tokens: int = 100_000_000
    target: float = 125.0  # 95% CI half-width, Elo
    max_parallel: int = 14
    load_cap: float = 36.0
    min_running: int = 2  # keep this many games going even when others push the load over the cap
    slots: dict = field(default_factory=lambda: {"fast": 3, "realtime": 6, "untimed_llm": 8})
    provider_slots: dict = field(default_factory=lambda: {"claude": 6, "gpt": 6, "jev": 4})
    gpu_slots: int = 6
    gpu_free_mb: int = 1500
    stagger_s: float = 20.0
    defer_unit: str = "melee-llm-arena"  # while this unit runs, at most `deferred_llm` token-spending games
    deferred_llm: int = 3
    boot: int = 300
    display: str = ":98"
    max_games: int = 0  # stop after this many started games (0 = no limit); for smoke runs
    only: list = field(default_factory=list)  # restrict to these entrant ids (smoke runs)


def read_results(path: Path) -> list[dict]:
    out = []
    if path.exists():
        for ln in path.read_text().splitlines():
            try:
                out.append(json.loads(ln))
            except ValueError:
                pass
    return out


def provider_tokens(rec: dict, entrants: dict[str, Entrant]) -> dict[str, int]:
    out: Counter = Counter()
    for port, s in (rec.get("sides") or {}).items():
        e = entrants.get(rec.get(f"p{port}"))
        if e and e.provider in ("claude", "gpt"):
            out[e.provider] += s.get("prompt_tokens", 0) + s.get("completion_tokens", 0)
    return dict(out)


def _gpu_free_mb() -> int | None:
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=10).stdout
        return int(out.split()[0])
    except (OSError, ValueError, IndexError, subprocess.TimeoutExpired):
        return None


def _unit_active(unit: str) -> bool:
    if not unit:
        return False
    r = subprocess.run(["systemctl", "--user", "is-active", unit], capture_output=True, text=True)
    return r.stdout.strip() == "active"


class Bench:
    def __init__(self, cfg: Config, out: Path = DATA):
        self.cfg, self.out = cfg, out
        self.out.mkdir(parents=True, exist_ok=True)
        self.results_path = out / "results.jsonl"
        self.entrants = by_id()
        self.results = read_results(self.results_path)
        self.imported, self.excluded = imports.load()
        self.imported_at = time.time()
        self.lock = threading.Lock()
        self.load = 0.0
        self.running: dict[str, dict] = {}
        self.free_ports = [p for p in PORTS]
        self.events: deque = deque(maxlen=40)
        self.started = 0
        self.last_start = 0.0
        self.standings: dict | None = None
        self.standings_at = 0.0
        self.dirty = True
        self.suspended: dict[str, float] = {}  # entrant → until (after repeated errors)
        self.stop_reason: str | None = None
        self.t0 = time.time()

    # ------------------------------------------------------------------ bookkeeping

    def log(self, msg: str) -> None:
        line = f"{datetime.now():%H:%M:%S} {msg}"
        print(line, flush=True)
        self.events.appendleft(line)

    def spent(self) -> dict:
        with self.lock:
            tot: Counter = Counter()
            usd: Counter = Counter()
            for r in self.results:
                tot.update(provider_tokens(r, self.entrants))
                for port, s in (r.get("sides") or {}).items():
                    e = self.entrants.get(r.get(f"p{port}"))
                    if e and s.get("usd"):
                        usd[e.provider] += s["usd"]
        return {"tokens": sum(tot.values()), "by_provider": dict(tot), "usd_est": {k: round(v, 3) for k, v in usd.items()}}

    def est_tokens(self, eid: str) -> int:
        e = self.entrants[eid]
        if e.provider not in ("claude", "gpt"):
            return 0
        own = [s.get("prompt_tokens", 0) + s.get("completion_tokens", 0)
               for r in self.results for port, s in (r.get("sides") or {}).items() if r.get(f"p{port}") == eid
               and r.get("status") in ("ok", "void", "slow")]
        prior = TOKEN_PRIOR.get(e.kind, 0)
        if not own:
            return prior
        return int((sum(own) + prior) / (len(own) + 1))

    def games(self) -> list[dict]:
        if time.time() - self.imported_at > 1800:
            self.imported, self.excluded = imports.load()
            self.imported_at = time.time()
        with self.lock:
            return [r for r in self.results if r.get("status") == "ok"] + self.imported

    def active(self) -> list[Entrant]:
        now = time.time()
        return [e for e in self.entrants.values() if e.active and e.spec and self.suspended.get(e.id, 0) < now
                and (not self.cfg.only or e.id in self.cfg.only)]

    # ------------------------------------------------------------------ choosing a game

    def kind_of_game(self, a: Entrant, b: Entrant) -> str:
        mode = game_mode(a, b)
        if mode == "realtime":
            return "realtime"
        return "untimed_llm" if (a.provider != "none" or b.provider != "none") else "fast"

    def feasible(self, a: Entrant, b: Entrant, spent: int, gpu_free: int | None, deferred: bool) -> bool:
        cfg = self.cfg
        run = list(self.running.values())
        kind = self.kind_of_game(a, b)
        if sum(r["kind"] == kind for r in run) >= cfg.slots[kind]:
            return False
        # CPU-heavy games respect the load cap; untimed LLM games mostly wait on the API, so they get some slack
        cap = cfg.load_cap + (LOAD_SLACK_IDLE if kind == "untimed_llm" else 0)
        if self.load + LOAD_COST[kind] > cap and len(run) >= cfg.min_running:
            return False
        for prov in {a.provider, b.provider} - {"none"}:
            n = sum(r["providers"].count(prov) for r in run) + [a.provider, b.provider].count(prov)
            if n > cfg.provider_slots.get(prov, 99):
                return False
        spends = a.provider in ("claude", "gpt") or b.provider in ("claude", "gpt")
        if spends:
            inflight = sum(r["est_tokens"] for r in run)
            if spent + inflight + self.est_tokens(a.id) + self.est_tokens(b.id) > cfg.budget_tokens:
                return False
            if deferred and sum(r["spends"] for r in run) >= cfg.deferred_llm:
                return False
        ngpu = a.gpu + b.gpu
        if ngpu:
            if sum(r["gpu"] for r in run) + ngpu > cfg.gpu_slots:
                return False
            if gpu_free is not None and gpu_free < cfg.gpu_free_mb * ngpu:
                return False
        return True

    def track_fit(self, track: str, games: list[dict], players: list[str]):
        tg = ratings.track_games(games, track, self.entrants)
        f = ratings.Fit(tg, extra_players=players)
        H = f.H.copy()
        for r in self.running.values():  # count running games as if played
            if r["track"] in (track, "shared") and r["p1"] in f.idx and r["p2"] in f.idx:
                i, j = f.idx[r["p1"]], f.idx[r["p2"]]
                p = 1 / (1 + np.exp(-(f.th[i] - f.th[j])))
                w = p * (1 - p)
                H[i, i] += w
                H[j, j] += w
                H[i, j] -= w
                H[j, i] -= w
        return f, np.linalg.inv(H)

    def needs(self, track: str, f, cov) -> dict[str, float]:
        boot = {}
        if self.standings:
            boot = {r["id"]: (r["elo_hi"] - r["elo_lo"]) / 2 for r in self.standings["tracks"][track]["players"]
                    if r.get("elo_lo") is not None}
        out = {}
        for e in self.active():
            if track not in tracks_of(e) or e.id == ratings.ANCHOR:
                continue
            lap, lap_now = f.half_width(e.id, cov), f.half_width(e.id)
            # the bootstrap CI (wider with few games) shrinks like the Laplace one does with the running games
            out[e.id] = max(lap, boot.get(e.id, 0) * lap / lap_now if lap_now else 0)
        return out

    def pick(self) -> dict | None:
        cfg = self.cfg
        games = self.games()
        spent = self.spent()["tokens"]
        gpu_free = _gpu_free_mb()
        deferred = _unit_active(cfg.defer_unit)
        self.load = os.getloadavg()[0]
        act = self.active()
        values: dict[tuple[str, str], float] = {}
        unconverged = {}
        for track in ratings.TRACK_NAMES:
            players = [e.id for e in act if track in tracks_of(e)]
            if not players:
                continue
            f, cov = self.track_fit(track, games, players)
            half = self.needs(track, f, cov)
            unconverged[track] = sorted(k for k, v in half.items() if v > cfg.target)
            K = [k for k in half]
            C = np.array([f.contrast(k) for k in K]) if K else np.zeros((0, len(f.players)))
            weight = np.array([1.0 if half[k] > cfg.target else 0.02 for k in K])
            for i, a in enumerate(players):
                for b in players[i + 1:]:
                    t = game_track(self.entrants[a], self.entrants[b])
                    if t not in (track, "shared"):
                        continue
                    d = f.contrast(a) - f.contrast(b)
                    p = f.p_win(a, b)
                    w = p * (1 - p)
                    sd = cov @ d
                    red = w * (C @ sd) ** 2 / (1 + w * d @ sd) * ELO**2
                    values[(a, b)] = values.get((a, b), 0.0) + float(weight @ red)
        self.unconverged = unconverged
        if not any(unconverged.values()):
            self.stop_reason = f"every entrant's 95% CI is within ±{cfg.target:.0f}"
            return None
        best, best_score = None, 0.0
        for (a, b), v in values.items():
            ea, eb = self.entrants[a], self.entrants[b]
            if v <= 0 or not self.feasible(ea, eb, spent, gpu_free, deferred):
                continue
            score = v / (self.est_tokens(a) + self.est_tokens(b) + OVERHEAD) * random.uniform(0.85, 1.15)
            if score > best_score:
                best, best_score = (a, b), score
        if best is None:
            return None
        return self.make_job(*best, games, best_score)

    def make_job(self, a: str, b: str, games: list[dict], score: float) -> dict:
        ea, eb = self.entrants[a], self.entrants[b]
        both = [g for g in games + list(self.running.values()) if {g["p1"], g["p2"]} == {a, b}]
        stage = min(STAGES, key=lambda s: (sum(g.get("stage") == s for g in both), random.random()))
        a_first = sum(g["p1"] == a for g in both) <= sum(g["p1"] == b for g in both)
        p1, p2 = (ea, eb) if a_first else (eb, ea)
        kind = self.kind_of_game(ea, eb)
        jid = f"{datetime.now():%Y%m%dT%H%M%S}-{self.started:04d}"
        return {"id": jid, "p1": p1.id, "p2": p2.id, "spec1": p1.spec, "spec2": p2.spec, "stage": stage,
                "mode": game_mode(ea, eb), "track": game_track(ea, eb), "kind": kind,
                "providers": [x.provider for x in (ea, eb) if x.provider != "none"],
                "spends": ea.provider in ("claude", "gpt") or eb.provider in ("claude", "gpt"),
                "gpu": ea.gpu + eb.gpu, "est_tokens": self.est_tokens(a) + self.est_tokens(b),
                "value": round(score * 1e6, 3)}

    # ------------------------------------------------------------------ running a game

    def can_start(self) -> tuple[bool, str]:
        cfg = self.cfg
        if cfg.max_games and self.started >= cfg.max_games:
            return False, "max games started"
        if len(self.running) >= cfg.max_parallel:
            return False, "all slots busy"
        if time.time() - self.last_start < cfg.stagger_s:
            return False, "staggering starts"
        load = os.getloadavg()[0]
        if load > cfg.load_cap + LOAD_SLACK_IDLE and len(self.running) >= cfg.min_running:
            return False, f"load {load:.1f} > {cfg.load_cap:.0f}"
        return True, ""

    def start(self, job: dict) -> None:
        with self.lock:
            port = next((p for p in self.free_ports if _port_free(p)), None)
            if port is None:
                self.log("no free Slippi port")
                return
            self.free_ports.remove(port)
            job.update(port=port, started=round(time.time(), 1))
            self.running[job["id"]] = job
        self.started += 1
        self.last_start = time.time()
        self.log(f"start {job['id']} {job['track']}/{job['mode']} {job['stage'][:5]} {job['p1']} vs {job['p2']} "
                 f"(port {port}, est {job['est_tokens']:,} tok)")
        threading.Thread(target=self._run, args=(job,), daemon=True).start()

    def _run(self, job: dict) -> None:
        gdir = GAMES / job["id"]
        gdir.mkdir(parents=True, exist_ok=True)
        timeout = TIMEOUT[job["kind"]]
        cmd = [sys.executable, "-m", "melee_llm.bench", "one", "--iso", self.cfg.iso, "--port", str(job["port"]),
               "--out", str(gdir), "--job", json.dumps({k: job[k] for k in ("id", "p1", "p2", "spec1", "spec2", "stage", "mode")})]
        if job["kind"] == "fast":
            cmd = ["nice", "-n", "8"] + cmd  # unthrottled bot games yield to real-time ones
        env = {**os.environ, "DISPLAY": self.cfg.display, "MELEE_HEADLESS_DISPLAY": self.cfg.display}
        t0 = time.time()
        base = {k: job[k] for k in ("id", "p1", "p2", "spec1", "spec2", "stage", "mode", "track", "port")}
        base.update(dir=str(gdir), ts=round(t0, 1))
        rec = None
        try:
            p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env, cwd=ROOT,
                                 start_new_session=True)
            try:
                stdout, stderr = p.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                os.killpg(p.pid, signal.SIGTERM)
                try:
                    stdout, stderr = p.communicate(timeout=30)
                except subprocess.TimeoutExpired:
                    os.killpg(p.pid, signal.SIGKILL)
                    stdout, stderr = p.communicate()
                stdout = ""
            (gdir / "stderr.log").write_text(stderr[-200_000:] + stdout[-20_000:])
            line = next((ln for ln in reversed(stdout.splitlines()) if ln.startswith("{")), None)
            if line:
                rec = {**base, **json.loads(line)}
                rec["status"] = status_of(rec)
            else:
                timed_out = time.time() - t0 >= timeout
                err = "timeout" if timed_out else (stderr.strip().splitlines() or ["no output"])[-1][:300]
                rec = {**base, "status": "timeout" if timed_out else "error", "error": err, "wall_s": round(time.time() - t0, 1)}
        except Exception as e:  # never lose the slot
            rec = {**base, "status": "error", "error": f"{type(e).__name__}: {e}"[:300]}
        finally:
            with self.lock:
                self.running.pop(job["id"], None)
                self.free_ports.append(job["port"])
                if rec:
                    self.results.append(rec)
                    with self.results_path.open("a") as f:
                        f.write(json.dumps(rec, default=float) + "\n")
                self.dirty = True
        self.on_result(rec)

    def on_result(self, rec: dict) -> None:
        tok = sum(provider_tokens(rec, self.entrants).values())
        if rec["status"] in ("ok", "void", "slow"):
            w = {1: rec["p1"], 2: rec["p2"]}.get(rec.get("winner"), "draw")
            self.log(f"{rec['status']:5s} {rec['id']} {rec['p1']} vs {rec['p2']}: stocks "
                     f"{ {k: int(v) for k, v in (rec.get('stocks') or {}).items()} } → {w} | {rec.get('frames')}f "
                     f"{rec.get('fps')} fps {rec.get('wall_s')}s | {tok:,} tok")
        else:
            self.log(f"{rec['status']:5s} {rec['id']} {rec['p1']} vs {rec['p2']}: {rec.get('error')}")
        # an entrant whose last 3 bench games all failed sits out for an hour (crashing bot, OOM, API outage)
        for eid in (rec["p1"], rec["p2"]):
            last = [r["status"] for r in self.results if eid in (r["p1"], r["p2"])][-3:]
            if len(last) == 3 and all(s in ("error", "timeout", "void") for s in last):
                self.suspended[eid] = time.time() + 3600
                self.log(f"suspend {eid} for 1 h after 3 failed games")

    # ------------------------------------------------------------------ the loop

    def refresh_standings(self, force: bool = False) -> None:
        if not (force or (self.dirty and time.time() - self.standings_at > 120)):
            return
        with self.lock:
            results = list(self.results)
            self.dirty = False
        st = ratings.standings(results, self.imported, self.excluded, boot=self.cfg.boot, target=self.cfg.target)
        self.standings, self.standings_at = st, time.time()
        _write_json(self.out / "standings.json", st)

    def write_status(self, phase: str, waiting: str = "") -> None:
        sp = self.spent()
        st = {"updated": round(time.time(), 1), "started_at": round(self.t0, 1), "phase": phase, "waiting": waiting,
              "stop_reason": self.stop_reason, "budget_tokens": self.cfg.budget_tokens, "spent": sp,
              "target": self.cfg.target, "load": round(os.getloadavg()[0], 1), "games_started": self.started,
              "unconverged": getattr(self, "unconverged", {}), "suspended": {k: round(v) for k, v in self.suspended.items()
                                                                              if v > time.time()},
              "running": [{k: r[k] for k in ("id", "p1", "p2", "stage", "mode", "track", "started", "est_tokens", "port")}
                          for r in list(self.running.values())],
              "events": list(self.events)[:25], "pid": os.getpid()}
        _write_json(self.out / "status.json", st)

    def run(self) -> None:
        self.log(f"bench: {len(self.results)} results so far, {len(self.imported)} imported games; "
                 f"budget {self.cfg.budget_tokens:,} tokens, {self.spent()['tokens']:,} spent")
        self.refresh_standings(force=True)
        stop = threading.Event()
        signal.signal(signal.SIGTERM, lambda *_: stop.set())
        waiting, last_status, idle_since = "", 0.0, time.time()
        while not stop.is_set():
            self.refresh_standings()
            ok, why = self.can_start()
            if ok and not self.stop_reason:
                job = self.pick()
                if job:
                    self.start(job)
                    waiting = ""
                else:
                    waiting = self.stop_reason or "no feasible pairing (slots, GPU, budget)"
            else:
                waiting = why or waiting
            spent = self.spent()["tokens"]
            if not self.stop_reason and spent >= self.cfg.budget_tokens:
                self.stop_reason = f"token budget reached ({spent:,})"
            if not self.stop_reason and self.cfg.max_games and self.started >= self.cfg.max_games and not self.running:
                self.stop_reason = "max games played"
            if self.stop_reason and not self.running:
                break
            if self.running or not waiting.startswith("no feasible"):
                idle_since = time.time()
            elif time.time() - idle_since > 1800:  # nothing fits and nothing ran for 30 min: budget or GPU exhausted
                self.stop_reason = "no affordable informative pairing left for 30 min"
                break
            if time.time() - last_status > 10:
                self.write_status("running", waiting)
                last_status = time.time()
            stop.wait(5)
        if stop.is_set():
            self.log("stopping: SIGTERM; running games are killed with the unit")
            self.stop_reason = self.stop_reason or "stopped"
        self.refresh_standings(force=True)
        self.write_status("done" if not stop.is_set() else "stopped", self.stop_reason or "")
        self.log(f"done: {self.stop_reason}")


def _port_free(port: int) -> bool:
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def _write_json(path: Path, data) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, default=float, indent=1))
    tmp.replace(path)
