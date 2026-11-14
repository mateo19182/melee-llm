"""Coach pilot: run conditions (coached, uncoached, fixed-command, random-coach Reyn) in parallel and summarise.

    uv run scripts/coach_pilot.py run --iso ~/melee.iso --out replays/coach-pilot/A --jobs 4 \
        --cond "coach:haiku,interval=120" --cond reyn --cond "coach:random,interval=120" --games 4
    uv run scripts/coach_pilot.py summary replays/coach-pilot/A

Each game runs in its own process with its own Slippi port (51480-51499 by default) and replay dir, so the
coach log and replay lookup never see another game's files. Results go to <out>/results.jsonl; behaviour
metrics come from the player's frames in the .slp.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from melee_llm.util import append_jsonl, run_game_process  # noqa: E402


def behaviour(slp: str, port: int, opp: int) -> dict:
    """Per-game action mix and spacing for `port`, from the replay."""
    import melee

    from melee_llm.runner import replay_states
    from melee_llm.state import AERIALS, DEAD, GRABBED, LASER_IDS, SHIELDING, SHINE_IDS, UPB_IDS
    n, dist, cats, opp_moved, prev_x, opp_cpu = 0, [], Counter(), 0, None, None
    for gs in replay_states(slp):
        if gs.frame < 0 or port not in gs.players:
            continue
        me, op = gs.players[port], gs.players[opp]
        opp_cpu = int(op.cpu_level)  # a CPU left at level 0 stands still all game: such games are invalid
        opp_moved += prev_x is not None and abs(float(op.position.x) - prev_x) > 0.01
        prev_x = float(op.position.x)
        if me.action in DEAD or op.action in DEAD:
            continue
        n += 1
        dist.append(abs(float(me.position.x - op.position.x)))
        v = getattr(me.action, "value", -1)
        a = me.action
        cats["laser"] += v in LASER_IDS
        cats["shine"] += v in SHINE_IDS
        cats["upb"] += v in UPB_IDS
        cats["shield"] += a in SHIELDING
        cats["aerial"] += a in AERIALS
        cats["grab"] += a in (melee.Action.GRAB, melee.Action.GRAB_RUNNING, melee.Action.GRAB_WAIT)
        cats["opp_grabbed"] += op.action in GRABBED
        cats["airborne"] += not me.on_ground
        cats["platform"] += me.on_ground and float(me.position.y) > 5
        cats["offstage"] += bool(me.off_stage)
        cats["taunt"] += a == melee.Action.TAUNT_LEFT or a == melee.Action.TAUNT_RIGHT
    n = max(n, 1)
    return {"frames": n, "opp_cpu_level": opp_cpu, "opp_moved_frac": round(opp_moved / n, 3), "mean_dx": round(statistics.fmean(dist), 1) if dist else None,
            "median_dx": round(statistics.median(dist), 1) if dist else None,
            **{f"frac_{k}": round(v / n, 4) for k, v in sorted(cats.items())}}


def one(a) -> None:
    import melee

    from melee_llm.players import make
    from melee_llm.runner import play
    from melee_llm.util import exit_on_term
    exit_on_term()  # so play()'s cleanup stops Dolphin and the bot
    out = Path(a.out)
    p1 = make(a.p1, a.char1, out)
    agents = {1: p1, 2: make(a.p2, a.char2)}
    t0 = time.time()
    [r] = play(agents, a.iso, melee.Stage[a.stage], a.mode, 1, replay_dir=out, slippi_port=a.port)
    rec = {"cond": a.cond, "p1": a.p1, "p2": a.p2, "char1": a.char1, "char2": a.char2, "stage": a.stage,
           "mode": a.mode, "wall_s": round(time.time() - t0, 1), **asdict(r)}
    body = getattr(p1, "body", p1)
    if hasattr(body, "latency"):
        rec["body_latency"] = body.latency()
    logs = sorted(out.rglob("*.coach.jsonl"))
    if logs:
        rec["coach_log"] = str(logs[-1])
        rec["coach"] = json.loads(logs[-1].read_text().splitlines()[-1])
    if r.replay:
        rec["behaviour"] = behaviour(r.replay, 1, 2)
    print(json.dumps(rec, default=float))


def run(a) -> None:
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    jobs = [(c, i, s) for i in range(a.games) for c in a.cond for s in a.stage]
    free = list(range(a.port0, a.port0 + a.jobs))
    results = out / "results.jsonl"
    env = {**os.environ, "DISPLAY": a.display}

    started = []

    def go(job, attempt=0):
        cond, i, stage = job
        port = free.pop()
        started.append(time.time())
        time.sleep(max(0.0, 8 * (len(started) - 1) - (time.time() - started[0])) if len(started) <= a.jobs else 0)
        retry = False
        try:
            gdir = out / f"{cond.replace(':', '_').replace(',', '_').replace(' ', '_')[:60]}-{stage}-{i}"
            gdir.mkdir(parents=True, exist_ok=True)
            cmd = [sys.executable, __file__, "one", "--iso", a.iso, "--p1", cond, "--p2", a.p2, "--char1", a.char1,
                   "--char2", a.char2, "--stage", stage, "--mode", a.mode, "--port", str(port), "--out", str(gdir),
                   "--cond", cond]
            r, stdout, stderr, timed_out = run_game_process(cmd, a.timeout, env, grace=20)
            if timed_out:
                print(f"{cond} {stage} #{i}: TIMEOUT", flush=True)
                return
            (gdir / "stderr.log").write_text(stderr + stdout)
            if r:
                append_jsonl(results, r)
                print(f"{cond:40s} {stage:18s} stocks {r['stocks']} pct {r['percent']} winner {r['winner']} "
                      f"{r['frames']}f {r['wall_s']}s", flush=True)
            else:
                retry = attempt == 0 and "could not connect" in stderr
                print(f"{cond} {stage} #{i}: FAILED{', retrying' if retry else ''} (see {gdir}/stderr.log)", flush=True)
        finally:
            free.append(port)
        if retry:
            go(job, 1)

    with ThreadPoolExecutor(a.jobs) as pool:
        list(pool.map(go, jobs))


def summary(a) -> None:
    rows = [json.loads(ln) for f in a.dirs for ln in (Path(f) / "results.jsonl").open()]
    by, invalid = {}, []
    for r in rows:
        if r.get("replay") and "opp_cpu_level" not in r.get("behaviour", {}):
            r["behaviour"] = behaviour(r["replay"], 1, 2)
        b = r.get("behaviour", {})
        if r["p2"].startswith("cpu") and (b.get("opp_cpu_level") != int(r["p2"].split(":")[1])
                                          or b.get("opp_moved_frac", 0) < 0.1):
            invalid.append(f"{r['cond']} {r['stage']} {r.get('replay')}")
            continue
        by.setdefault((r["cond"], r["p2"]), []).append(r)
    keys = ("mean_dx", "frac_laser", "frac_shield", "frac_aerial", "frac_grab", "frac_airborne", "frac_platform",
            "frac_offstage")
    print(f"{'condition':42s} {'vs':10s} n  W  L  D  stockdiff  pctdiff  " + " ".join(k.removeprefix('frac_')[:8] for k in keys))
    for (cond, p2), rs in sorted(by.items()):
        w = sum(r["winner"] == 1 for r in rs)
        lo = sum(r["winner"] == 2 for r in rs)
        sd = [r["stocks"]["1"] - r["stocks"]["2"] for r in rs]
        pdiff = [r["percent"]["2"] - r["percent"]["1"] for r in rs]
        beh = [r.get("behaviour", {}) for r in rs]
        cols = []
        for k in keys:
            v = [b[k] for b in beh if b.get(k) is not None]
            cols.append(f"{statistics.fmean(v):8.3f}" if v else "       -")
        print(f"{cond:42s} {p2:10s} {len(rs):<2d} {w:<2d} {lo:<2d} {len(rs) - w - lo:<2d} "
              f"{statistics.fmean(sd):+6.2f}    {statistics.fmean(pdiff):+6.0f}   " + " ".join(cols))
        coach = [r["coach"] for r in rs if r.get("coach")]
        if coach:
            lat = [c["mean_latency_s"] for c in coach if c.get("mean_latency_s")]
            print(f"    coach: decisions {sum(c['decisions'] for c in coach)}, changes {sum(c['changes'] for c in coach)}, "
                  f"abstained {sum(c['abstained'] for c in coach)}, errors {sum(c['errors'] for c in coach)}, "
                  f"mean latency {statistics.fmean(lat) if lat else 0:.2f}s, tokens "
                  f"{sum(c['prompt_tokens'] for c in coach)}/{sum(c['completion_tokens'] for c in coach)}")
        lat = [r["body_latency"]["round_trip_ms"] for r in rs if r.get("body_latency", {}).get("round_trip_ms")]
        print(f"    frames mean {statistics.fmean(r['frames'] for r in rs):.0f}, stocks lost {sum(4 - r['stocks']['1'] for r in rs):.0f}, "
              f"stocks taken {sum(4 - r['stocks']['2'] for r in rs):.0f}")
        if lat:
            print(f"    body round trip ms: p50 {statistics.fmean(x['p50'] for x in lat):.1f} "
                  f"p99 {statistics.fmean(x['p99'] for x in lat):.1f} max {max(x['max'] for x in lat):.0f}; "
                  f"fps {statistics.fmean(r['frames'] / r['wall_s'] for r in rs):.0f}")
    for line in invalid:
        print(f"EXCLUDED (CPU opponent inactive): {line}")


def main() -> None:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--iso", required=True)
    r.add_argument("--out", required=True)
    r.add_argument("--cond", action="append", required=True, help="p1 spec")
    r.add_argument("--p2", default="cpu:9")
    r.add_argument("--char1", default="FOX")
    r.add_argument("--char2", default="FOX")
    r.add_argument("--stage", action="append", default=None)
    r.add_argument("--mode", default="lockstep")
    r.add_argument("--games", type=int, default=1)
    r.add_argument("--jobs", type=int, default=4)
    r.add_argument("--port0", type=int, default=51480)
    r.add_argument("--display", default=":98")
    r.add_argument("--timeout", type=int, default=900)
    o = sub.add_parser("one")
    for k in ("iso", "p1", "p2", "char1", "char2", "stage", "mode", "out", "cond"):
        o.add_argument(f"--{k}", required=True)
    o.add_argument("--port", type=int, required=True)
    s = sub.add_parser("summary")
    s.add_argument("dirs", nargs="+")
    a = p.parse_args()
    if a.cmd == "run":
        a.stage = a.stage or ["BATTLEFIELD"]
        assert a.display != ":99" and not (a.port0 <= 51441 < a.port0 + a.jobs), "never touch the arena's :99/51441"
        run(a)
    elif a.cmd == "one":
        one(a)
    else:
        summary(a)


if __name__ == "__main__":
    main()
