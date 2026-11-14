"""Schedule and run arena games: each game is a child process with its own Slippi port, replay dir and process group."""
from __future__ import annotations

import json
import os
import random
import signal
import subprocess
import sys
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from melee_llm.runner import ROOT

PORTS = range(51880, 51920)  # the arena's Slippi port block (Jev 51840-51859, perception 51860-51879)
STAGES = ("BATTLEFIELD", "FINAL_DESTINATION")
ANCHORS = ("cpu:5", "cpu:9")
VOID_API_FAILED_FRAC = 0.10  # a side whose calls failed (after retries) this often → game void, not rated


@dataclass(frozen=True)
class Job:
    key: str
    kind: str  # "llm" (model vs model) | "anchor" (model vs CPU)
    stage: str
    p1: str  # "llm_paused:<model>[,k=v]" or "cpu:N"
    p2: str
    rep: int

    def players(self) -> tuple[str, str]:
        return player_name(self.p1), player_name(self.p2)


def player_name(spec: str) -> str:
    """Rating identity: the model id (spec options excluded) or cpu:N."""
    return spec if spec.startswith("cpu:") else spec.partition(":")[2].split(",")[0]


def llm_spec(model: str, opts: str) -> str:
    return f"llm_paused:{model}" + (f",{opts}" if opts else "")


def schedule(models: list[str], stages=STAGES, games: int = 2, anchor_games: int = 2, anchors=ANCHORS,
             opts: str = "", seed: int = 0, rotate: bool = False) -> list[Job]:
    """Round-robin: `games` per ordered pair (so both port orders) per stage, plus `anchor_games` per model, CPU
    level and stage, the model alternating ports. With `rotate` the counts are per pairing instead of per stage
    and the stage rotates (A-B on stage 0, B-A on stage 1, ...): a quarter of the games for the same balance.
    Ordered so that any prefix is roughly balanced."""
    jobs = []
    for rep in range(max(games, anchor_games)):
        batch = []
        for si, stage in enumerate(stages):
            for i, a in enumerate(models):
                for j, b in enumerate(models):
                    if rep < games and i != j and (not rotate or (rep + (i > j)) % len(stages) == si):
                        batch.append(Job(f"{stage}|{a}|{b}|{rep}", "llm", stage, llm_spec(a, opts), llm_spec(b, opts), rep))
                if rep >= anchor_games:
                    continue
                for k, cpu in enumerate(anchors):
                    r = rep + (i + k if rotate else 0)
                    if rotate and r % len(stages) != si:
                        continue
                    p1, p2 = (llm_spec(a, opts), cpu) if r % 2 == 0 else (cpu, llm_spec(a, opts))
                    batch.append(Job(f"{stage}|{player_name(p1)}|{player_name(p2)}|{rep}", "anchor", stage, p1, p2, rep))
        random.Random(f"{seed}-{rep}").shuffle(batch)
        jobs += batch
    return jobs


def read_results(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text().splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            pass  # a line cut by a crash; the game reruns
    return out


def tokens_of(rec: dict) -> int:
    return sum(s.get("prompt_tokens", 0) + s.get("completion_tokens", 0) for s in (rec.get("sides") or {}).values())


# ------------------------------------------------------------------ one game (child process)


def play_one(job: dict, iso: str, port: int, out: Path, cap_frames: int, retries: int) -> dict:
    import melee

    from melee_llm.agents.base import CPU
    from melee_llm.llm_arena.agent import ArenaLLM
    from melee_llm.runner import play

    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))  # play()'s cleanup stops Dolphin
    out.mkdir(parents=True, exist_ok=True)
    agents, quitter = {}, True
    for p, spec in ((1, job["p1"]), (2, job["p2"])):
        if spec.startswith("cpu:"):
            agents[p] = CPU(int(spec[4:]), melee.Character.FOX)
        else:
            agents[p] = ArenaLLM(spec.partition(":")[2], cap_frames=cap_frames, quitter=quitter, retries=retries)
            agents[p].character, agents[p].log_dir, quitter = melee.Character.FOX, out, False
    meta = {"source": "llm-arena", "label": f"LLM arena {job['p1'].split(',')[0]} vs {job['p2'].split(',')[0]}",
            "specs": {1: job["p1"], 2: job["p2"]}, "arena_key": job["key"]}
    t0 = time.time()
    [r] = play(agents, iso, melee.Stage[job["stage"]], "fast", 1, replay_dir=out, slippi_port=port, meta=meta)
    sides = {}
    for p, a in agents.items():
        if isinstance(a, ArenaLLM):
            logs = sorted(out.rglob(f"*.p{p}.llm.jsonl"))
            sides[str(p)] = {**a.summary(), "log": str(logs[-1]) if logs else None}
    return {**asdict(r), "wall_s": round(time.time() - t0, 1), "sides": sides}


# ------------------------------------------------------------------ the pool (parent process)


def status_of(rec: dict) -> str:
    """ok | void. Void: some side's API calls kept failing after retries (infra, not decision quality)."""
    for s in rec.get("sides", {}).values():
        if s["decisions"] and s["api_failed"] / s["decisions"] > VOID_API_FAILED_FRAC:
            return "void"
    return "ok"


def run(jobs: list[Job], iso: str, out: Path, parallel: int = 16, cap_frames: int = 3600, retries: int = 4,
        timeout_s: int = 3600, max_attempts: int = 2, max_tokens: int = 0, stagger_s: float = 6.0,
        display: str = ":98") -> None:
    assert display != ":99", "the live slot's display is off limits"
    out.mkdir(parents=True, exist_ok=True)
    results = out / "results.jsonl"
    done = read_results(results)
    ok = {r["key"] for r in done if r["status"] == "ok"}
    attempts: dict[str, int] = {}
    for r in done:
        attempts[r["key"]] = attempts.get(r["key"], 0) + 1
    todo = [j for j in jobs if j.key not in ok and attempts.get(j.key, 0) < max_attempts]
    spent = sum(tokens_of(r) for r in done)
    print(f"{len(jobs)} games scheduled, {len(ok)} done, {len(todo)} to run; {spent:,} tokens spent so far", flush=True)

    lock, free = threading.Lock(), list(PORTS)
    state = {"spent": spent, "started": 0, "stop": False}
    env = {**os.environ, "DISPLAY": display}

    def record(rec: dict) -> None:
        with lock:
            with results.open("a") as f:
                f.write(json.dumps(rec, default=float) + "\n")
            state["spent"] += tokens_of(rec)
            if max_tokens and state["spent"] >= max_tokens and not state["stop"]:
                state["stop"] = True
                print(f"token budget {max_tokens:,} reached: no new games", flush=True)

    def go(job: Job) -> None:
        with lock:
            if state["stop"]:
                return
            n = state["started"]
            state["started"] += 1
        if n < parallel:
            time.sleep(stagger_s * n)  # Dolphin boots are CPU-heavy: spread the first wave
        for attempt in range(2):
            with lock:
                port = free.pop(0)
            gdir = out / "games" / job.key.replace("|", "__").replace(":", "-") / f"try{attempts.get(job.key, 0)}-{attempt}"
            cmd = [sys.executable, "-m", "melee_llm.llm_arena", "one", "--iso", iso, "--port", str(port),
                   "--out", str(gdir), "--cap-frames", str(cap_frames), "--retries", str(retries),
                   "--job", json.dumps(asdict(job))]
            gdir.mkdir(parents=True, exist_ok=True)
            base = {**asdict(job), "port": port, "dir": str(gdir), "cap_frames": cap_frames, "ts": round(time.time(), 1)}
            t0 = time.time()
            p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env, cwd=ROOT,
                                 start_new_session=True)  # own process group: kill Dolphin with it
            try:
                stdout, stderr = p.communicate(timeout=timeout_s)
            except subprocess.TimeoutExpired:
                os.killpg(p.pid, signal.SIGTERM)
                try:
                    stdout, stderr = p.communicate(timeout=30)
                except subprocess.TimeoutExpired:
                    os.killpg(p.pid, signal.SIGKILL)
                    stdout, stderr = p.communicate()
                stdout = ""
            finally:
                with lock:
                    free.append(port)
            (gdir / "stderr.log").write_text(stderr + stdout)
            line = next((ln for ln in reversed(stdout.splitlines()) if ln.startswith("{")), None)
            if line:
                rec = {**base, **json.loads(line)}
                rec["status"] = status_of(rec)
                record(rec)
                a, b = job.players()
                w = {1: a, 2: b}.get(rec["winner"], "draw")
                print(f"{rec['status']:4s} {job.stage[:5]} {a} vs {b}: stocks {rec['stocks']} pct "
                      f"{ {k: round(v) for k, v in rec['percent'].items()} } → {w} | {rec['frames']}f "
                      f"{rec['wall_s']}s {tokens_of(rec):,} tok | total {state['spent']:,}", flush=True)
                return
            timed_out = time.time() - t0 >= timeout_s
            if attempt == 0 and not timed_out and "could not connect" in stderr:
                print(f"retry {job.key}: Dolphin did not connect", flush=True)
                continue
            err = "timeout" if timed_out else (stderr.strip().splitlines() or ["no output"])[-1][:300]
            record({**base, "status": "timeout" if timed_out else "error", "error": err})
            print(f"FAIL {job.key}: {err}", flush=True)
            return

    threads: list[threading.Thread] = []
    sem = threading.Semaphore(parallel)

    def worker(job: Job) -> None:
        try:
            go(job)
        finally:
            sem.release()

    for job in todo:
        sem.acquire()
        if state["stop"]:
            sem.release()
            break
        t = threading.Thread(target=worker, args=(job,), daemon=True)
        t.start()
        threads.append(t)
    for t in threads:
        t.join()
