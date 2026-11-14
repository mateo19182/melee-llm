"""Evaluation ladder: every entrant plays every roster opponent, N games per (stage, side).

  python -m melee_llm.botwriter.ladder run   --config ladder.json
  python -m melee_llm.botwriter.ladder board --out DIR        # recompute leaderboard.json

Config (JSON):
  {"entrants": {"opus-5/run1": "path/to/bot.py", ...},          # name "<model>/<run>" groups runs
   "roster": ["cpu:1", ..., "cpu:9", "baseline:rusher", ...],        # main score
   "hard_tier": ["agent:melee_llm.bots:HAL:MASTER", ...],            # learned bots, scored separately
   "stages": ["FINAL_DESTINATION", "BATTLEFIELD"], "character": "FOX", "allowed_characters": ["FOX"],
   "games_per_side": 2, "hard_games_per_side": 1, "workers": 8, "budget_ms": 16, "iso": "...", "out": "DIR",
   "entrants_play_each_other": false, "calibrate_roster": false, "anchor": "cpu:1", "job_timeout_s": 1800}

Games append to DIR/games.jsonl (re-running resumes); DIR/leaderboard.json holds the scores.
Primary score = mean over roster opponents of the entrant's win rate (draw = half), so it does
not depend on who else is in the field. `hard_score` is the same over the hard tier (learned bots).
A Bradley-Terry fit over all games gives Elo-scale ratings. `hard_games_per_side` (default: same as
`games_per_side`) lets the hard tier run fewer games. Raising either later just plays the extra games.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import multiprocessing as mp
import signal
import statistics
import time
import traceback
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from melee_llm.ratings import elo_ratings

DEFAULTS = {"stages": ["FINAL_DESTINATION", "BATTLEFIELD"], "character": "FOX", "allowed_characters": ["FOX"],
            "games_per_side": 2, "workers": 4, "budget_ms": 16.0, "entrants_play_each_other": False,
            "calibrate_roster": False, "hard_games_per_side": None, "anchor": "cpu:1", "job_timeout_s": 1800,
            "roster": [f"cpu:{i}" for i in range(1, 10)] + ["baseline:laser", "baseline:rusher", "baseline:shine"],
            "hard_tier": ["agent:melee_llm.bots:HAL:MASTER", "agent:melee_llm.bots:Phillip:gm",
                          "agent:melee_llm.bots:MIMIC", "agent:melee_llm.bots:Faynt"]}


def load_config(path: str | Path) -> dict:
    cfg = {**DEFAULTS, **json.loads(Path(path).read_text())}
    cfg["out"] = str(Path(cfg.get("out") or Path(path).with_suffix("")).expanduser().resolve())
    cfg["entrants"] = {k: str(Path(v).expanduser().resolve()) for k, v in cfg.get("entrants", {}).items()}
    if cfg.get("iso"):
        cfg["iso"] = str(Path(cfg["iso"]).expanduser())
    return cfg


def player_spec(cfg: dict, name: str) -> str:
    return f"bot:{cfg['entrants'][name]}" if name in cfg["entrants"] else name


def make_jobs(cfg: dict) -> list[dict]:
    entrants, roster = list(cfg["entrants"]), list(cfg["roster"]) + list(cfg["hard_tier"])
    pairs = [(e, r) for e in entrants for r in roster]
    if cfg["entrants_play_each_other"]:
        pairs += [(a, b) for i, a in enumerate(entrants) for b in entrants[i + 1:]]
    if cfg["calibrate_roster"]:
        pairs += [(a, b) for i, a in enumerate(roster) for b in roster[i + 1:]]
    jobs, hard = [], set(cfg["hard_tier"])
    for a, b in pairs:
        games = (cfg["hard_games_per_side"] or cfg["games_per_side"]) if b in hard else cfg["games_per_side"]
        for stage in cfg["stages"]:
            for a_port in (1, 2):
                key = f"{a}|{b}|{stage}|p{a_port}"
                jobs.append({"key": key, "a": a, "b": b, "stage": stage, "a_port": a_port,
                             "games": games, "id": hashlib.sha1(key.encode()).hexdigest()[:12]})
    return jobs


# --- worker side ------------------------------------------------------------------------------
_PORT = None


def _alarm(*_):
    raise TimeoutError("job exceeded job_timeout_s")


def run_job(job: dict, cfg: dict) -> list[dict]:
    global _PORT
    import melee

    from melee_llm.botwriter.dolphin import claim_slippi_port, exit_on_term
    from melee_llm.botwriter.specs import make_agent
    from melee_llm.runner import play
    from melee_llm.util import claim_slot

    if _PORT is None:
        _PORT = claim_slippi_port()
        exit_on_term()
    out = Path(cfg["out"])
    char = melee.Character[cfg["character"]]
    allowed = {melee.Character[c] for c in cfg["allowed_characters"]}
    logs = out / "logs" / job["id"]
    logs.mkdir(parents=True, exist_ok=True)
    base = {"job": job["key"], "a": job["a"], "b": job["b"], "stage": job["stage"], "a_port": job["a_port"]}
    agents, side = {}, {}
    try:
        for who, port in (("a", job["a_port"]), ("b", 3 - job["a_port"])):
            try:
                ag = make_agent(player_spec(cfg, job[who]), char, cfg["budget_ms"], logs)
                if ag.cpu_level == 0 and ag.character not in allowed:
                    raise ValueError(f"character {ag.character.name} not allowed")
            except Exception as e:
                for other in agents.values():
                    other.close()
                if job[who] not in cfg["entrants"]:
                    raise  # a broken roster opponent is an infrastructure error, not a free win
                winner = "b" if who == "a" else "a"
                return [{**base, "game": i, "winner": winner, "forfeit": who, "reason": f"{type(e).__name__}: {e}"[:500],
                         "ts": time.time()} for i in range(job["games"])]
            agents[port], side[port] = ag, who
        rdir = out / "replays" / job["id"]
        with claim_slot():  # waiting for a slot is not part of the job's time limit
            signal.signal(signal.SIGALRM, _alarm)
            signal.alarm(int(cfg["job_timeout_s"]))
            results = play(agents, cfg["iso"], melee.Stage[job["stage"]], mode="fast", games=job["games"], replay_dir=rdir,
                           slippi_port=_PORT)
            signal.alarm(0)
        recs = []
        for i, r in enumerate(results):
            stats = {side[p]: (agents[p].game_stats[i] if i < len(getattr(agents[p], "game_stats", [])) else None) for p in agents}
            recs.append({**base, "game": i, "winner": side.get(r.winner) if r.winner else None,
                         "stocks": {side[p]: int(r.stocks[p]) for p in agents},
                         "percent": {side[p]: round(float(r.percent[p]), 1) for p in agents},
                         "frames": r.frames, "seconds": round(r.seconds, 1), "bot_stats": stats,
                         "replay": r.replay, "slippi_port": _PORT, "ts": time.time()})
        return recs
    except Exception:
        signal.alarm(0)
        for ag in agents.values():  # play() closes them itself; this covers failures before it starts
            ag.close()
        return [{**base, "error": traceback.format_exc(limit=8), "ts": time.time()}]


# --- scoring ----------------------------------------------------------------------------------
def read_games(out: Path) -> list[dict]:
    path = out / "games.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()] if path.exists() else []


def wilson(score: float, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    c = (score + z * z / (2 * n)) / (1 + z * z / n)
    h = z * math.sqrt(score * (1 - score) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return (round(max(0.0, c - h), 3), round(min(1.0, c + h), 3))


def leaderboard(cfg: dict, games: list[dict]) -> dict:
    played = [g for g in games if "error" not in g]
    pairs = [(g["a"], g["b"], 1.0 if g["winner"] == "a" else 0.0 if g["winner"] == "b" else 0.5) for g in played]
    elo = {k: round(v, 1) for k, v in elo_ratings(pairs, cfg["anchor"]).items()}
    roster = list(cfg["roster"])
    rows = {}
    for e in cfg["entrants"]:
        vs = defaultdict(list)
        flags = defaultdict(int)
        for g in played:
            if e not in (g["a"], g["b"]):
                continue
            me = "a" if g["a"] == e else "b"
            opp = g["b"] if me == "a" else g["a"]
            vs[opp].append(1.0 if g["winner"] == me else 0.5 if g["winner"] is None else 0.0)
            if g.get("forfeit") == me:
                flags["forfeits"] += 1
            st = (g.get("bot_stats") or {}).get(me) or {}
            for k in ("late", "skipped", "exceptions", "policy_violations"):
                flags[k] += int(st.get(k) or 0)
            flags["crashes"] += bool(st.get("crashed"))
            flags["frames"] += int(st.get("frames") or 0)
        per_opp = {o: round(statistics.fmean(s), 3) for o, s in vs.items()}

        def tier(opps):
            rates = [per_opp[o] for o in opps if o in per_opp]
            score = statistics.fmean(rates) if rates else 0.0
            ci = wilson(score, sum(len(vs[o]) for o in opps if o in vs))
            return score, [round(100 * x, 1) for x in ci], len(rates)

        score, ci, _ = tier(roster)
        hard, hard_ci, hard_n = tier(cfg["hard_tier"])
        level = 0  # highest CPU level with every lower roster CPU also beaten at least half the time
        for lvl in sorted(int(o[4:]) for o in roster if o.startswith("cpu:")):
            if per_opp.get(f"cpu:{lvl}", 0) >= 0.5:
                level = lvl
            else:
                break
        rows[e] = {"roster_score": round(100 * score, 1), "roster_score_ci95": ci,
                   "hard_score": round(100 * hard, 1) if hard_n else None, "hard_score_ci95": hard_ci if hard_n else None,
                   "elo": elo.get(e), "cpu_ladder_level": level, "games": sum(map(len, vs.values())),
                   "vs": per_opp, "integrity": dict(flags), "flagged": bool(flags["policy_violations"] or flags["forfeits"])}
    models = defaultdict(list)
    for e, r in rows.items():
        models[e.split("/")[0]].append(r)
    by_model = {m: {"runs": len(rs), "roster_score_mean": round(statistics.fmean(r["roster_score"] for r in rs), 1),
                    "roster_score_sd": round(statistics.pstdev([r["roster_score"] for r in rs]), 1),
                    "hard_score_mean": round(statistics.fmean(r["hard_score"] or 0 for r in rs), 1),
                    "elo_mean": round(statistics.fmean(r["elo"] or 0 for r in rs), 1),
                    "best_run_score": max(r["roster_score"] for r in rs)} for m, rs in models.items()}
    return {"updated": time.strftime("%Y-%m-%dT%H:%M:%S"), "config": {k: cfg[k] for k in ("stages", "character", "games_per_side", "hard_games_per_side", "budget_ms", "roster", "hard_tier", "anchor")},
            "games": len(played), "errors": len(games) - len(played),
            "models": dict(sorted(by_model.items(), key=lambda kv: -kv[1]["roster_score_mean"])),
            "entrants": dict(sorted(rows.items(), key=lambda kv: -kv[1]["roster_score"])),
            "roster_elo": {r: elo.get(r) for r in roster + list(cfg["hard_tier"])}}


def run(cfg: dict) -> dict:
    if not cfg.get("iso") or not Path(cfg["iso"]).is_file():
        raise SystemExit("config needs an existing 'iso' path")
    out = Path(cfg["out"])
    out.mkdir(parents=True, exist_ok=True)
    done = defaultdict(int)
    for g in read_games(out):
        if "error" not in g:
            done[g["job"]] += 1
    todo = [j for j in make_jobs(cfg) if done[j["key"]] < j["games"]]
    for j in todo:
        j["games"] -= done[j["key"]]
    print(f"{len(todo)} jobs to run ({sum(j['games'] for j in todo)} games) on {cfg['workers']} Dolphins")
    with ProcessPoolExecutor(cfg["workers"], mp_context=mp.get_context("spawn")) as pool, open(out / "games.jsonl", "a") as f:
        futs = {pool.submit(run_job, j, cfg): j for j in todo}
        for i, fut in enumerate(as_completed(futs), 1):
            recs = fut.result()
            for r in recs:
                f.write(json.dumps(r) + "\n")
            f.flush()
            bad = [r for r in recs if "error" in r]
            print(f"[{i}/{len(todo)}] {futs[fut]['key']}: " + ("ERROR " + bad[0]["error"].splitlines()[-1] if bad else
                  " ".join(str(r.get("winner")) for r in recs)), flush=True)
    board = leaderboard(cfg, read_games(out))
    (out / "leaderboard.json").write_text(json.dumps(board, indent=1))
    return board


def main() -> None:
    ap = argparse.ArgumentParser(prog="ladder")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--config", required=True)
    r.add_argument("--dry-run", action="store_true", help="list jobs without playing")
    b = sub.add_parser("board")
    b.add_argument("--config", required=True)
    a = ap.parse_args()
    cfg = load_config(a.config)
    if a.cmd == "run" and a.dry_run:
        for j in make_jobs(cfg):
            print(j["key"], j["games"])
        return
    board = run(cfg) if a.cmd == "run" else leaderboard(cfg, read_games(Path(cfg["out"])))
    if a.cmd == "board":
        (Path(cfg["out"]) / "leaderboard.json").write_text(json.dumps(board, indent=1))
    print(json.dumps({k: board[k] for k in ("games", "errors", "models")}, indent=1))


if __name__ == "__main__":
    main()
