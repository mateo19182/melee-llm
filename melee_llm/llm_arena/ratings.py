"""Bradley-Terry ratings on the Elo scale, anchored to the CPU, with game-bootstrap CIs; per-model stats."""
from __future__ import annotations

import json
import statistics
import time
from pathlib import Path

import numpy as np

from melee_llm.ratings import ELO, PRIOR_SD, fit

ANCHOR, ANCHOR_ELO = "cpu:9", 1500.0


def outcomes(rows: list[dict]) -> list[tuple[str, str, float]]:
    """(p1 name, p2 name, p1 score) per rated game; a draw scores 0.5."""
    from melee_llm.llm_arena.tournament import player_name
    out = []
    for r in rows:
        s = {1: 1.0, 2: 0.0}.get(r["winner"], 0.5)
        out.append((player_name(r["p1"]), player_name(r["p2"]), s))
    return out


def elo(games, players, anchor: str) -> np.ndarray:
    th = fit(games, players)
    return ANCHOR_ELO + ELO * (th - th[players.index(anchor)])


def standings(rows: list[dict], boot: int = 1000, seed: int = 0) -> dict:
    rated = [r for r in rows if r.get("status") == "ok"]
    games = outcomes(rated)
    players = sorted({p for g in games for p in g[:2]}, key=lambda p: (p.startswith("cpu:"), p))
    anchor = ANCHOR if ANCHOR in players else next((p for p in players if p.startswith("cpu:")), players[0] if players else None)
    res = {"generated": round(time.time(), 1), "anchor": {"player": anchor, "elo": ANCHOR_ELO},
           "method": f"Bradley-Terry MAP (Gaussian prior sd {PRIOR_SD} per log-strength), draws = half wins; "
                     f"95% CI = 2.5/97.5 percentiles of {boot} bootstrap resamples of games",
           "games": {k: sum(r.get("status") == k for r in rows) for k in ("ok", "void", "error", "timeout")},
           "tokens": {"prompt": 0, "completion": 0}, "players": [], "matrix": {}}
    for r in rows:
        for s in (r.get("sides") or {}).values():
            res["tokens"]["prompt"] += s["prompt_tokens"]
            res["tokens"]["completion"] += s["completion_tokens"]
    if not games:
        return res
    point = elo(games, players, anchor)
    rng = np.random.default_rng(seed)
    samples = np.array([elo([games[i] for i in rng.integers(0, len(games), len(games))], players, anchor)
                        for _ in range(boot)])
    lo, hi = np.percentile(samples, [2.5, 97.5], axis=0)
    for i, p in enumerate(players):
        res["players"].append({"player": p, "kind": "cpu" if p.startswith("cpu:") else "llm",
                               "elo": round(float(point[i])), "elo_lo": round(float(lo[i])), "elo_hi": round(float(hi[i])),
                               **record(p, rated), "stats": model_stats(p, rows)})
    res["players"].sort(key=lambda x: -x["elo"])
    for a, b, s in games:
        for x, y, v in ((a, b, s), (b, a, 1 - s)):
            cell = res["matrix"].setdefault(x, {}).setdefault(y, {"w": 0, "l": 0, "d": 0})
            cell["w" if v == 1 else "l" if v == 0 else "d"] += 1
    return res


def record(p: str, rated: list[dict]) -> dict:
    """W/L/D, mean stock and percent differential (own minus opponent's stocks; opponent's minus own percent)."""
    from melee_llm.llm_arena.tournament import player_name
    w = lost = d = 0
    sd, pd = [], []
    for r in rated:
        names = {1: player_name(r["p1"]), 2: player_name(r["p2"])}
        for me, op in ((1, 2), (2, 1)):
            if names[me] != p or names[op] == p:
                continue
            w += r["winner"] == me
            lost += r["winner"] == op
            d += r["winner"] is None
            sd.append(r["stocks"][str(me)] - r["stocks"][str(op)])
            pd.append(r["percent"][str(op)] - r["percent"][str(me)])
    n = w + lost + d
    return {"games": n, "wins": w, "losses": lost, "draws": d, "score": round((w + d / 2) / n, 3) if n else None,
            "stock_diff": round(statistics.fmean(sd), 2) if sd else None,
            "percent_diff": round(statistics.fmean(pd), 1) if pd else None}


def model_stats(p: str, rows: list[dict]) -> dict | None:
    """Decision stats over every finished game the model played (void games included: they are real calls)."""
    from melee_llm.llm_arena.tournament import player_name
    sides = [s for r in rows for port, s in (r.get("sides") or {}).items()
             if player_name(r["p1" if port == "1" else "p2"]) == p]
    if not sides:
        return None
    n = len(sides)
    dec = sum(s["decisions"] for s in sides)
    lat = [s["mean_latency_s"] for s in sides if s["mean_latency_s"] is not None]
    actions: dict[str, int] = {}
    for s in sides:
        for k, v in s["actions"].items():
            actions[k] = actions.get(k, 0) + v
    tot = sum(actions.values()) or 1
    return {"games": n, "decisions_per_game": round(dec / n, 1),
            "mean_latency_s": round(statistics.fmean(lat), 2) if lat else None,
            "mean_think_s": round(statistics.fmean(s["mean_think_s"] for s in sides if s["mean_think_s"] is not None), 2),
            "tokens_per_game": round(sum(s["prompt_tokens"] + s["completion_tokens"] for s in sides) / n),
            "prompt_tokens": sum(s["prompt_tokens"] for s in sides),
            "completion_tokens": sum(s["completion_tokens"] for s in sides),
            "invalid": sum(s["invalid"] for s in sides), "invalid_rate": round(sum(s["invalid"] for s in sides) / max(dec, 1), 4),
            "api_failed": sum(s["api_failed"] for s in sides), "api_retries": sum(s["api_retries"] for s in sides),
            "actions": {k: round(v / tot, 3) for k, v in sorted(actions.items(), key=lambda kv: -kv[1])}}


def markdown(st: dict) -> str:
    lines = [f"Anchor: {st['anchor']['player']} = {st['anchor']['elo']:.0f}. {st['method']}.",
             f"Games: {st['games']}. Tokens: {st['tokens']['prompt']:,} prompt + {st['tokens']['completion']:,} completion.", "",
             "| # | Player | Elo | 95% CI | G | W-L-D | Score | Stock diff | % diff | Dec/game | Latency s | Tok/game | Invalid | Top actions |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for i, p in enumerate(st["players"], 1):
        s = p["stats"] or {}
        inv = f"{s['invalid_rate']:.1%}" if s else ""
        top = ", ".join(f"{k} {v:.0%}" for k, v in list(s.get("actions", {}).items())[:4])
        lines.append(f"| {i} | {p['player']} | {p['elo']} | {p['elo_lo']}–{p['elo_hi']} | {p['games']} | "
                     f"{p['wins']}-{p['losses']}-{p['draws']} | {p['score']} | {p['stock_diff']:+} | {p['percent_diff']:+} | "
                     f"{s.get('decisions_per_game', '')} | {s.get('mean_latency_s', '')} | {s.get('tokens_per_game', '')} | "
                     f"{inv} | {top} |".replace("| None |", "| |"))
    names = [p["player"] for p in st["players"]]
    lines += ["", "Head to head (row's W-L-D against column):", "", "| | " + " | ".join(names) + " |",
              "|---|" + "---|" * len(names)]
    for a in names:
        cells = []
        for b in names:
            c = st["matrix"].get(a, {}).get(b)
            cells.append(f"{c['w']}-{c['l']}-{c['d']}" if c else "")
        lines.append(f"| {a} | " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def write(out: Path, boot: int = 1000) -> dict:
    from melee_llm.llm_arena.tournament import read_results
    st = standings(read_results(out / "results.jsonl"), boot)
    (out / "standings.json").write_text(json.dumps(st, indent=1))
    (out / "standings.md").write_text(markdown(st))
    return st
