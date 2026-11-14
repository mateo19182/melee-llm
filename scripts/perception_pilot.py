"""Perception pilot: does a screenshot help the LLM player compared with the structured text state?

    uv run scripts/perception_pilot.py run --iso ~/melee.iso --out replays/perception/A --jobs 6 --games 8 \
        --cond "llm_paused:claude-haiku-4-5-20251001,obs=text" --cond "llm_paused:claude-haiku-4-5-20251001,obs=image"
    uv run scripts/perception_pilot.py summary replays/perception/A
    uv run scripts/perception_pilot.py probe replays/perception/A --model claude-haiku-4-5-20251001 --n 100
    uv run scripts/perception_pilot.py bench            # capture latency on a private display, CPU vs CPU

Every game runs in its own process on its own private Xvfb display (melee_llm.vision.PrivateDisplay), Slippi
port (51860-51879) and replay dir. `--cap` ends a game after that many frames (scored by stocks, then
percent, like a time-out) so a slow LLM game cannot run for half an hour. See docs/perception.md.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import random
import signal
import statistics
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from melee_llm.paths import PERCEPTION_PORTS as PORTS  # noqa: E402


class Capped(Exception):
    pass


def one(a) -> None:
    import melee

    from melee_llm.players import make
    from melee_llm.runner import GameResult, play
    from melee_llm.util import exit_on_term
    from melee_llm.vision import PrivateDisplay
    exit_on_term()
    out = Path(a.out)
    p1 = make(a.p1, a.char1, out)
    agents = {1: p1, 2: make(a.p2, a.char2)}
    last = {"gs": None, "t0": time.time()}

    def observer(event, info):
        if event == "frame":
            last["gs"] = info["gs"]
            if a.cap and info["gs"].frame >= a.cap:
                raise Capped

    t0 = time.time()
    with PrivateDisplay() as disp:
        try:
            [r] = play(agents, a.iso, melee.Stage[a.stage], a.mode, 1, replay_dir=out, slippi_port=a.port,
                       observer=observer, meta={"source": "perception-pilot", "label": a.cond})
            capped = False
        except Capped:
            gs = last["gs"]
            stocks = {p: int(gs.players[p].stock) for p in agents}
            pct = {p: float(gs.players[p].percent) for p in agents}
            key = {p: (stocks[p], -pct[p]) for p in agents}
            win = max(agents, key=key.get) if key[1] != key[2] else None
            r = GameResult(stocks, pct, int(gs.frame), time.time() - t0, win, {p: x.name for p, x in agents.items()})
            p1.on_game_end(gs)  # play() was aborted before its game_end: close and rename the decision log here
            capped = True
    rec = {"cond": a.cond, "p1": a.p1, "p2": a.p2, "stage": a.stage, "mode": a.mode, "display": disp.name,
           "capped": capped, "wall_s": round(time.time() - t0, 1), **asdict(r)}
    logs = sorted(out.rglob("*.llm.jsonl")) or sorted(out.rglob("llm-*.jsonl"))
    if logs:
        rec["log"] = str(logs[-1])
        rec["llm"] = json.loads(logs[-1].read_text().splitlines()[-1])
    print(json.dumps(rec, default=float))


def run(a) -> None:
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    jobs = [(c, i) for i in range(a.games) for c in a.cond]
    free = [p for p in PORTS if p >= a.port0][: a.jobs]
    results = out / "results.jsonl"
    started = []

    def go(job, attempt=0):
        cond, i = job
        port = free.pop()
        started.append(time.time())
        if len(started) <= a.jobs:  # stagger the first wave: Dolphin boots are CPU-heavy
            time.sleep(max(0.0, 6 * (len(started) - 1) - (time.time() - started[0])))
        retry = False
        try:
            gdir = out / f"{cond.split(':')[0]}-{cond.replace(':', '_').replace(',', '_').replace('/', '_')[-60:]}-{i}"
            gdir.mkdir(parents=True, exist_ok=True)
            cmd = [sys.executable, __file__, "one", "--iso", a.iso, "--p1", cond, "--p2", a.p2, "--char1", a.char1,
                   "--char2", a.char2, "--stage", a.stage, "--mode", a.mode, "--port", str(port), "--out", str(gdir),
                   "--cond", cond, "--cap", str(a.cap)]
            p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=ROOT,
                                 start_new_session=True)
            try:
                stdout, stderr = p.communicate(timeout=a.timeout)
            except subprocess.TimeoutExpired:
                os.killpg(p.pid, signal.SIGTERM)
                try:
                    p.communicate(timeout=20)
                except subprocess.TimeoutExpired:
                    os.killpg(p.pid, signal.SIGKILL)
                raise
            (gdir / "stderr.log").write_text(stderr + stdout)
            line = next((ln for ln in reversed(stdout.splitlines()) if ln.startswith("{")), None)
            if line:
                with results.open("a") as f:
                    f.write(line + "\n")
                r = json.loads(line)
                print(f"{cond:60s} #{i} stocks {r['stocks']} pct {[round(v) for v in r['percent'].values()]} "
                      f"winner {r['winner']} {r['frames']}f {r['wall_s']}s{' capped' if r['capped'] else ''}", flush=True)
            else:
                retry = attempt == 0 and "could not connect" in stderr
                print(f"{cond} #{i}: FAILED{', retrying' if retry else ''} (see {gdir}/stderr.log)", flush=True)
        except subprocess.TimeoutExpired:
            print(f"{cond} #{i}: TIMEOUT", flush=True)
        finally:
            free.append(port)
        if retry:
            go(job, 1)

    with ThreadPoolExecutor(a.jobs) as pool:
        list(pool.map(go, jobs))


def decisions(log: str) -> list[dict]:
    return [r for r in map(json.loads, Path(log).read_text().splitlines()) if r.get("type") == "decision"]


def _ci(k: int, n: int) -> str:
    """Wilson 95% interval for k/n."""
    if not n:
        return "-"
    z, p = 1.96, k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * (p * (1 - p) / n + z * z / (4 * n * n)) ** .5 / d
    return f"{max(0, c - h):.2f}-{min(1, c + h):.2f}"


def summary(a) -> None:
    rows = [json.loads(ln) for d in a.dirs for ln in (Path(d) / "results.jsonl").open()]
    by: dict[str, list] = {}
    for r in rows:
        by.setdefault(r["cond"], []).append(r)
    print(f"{'condition':58s} n  W  L  D  win (95% CI)  stock± pct±   lat s  p50  ptok  ctok  img tok  inval  dec/game  capped")
    for cond, rs in sorted(by.items()):
        w = sum(r["winner"] == 1 for r in rs)
        lo = sum(r["winner"] == 2 for r in rs)
        sd = statistics.fmean(r["stocks"]["1"] - r["stocks"]["2"] for r in rs)
        pdiff = statistics.fmean(r["percent"]["2"] - r["percent"]["1"] for r in rs)
        ds = [d for r in rs if r.get("log") and Path(r["log"]).exists() for d in decisions(r["log"])]
        lat = [d["latency_s"] for d in ds if d["reply_mode"] != "error"]
        n = max(len(ds), 1)
        print(f"{cond:58s} {len(rs):<2d} {w:<2d} {lo:<2d} {len(rs) - w - lo:<2d} {w / len(rs):.2f} ({_ci(w, len(rs))})"
              f" {sd:+5.2f} {pdiff:+5.0f}  {statistics.fmean(lat) if lat else 0:5.2f} {statistics.median(lat) if lat else 0:5.2f}"
              f" {sum(d['prompt_tokens'] for d in ds) / n:5.0f} {sum(d['completion_tokens'] for d in ds) / n:4.0f}"
              f"  {sum(d.get('image_tokens_est', 0) for d in ds) / n:6.0f}"
              f"  {sum(bool(d.get('invalid')) for d in ds) / n:5.3f}  {len(ds) / len(rs):6.0f}"
              f"  {sum(r.get('capped', False) for r in rs)}")
        errs = sum(d["reply_mode"] == "error" for d in ds)
        cap = [d["capture_ms"] for d in ds if "capture_ms" in d]
        stale = [d["stale_frames"] for d in ds if d.get("stale_frames")]
        extra = f"    errors {errs}/{len(ds)}"
        if cap:
            extra += f", capture ms p50 {statistics.median(cap):.1f} p95 {sorted(cap)[int(.95 * len(cap))]:.1f}"
        if stale:
            extra += f", stale frames mean {statistics.fmean(stale):.0f}"
        extra += f", game frames mean {statistics.fmean(r['frames'] for r in rs):.0f}, wall s mean {statistics.fmean(r['wall_s'] for r in rs):.0f}"
        print(extra)


# ---------------------------------------------------------------- perception probe

PROBE_SYSTEM = """You read screenshots of Super Smash Bros. Melee (NTSC 1.02).
Coordinates are Melee units: x grows right, y grows up. {stage} A fighter is about 15 units tall.
The camera zooms to fit both fighters. The bottom HUD shows each port's damage % with stock icons above it, P1 left, P2 right.
P1 is {p1}, P2 is {p2}. "Offstage" means not above the main stage (beyond the ledges or below the floor)."""
PROBE_TOOL = {"type": "function", "function": {"name": "report", "parameters": {
    "type": "object", "required": ["p1", "p2", "p1_left_of_p2"],
    "properties": {**{p: {"type": "object", "required": ["x", "y", "percent", "stocks", "offstage", "airborne", "facing"],
                          "properties": {"x": {"type": "number"}, "y": {"type": "number"},
                                         "percent": {"type": "integer"}, "stocks": {"type": "integer"},
                                         "offstage": {"type": "boolean"}, "airborne": {"type": "boolean"},
                                         "facing": {"type": "string", "enum": ["left", "right"]}}}
                      for p in ("p1", "p2")},
                   "p1_left_of_p2": {"type": "boolean"}}}}}


def probe(a) -> None:
    """Ask a model to read the true state from sent screenshots (image only) and score it against the logged obs."""
    fixed = Path(a.dirs[0]) / "probe-frames.json"  # the sample is frozen on first use: every model sees the same frames
    if fixed.exists():
        frames = [(Path(i), o) for i, o in json.loads(fixed.read_text())]
        return _probe(a, frames[: a.n])
    frames = []
    for d in a.dirs:
        for r in (json.loads(ln) for ln in (Path(d) / "results.jsonl").open()):
            if not r.get("log") or "obs=text" in r["cond"] or not Path(r["log"]).exists():
                continue
            media = Path(r["log"]).with_suffix(".frames")
            for dec in decisions(r["log"]):
                imgs = dec.get("images") or []
                # paused games only: there the image is exactly the logged state's frame
                if imgs and dec.get("stale_frames", 0) == 0 and imgs[-1]["frame"] == dec["asked_frame"]:
                    frames.append((media / imgs[-1]["file"], dec["obs"]))
    random.Random(a.seed).shuffle(frames)
    frames = [f for f in frames if f[0].exists()][: a.n]
    fixed.write_text(json.dumps([(str(i), o) for i, o in frames]))
    _probe(a, frames)


def _probe(a, frames) -> None:
    import melee

    from melee_llm.llm import LLM
    from melee_llm.state import stage_text
    llm = LLM(a.model, base_url=a.base_url, mode="json", timeout=90, max_tokens=1200)
    out = Path(a.dirs[0]) / f"probe-{a.model.replace('/', '_')}.jsonl"
    rows = []
    with out.open("w") as f, ThreadPoolExecutor(a.jobs) as pool:
        def ask(item):
            img, obs = item
            uri = "data:image/jpeg;base64," + base64.b64encode(img.read_bytes()).decode()
            sys_ = PROBE_SYSTEM.format(stage=stage_text(melee.Stage[obs["stage"]]), p1=f"{obs['me']['char']}", p2=f"{obs['opp']['char']}")
            for _ in range(2):  # one retry: some models sometimes reason in prose until the token cap
                rep = llm.choose(sys_, "Report the state of both fighters in this frame.", PROBE_TOOL, images=[uri])
                if rep.args:
                    break
            return {"raw": "" if rep.args else rep.text[-400:], "image": str(img), "truth": {"p1": obs["me"], "p2": obs["opp"]}, "reply": rep.args,
                    "latency_s": rep.latency_s, "prompt_tokens": rep.prompt_tokens, "error": rep.error}
        for row in pool.map(ask, frames):
            rows.append(row)
            f.write(json.dumps(row) + "\n")
    score(rows, a.model)


def score(rows: list[dict], model: str) -> None:
    def get(rep, p, k):
        try:
            return rep[p][k]
        except (KeyError, TypeError):
            return None
    ok = [r for r in rows if r["reply"]]
    acc: dict[str, list] = {}
    for r in ok:
        t, rep = r["truth"], r["reply"]
        for p in ("p1", "p2"):
            tr = t[p]
            pc, st = get(rep, p, "percent"), get(rep, p, "stocks")
            acc.setdefault("percent exact", []).append(pc is not None and abs(pc - tr["pct"]) <= 1)
            if pc is not None:
                acc.setdefault("percent abs err", []).append(abs(pc - tr["pct"]))
            acc.setdefault("stocks exact", []).append(st == tr["stocks"])
            acc.setdefault("offstage", []).append(get(rep, p, "offstage") == tr["offstage"])
            acc.setdefault("airborne", []).append(get(rep, p, "airborne") == (not tr["ground"]))
            acc.setdefault("facing", []).append((get(rep, p, "facing") or "?")[:1].upper() == tr["facing"])
            x, y = get(rep, p, "x"), get(rep, p, "y")
            if isinstance(x, (int, float)) and isinstance(y, (int, float)):
                acc.setdefault("x abs err", []).append(abs(x - tr["x"]))
                acc.setdefault("y abs err", []).append(abs(y - tr["y"]))
        if abs(t["p1"]["x"] - t["p2"]["x"]) > 5:
            acc.setdefault("left/right order", []).append(rep.get("p1_left_of_p2") == (t["p1"]["x"] < t["p2"]["x"]))
        off = [p for p in ("p1", "p2") if t[p]["offstage"]]
        if off:
            acc.setdefault("who is offstage (frames with someone offstage)", []).append(
                all(get(rep, p, "offstage") == t[p]["offstage"] for p in ("p1", "p2")))
        # identity-free: the better of the two pairings (both fighters may wear similar costumes)
        def err(pa, pb):
            x, y = get(rep, pa, "x"), get(rep, pa, "y")
            if not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
                return None
            return abs(x - t[pb]["x"]) + abs(y - t[pb]["y"])
        same, swap = [err("p1", "p1"), err("p2", "p2")], [err("p1", "p2"), err("p2", "p1")]
        if None not in same + swap:
            best = min(sum(same), sum(swap))
            acc.setdefault("pair x+y abs err, best pairing (per fighter)", []).append(best / 2)
            if abs(t["p1"]["x"] - t["p2"]["x"]) > 20:
                acc.setdefault("identity right (fighters >20 apart)", []).append(sum(same) <= sum(swap))
    lat = [r["latency_s"] for r in ok]
    print(f"probe {model}: {len(ok)}/{len(rows)} parsed, latency p50 {statistics.median(lat) if lat else 0:.2f}s, "
          f"prompt tokens mean {statistics.fmean(r['prompt_tokens'] for r in ok) if ok else 0:.0f}")
    for k, v in acc.items():
        if "err" in k:
            print(f"  {k:48s} median {statistics.median(v):6.1f}  mean {statistics.fmean(v):6.1f}  (n={len(v)})")
        else:
            print(f"  {k:48s} {sum(v) / len(v):6.2f}  (n={len(v)})")


def rescore(a) -> None:
    for p in a.files:
        score([json.loads(ln) for ln in Path(p).open()], Path(p).stem)


# ---------------------------------------------------------------- capture benchmark

def bench(a) -> None:
    """CPU vs CPU on a private display: grab + encode cost per screenshot, and the game's fps with/without grabs."""
    import melee

    from melee_llm.agents.base import CPU
    from melee_llm.runner import play
    from melee_llm.vision import Camera, PrivateDisplay
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    with PrivateDisplay() as disp:
        cam = Camera(disp.name, a.width)
        st = {"n": 0, "t": None, "grab": [], "enc": [], "kb": []}

        def obs(ev, info):
            if ev != "frame":
                return
            st["n"] += 1
            if st["n"] == 60:
                st["t"] = time.perf_counter()
            if st["n"] > 60 and st["n"] % a.every == 0:
                s = cam.shot(info["gs"].frame)
                if s:
                    st["grab"].append(s.grab_ms)
                    st["enc"].append(s.encode_ms)
                    st["kb"].append(len(s.jpeg) / 1e3)
                    if st["n"] % 600 == 0:
                        (out / f"bench-f{s.frame}.jpg").write_bytes(s.jpeg)
            if st["n"] >= 60 + a.frames:
                raise Capped
        try:
            play({1: CPU(5), 2: CPU(5)}, a.iso, melee.Stage.BATTLEFIELD, "lockstep", 1, replay_dir=out,
                 slippi_port=a.port, observer=obs, meta={"source": "perception-bench"})
        except Capped:
            pass
        fps = a.frames / (time.perf_counter() - st["t"])
    g, e = sorted(st["grab"]), sorted(st["enc"])
    print(json.dumps({"display": disp.name, "window": cam.window, "every": a.every, "width": a.width, "fps": round(fps, 1),
                      "grabs": len(g), "grab_ms_p50": statistics.median(g), "grab_ms_p95": g[int(.95 * len(g))],
                      "encode_ms_p50": statistics.median(e), "jpeg_kb_p50": round(statistics.median(st["kb"]), 1)}))


def main() -> None:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--iso", required=True)
    r.add_argument("--out", required=True)
    r.add_argument("--cond", action="append", required=True, help="p1 spec")
    r.add_argument("--p2", default="cpu:5")
    r.add_argument("--char1", default="FOX")
    r.add_argument("--char2", default="FOX")
    r.add_argument("--stage", default="BATTLEFIELD")
    r.add_argument("--mode", default="paused")
    r.add_argument("--games", type=int, default=1)
    r.add_argument("--jobs", type=int, default=6)
    r.add_argument("--cap", type=int, default=0, help="end a game at this frame (0 = play it out)")
    r.add_argument("--timeout", type=int, default=3600)
    r.add_argument("--port0", type=int, default=PORTS[0], help="first Slippi port (parallel runs need disjoint ranges)")
    o = sub.add_parser("one")
    for k in ("iso", "p1", "p2", "char1", "char2", "stage", "mode", "out", "cond"):
        o.add_argument(f"--{k}", required=True)
    o.add_argument("--port", type=int, required=True)
    o.add_argument("--cap", type=int, default=0)
    s = sub.add_parser("summary")
    s.add_argument("dirs", nargs="+")
    pr = sub.add_parser("probe")
    pr.add_argument("dirs", nargs="+")
    pr.add_argument("--model", default="claude-haiku-4-5-20251001")
    pr.add_argument("--base_url", default=None)
    pr.add_argument("--n", type=int, default=100)
    pr.add_argument("--jobs", type=int, default=4)
    pr.add_argument("--seed", type=int, default=0)
    rs = sub.add_parser("rescore")
    rs.add_argument("files", nargs="+")
    b = sub.add_parser("bench")
    b.add_argument("--iso", default=str(Path.home() / "melee.iso"))
    b.add_argument("--out", default=str(ROOT / "replays/perception/bench"))
    b.add_argument("--port", type=int, default=51879)
    b.add_argument("--every", type=int, default=30)
    b.add_argument("--frames", type=int, default=1800)
    b.add_argument("--width", type=int, default=512)
    a = p.parse_args()
    if a.cmd == "run":
        assert a.jobs <= len(PORTS)
        run(a)
    else:
        {"one": one, "summary": summary, "probe": probe, "rescore": rescore, "bench": bench}[a.cmd](a)


if __name__ == "__main__":
    main()
