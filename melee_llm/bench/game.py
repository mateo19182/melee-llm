"""One bench game, run as a child process: build both players, play one full game, print the result as JSON.

Fox vs Fox, 4 stocks, 8 minutes. `fast` mode for untimed and token-free games (the game waits for every input);
`realtime` (headless, 60 fps cap) when a player decides on the wall clock. llm_paused players are wrapped in
llm_arena's ArenaLLM for its transport retries, with no frame cap.
"""
from __future__ import annotations

import signal
import sys
import time
from dataclasses import asdict
from pathlib import Path

VOID_API_FAILED_FRAC = 0.10  # a side whose calls failed this often → void (infrastructure, not play)
MIN_FPS = 50.0  # a realtime game slower than this gives wall-clock players extra game time → "slow", not rated


def make_agent(spec: str, out: Path):
    import melee

    kind, _, arg = spec.partition(":")
    if kind in ("bot", "baseline"):
        from melee_llm.botwriter.specs import make_agent as bw_make
        return bw_make(spec, melee.Character.FOX, budget_ms=16.0, log_dir=out)
    if kind == "llm_paused":
        from melee_llm.llm_arena.agent import ArenaLLM
        a = ArenaLLM(arg, cap_frames=0, retries=4)
    else:
        from match import make
        a = make(spec, "FOX")
    a.character = melee.Character.FOX
    if hasattr(a, "log_dir"):
        a.log_dir = out
    return a


def side_stats(out: Path, port: int, agent=None) -> dict | None:
    """Token use and decision health of one port, from its decision log(s); None for players with no log.

    Every call's tokens count, applied or not: `dropped` replies (a live player's stale or superseded replies, a
    call still in flight at game end) carry their usage. Logs from before 2026-11-14 wrote dropped records
    without usage; those are estimated at the log's mean tokens per applied call (`tokens_estimated`)."""
    from melee_llm.web.logs import price, read
    logs = sorted(out.rglob(f"*.p{port}.llm.jsonl")) + sorted(out.rglob(f"*.p{port}.coach.jsonl"))
    if not logs:
        return None
    s = {"log": str(logs[-1]), "decisions": 0, "dropped": 0, "calls": 0, "errors": 0, "invalid": 0,
         "prompt_tokens": 0, "completion_tokens": 0, "tokens_estimated": 0, "usd": None}
    model, lat, usd = "", [], 0.0
    for path in logs:
        unmetered = 0  # dropped records without usage (old logs)
        dec_pt = dec_ct = dec_calls = 0
        for r in read(path):
            t = r.get("type")
            if t == "game_start":
                model = r.get("model") or r.get("coach") or model
            elif t == "jev_stats":
                usd += r.get("usd") or 0.0
            elif t in ("decision", "dropped"):
                s["decisions" if t == "decision" else "dropped"] += 1
                if t == "dropped" and "prompt_tokens" not in r:
                    unmetered += 1
                    continue
                pt, ct = r.get("prompt_tokens") or 0, r.get("completion_tokens") or 0
                s["prompt_tokens"] += pt
                s["completion_tokens"] += ct
                s["calls"] += bool(pt or ct)
                if t == "decision":
                    dec_pt, dec_ct, dec_calls = dec_pt + pt, dec_ct + ct, dec_calls + bool(pt or ct)
                    failed = r.get("reply_mode") == "error" or (bool(r.get("error")) and not (pt or ct))
                    s["errors"] += failed
                    s["invalid"] += bool(r.get("invalid"))
                    if r.get("latency_s") is not None and not failed:
                        lat.append(float(r["latency_s"]))
        if unmetered and dec_calls:
            ept, ect = round(unmetered * dec_pt / dec_calls), round(unmetered * dec_ct / dec_calls)
            s["prompt_tokens"] += ept
            s["completion_tokens"] += ect
            s["tokens_estimated"] += ept + ect
            s["calls"] += unmetered
    s["model"] = model
    s["mean_latency_s"] = round(sum(lat) / len(lat), 3) if lat else None
    s["usd"] = round(usd, 5) if usd else price(model, s["prompt_tokens"], s["completion_tokens"])
    if hasattr(agent, "summary") and hasattr(agent, "api_failed"):  # ArenaLLM: failures after its retries
        s["errors"], s["api_retries"] = agent.api_failed, agent.api_retries
    return s


def play_one(job: dict, iso: str, port: int, out: Path) -> dict:
    import melee

    from melee_llm.runner import play

    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))  # play()'s cleanup stops Dolphin and the bots
    out.mkdir(parents=True, exist_ok=True)
    agents = {1: make_agent(job["spec1"], out), 2: make_agent(job["spec2"], out)}
    meta = {"source": "bench", "label": f"Bench {job['p1']} vs {job['p2']}", "specs": {1: job["spec1"], 2: job["spec2"]},
            "bench_id": job["id"]}
    t0 = time.time()
    [r] = play(agents, iso, melee.Stage[job["stage"]], job["mode"], 1, replay_dir=out, slippi_port=port, meta=meta)
    sides = {}
    for p, a in agents.items():
        s = side_stats(out, p, a)
        if s:
            sides[str(p)] = s
    bot_stats = {str(p): a.game_stats[-1] for p, a in agents.items() if getattr(a, "game_stats", None)}
    res = asdict(r)
    fps = round(r.frames / r.seconds, 1) if r.seconds else None
    return {**res, "fps": fps, "wall_s": round(time.time() - t0, 1), "sides": sides, "bot_stats": bot_stats or None}


def status_of(rec: dict) -> str:
    for s in (rec.get("sides") or {}).values():
        if s["decisions"] and s["errors"] / s["decisions"] > VOID_API_FAILED_FRAC:
            return "void"
    if rec.get("mode") == "realtime" and (rec.get("fps") or 0) < MIN_FPS:
        return "slow"
    return "ok"
