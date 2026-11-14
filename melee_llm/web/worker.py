"""The worker owns the live slot (display :99, Slippi port 51441) and the headless pool (display :98).

Live jobs run on the live slot one at a time, in queue order. When none is queued, the arena
(melee_llm.arena, one game per process) fills the slot; a queued job waits for the arena game to finish,
or aborts it if the job asked to start now. Headless (fast) jobs run in parallel, up to 4, on
ports 51700-51799. Every job runs as `melee_llm.web.runjob` in its own process group, so cancel
kills Dolphin and the bots with it.

    python -m melee_llm.web.worker --iso ~/melee.iso     # systemd user unit melee-arena
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from melee_llm.paths import DATA, HEADLESS_DISPLAY, HEADLESS_MAX, HEADLESS_PORTS, ISO, LIVE_DISPLAY, LIVE_PORT, ROOT, VENV_PY
from melee_llm.util import port_free, read_jsonl
from melee_llm.web import jobs, live, logs

ARENA_LOG = DATA / "arena.log"
KILL_AFTER = 20  # seconds between SIGTERM and SIGKILL


@dataclass
class Proc:
    popen: subprocess.Popen
    kind: str  # job | arena
    job: dict | None = None
    started: float = field(default_factory=time.time)
    term_at: float | None = None
    synced: float = 0.0

    def terminate(self) -> None:
        if self.term_at is None:
            self.term_at = time.time()
            _signal_group(self.popen.pid, signal.SIGTERM)
        elif time.time() - self.term_at > KILL_AFTER:
            _signal_group(self.popen.pid, signal.SIGKILL)


def _signal_group(pid: int, sig: int) -> None:
    try:
        os.killpg(pid, sig)
    except ProcessLookupError:
        pass


def _tail(path: Path, n: int = 4000) -> str:
    try:
        with path.open("rb") as f:
            f.seek(max(0, path.stat().st_size - n))
            return f.read().decode(errors="replace")
    except OSError:
        return ""


def _error_line(text: str) -> str:
    lines = [ln for ln in text.strip().splitlines() if ln.strip()]
    errs = [ln for ln in lines if "Error" in ln or "Exception" in ln]
    return (errs[-1] if errs else lines[-1] if lines else "no output")[:500]


class Worker:
    def __init__(self, iso: str):
        self.iso = iso
        self.live: Proc | None = None
        self.headless: dict[int, Proc] = {}
        self.arena_backoff = 0.0
        self.live_free_since: float | None = None
        self.stopping = False

    # ------------------------------------------------------------------ processes

    def _spawn(self, cmd: list[str], display: str, log: Path) -> subprocess.Popen:
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("ab") as out:
            return subprocess.Popen(cmd, cwd=ROOT, stdout=out, stderr=subprocess.STDOUT, start_new_session=True,
                                    env={**os.environ, "DISPLAY": display, "PYTHONUNBUFFERED": "1"})

    def start_job(self, job: dict, port: int, is_live: bool) -> Proc:
        d = Path(job["dir"])
        spec = {k: job[k] for k in ("id", "p1", "p2", "char1", "char2", "stage", "mode", "games")}
        cmd = [str(VENV_PY), "-m", "melee_llm.web.runjob", "--job", json.dumps(spec), "--dir", str(d),
               "--port", str(port), "--iso", self.iso] + (["--live"] if is_live else [])
        p = self._spawn(cmd, LIVE_DISPLAY if is_live else HEADLESS_DISPLAY, d / "output.log")
        jobs.update(job["id"], status="running", started=time.time(), pid=p.pid, port=port)
        print(f"job {job['id']} started on port {port}: {job['p1']} vs {job['p2']} ({job['mode']})", flush=True)
        return Proc(p, "job", job)

    def start_arena(self) -> Proc:
        if ARENA_LOG.exists() and ARENA_LOG.stat().st_size > 5 << 20:
            ARENA_LOG.replace(ARENA_LOG.with_suffix(".log.1"))
        p = self._spawn([str(VENV_PY), "-m", "melee_llm.arena", "--iso", self.iso, "--games", "1", "--no-retry"], LIVE_DISPLAY, ARENA_LOG)
        return Proc(p, "arena")

    def sync(self, proc: Proc, final: bool = False) -> None:
        """Copy results and token counts from the job dir into the DB (while running, every 5 s)."""
        job = proc.job
        d = Path(job["dir"])
        results = read_jsonl(d / "results.jsonl")
        found = sorted(p for p in d.rglob("*.jsonl") if p.name != "results.jsonl")  # incl. logs not yet renamed
        fields = {"results": results, "tokens": logs.tokens(found)}
        if final:
            rc = proc.popen.returncode
            cancelled = (jobs.get(job["id"]) or {}).get("cancel")
            status = "cancelled" if cancelled else "done" if rc == 0 else "failed"
            fields.update(status=status, finished=time.time(), pid=None)
            if status == "failed":
                fields["error"] = f"exit {rc}: " + _error_line(_tail(d / "output.log"))
            print(f"job {job['id']} {status} ({len(results)} games)", flush=True)
        jobs.update(job["id"], **fields)
        proc.synced = time.time()

    # ------------------------------------------------------------------ main loop

    def tick(self) -> None:
        running = {j["id"]: j for j in (jobs.get(i) for i in self._job_ids()) if j}
        for proc in self._procs():
            if proc.kind == "job" and running.get(proc.job["id"], {}).get("cancel"):
                proc.terminate()
            elif proc.term_at is not None:
                proc.terminate()  # escalates to SIGKILL after KILL_AFTER
        # reap
        for jid, proc in list(self.headless.items()):
            if proc.popen.poll() is not None:
                self.sync(proc, final=True)
                del self.headless[jid]
            elif time.time() - proc.synced > 5:
                self.sync(proc)
        if self.live and self.live.popen.poll() is not None:
            if self.live.kind == "job":
                self.sync(self.live, final=True)
            elif self.live.popen.returncode not in (0, -signal.SIGTERM, 143) and self.live.term_at is None:
                self.arena_backoff = time.time() + 30
            self.live = None
            self.live_free_since = time.time()
            live.idle()
        elif self.live and self.live.kind == "job" and time.time() - self.live.synced > 5:
            self.sync(self.live)
        if self.stopping:
            return
        # headless pool
        for job in jobs.queued("headless"):
            if len(self.headless) >= HEADLESS_MAX:
                break
            used = {p.job["port"] for p in self.headless.values() if p.job.get("port")}
            port = next((p for p in HEADLESS_PORTS if p not in used and port_free(p)), None)
            if port is None:
                break
            job["port"] = port
            self.headless[job["id"]] = self.start_job(job, port, is_live=False)
        # live slot
        waiting = jobs.queued("live")
        if self.live is None:
            port_ok = port_free(LIVE_PORT) or time.time() - (self.live_free_since or 0) > 60
            if waiting and port_ok:
                self.live = self.start_job(waiting[0], LIVE_PORT, is_live=True)
            elif not waiting and port_ok and jobs.setting("arena", "on") == "on" and time.time() > self.arena_backoff:
                self.live = self.start_arena()
        elif self.live.kind == "arena" and waiting and waiting[0]["preempt"] and self.live.term_at is None:
            print(f"aborting the arena game for job {waiting[0]['id']}", flush=True)
            self.live.terminate()

    def _procs(self) -> list[Proc]:
        return [p for p in [self.live, *self.headless.values()] if p]

    def _job_ids(self) -> list[int]:
        return [p.job["id"] for p in self._procs() if p.kind == "job"]

    def recover(self) -> None:
        with jobs.connect() as db:
            n = db.execute("UPDATE jobs SET status = 'failed', error = 'worker restarted while running', finished = ? "
                           "WHERE status = 'running'", (time.time(),)).rowcount
        if n:
            print(f"marked {n} interrupted jobs as failed", flush=True)
        live.idle()

    def run(self) -> None:
        self.recover()

        def stop(*_):
            self.stopping = True
        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        while True:
            self.tick()
            if self.stopping:
                procs = self._procs()
                if not procs:
                    break
                for p in procs:
                    p.terminate()
            time.sleep(0.5)
        live.idle()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--iso", default=ISO)
    a = ap.parse_args()
    if not Path(a.iso).is_file():
        sys.exit(f"no ISO at {a.iso}")
    Worker(a.iso).run()


if __name__ == "__main__":
    main()
