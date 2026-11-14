"""Bench ratings: one Bradley-Terry fit per track on the Elo scale, cpu:9 pinned at 1500.

The fit is the shared one in melee_llm/ratings.py (MAP with a Gaussian prior, sd 2 per log-strength, draws = half wins). A track's games are
those whose two players both play that track; games between two token-free players (CPUs and bots) count on both
boards, which puts the two scales on the same anchors. CIs: 2.5/97.5 percentiles of bootstrap resamples of games,
refit and re-anchored; the scheduler uses the faster Laplace (inverse Hessian) half-width.
"""
from __future__ import annotations

import statistics
import time
from collections import defaultdict

import numpy as np

from melee_llm.bench.entrants import Entrant, by_id, game_track
from melee_llm.ratings import ELO, PRIOR_SD, fit

ANCHOR, ANCHOR_ELO = "cpu:9", 1500.0
TRACK_NAMES = ("realtime", "untimed")


def score(r: dict) -> float:
    return {1: 1.0, 2: 0.0}.get(r.get("winner"), 0.5)


def track_games(games: list[dict], track: str, entrants: dict[str, Entrant]) -> list[dict]:
    out = []
    for g in games:
        if g.get("status") != "ok" or g["p1"] not in entrants or g["p2"] not in entrants:
            continue
        t = game_track(entrants[g["p1"]], entrants[g["p2"]])
        if t in (track, "shared"):
            out.append(g)
    return out


def precision(pairs: list[tuple[int, int]], th: np.ndarray, n: int) -> np.ndarray:
    """Negative Hessian of the log posterior at `th` (Fisher information of the games plus the prior)."""
    H = np.eye(n) / PRIOR_SD**2
    for a, b in pairs:
        p = 1 / (1 + np.exp(-(th[a] - th[b])))
        w = p * (1 - p)
        H[a, a] += w
        H[b, b] += w
        H[a, b] -= w
        H[b, a] -= w
    return H


class Fit:
    """MAP strengths and Laplace covariance for one track."""

    def __init__(self, games: list[dict], extra_players: list[str] = ()):
        self.games = games
        names = {g["p1"] for g in games} | {g["p2"] for g in games} | set(extra_players) | {ANCHOR}
        self.players = sorted(names)
        self.idx = {p: i for i, p in enumerate(self.players)}
        triples = [(g["p1"], g["p2"], score(g)) for g in games]
        self.th = fit(triples, self.players) if triples else np.zeros(len(self.players))
        self.pairs = [(self.idx[g["p1"]], self.idx[g["p2"]]) for g in games]
        self.H = precision(self.pairs, self.th, len(self.players))
        self.cov = np.linalg.inv(self.H)
        self.a = self.idx[ANCHOR]

    def elo(self, p: str) -> float:
        return ANCHOR_ELO + ELO * (self.th[self.idx[p]] - self.th[self.a])

    def contrast(self, p: str) -> np.ndarray:
        d = np.zeros(len(self.players))
        d[self.idx[p]] += 1
        d[self.a] -= 1
        return d

    def half_width(self, p: str, cov: np.ndarray | None = None) -> float:
        """95% Laplace half-width of p's anchored rating, in Elo (0 for the anchor)."""
        cov = self.cov if cov is None else cov
        d = self.contrast(p)
        return float(1.96 * ELO * np.sqrt(max(d @ cov @ d, 0.0)))

    def p_win(self, a: str, b: str) -> float:
        return float(1 / (1 + np.exp(-(self.th[self.idx[a]] - self.th[self.idx[b]]))))


def bootstrap(games: list[dict], players: list[str], boot: int, seed: int = 0) -> tuple[np.ndarray, np.ndarray]:
    triples = [(g["p1"], g["p2"], score(g)) for g in games]
    rng = np.random.default_rng(seed)
    a = players.index(ANCHOR)
    samples = []
    for _ in range(boot):
        res = [triples[i] for i in rng.integers(0, len(triples), len(triples))]
        th = fit(res, players, iters=30)
        samples.append(ANCHOR_ELO + ELO * (th - th[a]))
    lo, hi = np.percentile(np.array(samples), [2.5, 97.5], axis=0)
    return lo, hi


def record(p: str, games: list[dict]) -> dict:
    w = lost = d = 0
    sd, opp = [], defaultdict(lambda: {"w": 0, "l": 0, "d": 0})
    for g in games:
        for me, op in ((1, 2), (2, 1)):
            if g[f"p{me}"] != p:
                continue
            o = g[f"p{op}"]
            res = "w" if g.get("winner") == me else "l" if g.get("winner") == op else "d"
            w, lost, d = w + (res == "w"), lost + (res == "l"), d + (res == "d")
            opp[o][res] += 1
            st = g.get("stocks") or {}
            if str(me) in st and str(op) in st:
                sd.append(st[str(me)] - st[str(op)])
    n = w + lost + d
    return {"games": n, "wins": w, "losses": lost, "draws": d, "score": round((w + d / 2) / n, 3) if n else None,
            "stock_diff": round(statistics.fmean(sd), 2) if sd else None, "opponents": dict(opp)}


def spend(results: list[dict]) -> dict:
    """Per entrant: bench games with token/cost accounting. CLIProxy tokens (claude, gpt) count against the budget;
    Jev is billed to its own key and reported in USD. Tokens include replies that were never applied (`dropped`);
    pass results through recount.apply() for games logged before those carried their usage."""
    out: dict[str, dict] = defaultdict(lambda: {"games": 0, "prompt": 0, "completion": 0, "usd": 0.0, "calls": 0,
                                                "decisions": 0, "dropped": 0, "tokens_estimated": 0, "errors": 0,
                                                "latency": []})
    for r in results:
        for port, s in (r.get("sides") or {}).items():
            e = r.get(f"p{port}")
            o = out[e]
            o["games"] += 1
            o["prompt"] += s.get("prompt_tokens", 0)
            o["completion"] += s.get("completion_tokens", 0)
            o["usd"] += s.get("usd") or 0.0
            o["calls"] += s.get("calls", 0)
            o["decisions"] += s.get("decisions", 0)
            o["dropped"] += s.get("dropped", 0)
            o["tokens_estimated"] += s.get("tokens_estimated", 0)
            o["errors"] += s.get("errors", 0)
            if s.get("mean_latency_s") is not None:
                o["latency"].append(s["mean_latency_s"])
    for o in out.values():
        lat = o.pop("latency")
        o["mean_latency_s"] = round(statistics.fmean(lat), 2) if lat else None
        o["tokens"] = o["prompt"] + o["completion"]
        replies = o["decisions"] + o["dropped"]
        o["discarded_rate"] = round(o["dropped"] / replies, 3) if replies else None  # replies never applied
        o["tokens_per_game"] = round(o["tokens"] / o["games"]) if o["games"] else None
        o["usd_per_game"] = round(o["usd"] / o["games"], 4) if o["games"] else None
        o["usd"] = round(o["usd"], 4)
    return dict(out)


def standings(results: list[dict], imported: list[dict], excluded: dict | None = None, boot: int = 500,
              target: float = 125.0) -> dict:
    entrants = by_id()
    games = results + imported
    sp = spend(results)
    out = {"generated": round(time.time(), 1), "anchor": {"player": ANCHOR, "elo": ANCHOR_ELO}, "target_half_width": target,
           "method": f"Bradley-Terry MAP per track (Gaussian prior sd {PRIOR_SD} per log-strength), draws = half wins; "
                     f"95% CI = 2.5/97.5 percentiles of {boot} bootstrap resamples of games",
           "games": {"bench": sum(r.get("status") == "ok" for r in results), "imported": len(imported),
                     "by_status": dict(sorted(_count(results).items())), "excluded": excluded or {}},
           "tracks": {}}
    for t in TRACK_NAMES:
        tg = track_games(games, t, entrants)
        f = Fit(tg)
        lo, hi = bootstrap(tg, f.players, boot) if tg and boot else (None, None)
        rows = []
        for i, p in enumerate(f.players):
            e = entrants[p]
            rec = record(p, tg)
            if not rec["games"] and p != ANCHOR:
                continue
            elo = round(f.elo(p))
            row = {"id": p, "elo": elo, "laplace_half": round(f.half_width(p)),
                   "elo_lo": round(float(lo[i])) if lo is not None else None,
                   "elo_hi": round(float(hi[i])) if hi is not None else None, **rec,
                   "imported_games": sum(g.get("imported", False) and p in (g["p1"], g["p2"]) for g in tg)}
            row["half_width"] = 0 if p == ANCHOR else max(row["laplace_half"], (row["elo_hi"] - row["elo_lo"]) / 2
                                                          if lo is not None else 0)
            row["converged"] = row["half_width"] <= target
            rows.append(row)
        rows.sort(key=lambda r: -r["elo"])
        out["tracks"][t] = {"games": len(tg), "players": rows}
    out["spend"] = sp
    out["entrants"] = {k: e.view() for k, e in entrants.items()}
    return out


def _count(results: list[dict]) -> dict:
    c: dict[str, int] = defaultdict(int)
    for r in results:
        c[r.get("status", "?")] += 1
    return c
