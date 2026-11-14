"""The one rating fit: Bradley-Terry on the Elo scale, for the bench, both arenas and the bot-writer ladder.

MAP estimate with a Gaussian prior on each log-strength, draws counted as half wins. The prior keeps a player
with only wins or only losses finite; ratings are reported relative to an anchor player.
"""
from __future__ import annotations

import numpy as np

ELO = 400 / np.log(10)  # natural BT units → Elo points
PRIOR_SD = 2.0  # Gaussian prior on each log-strength (≈350 Elo): keeps all-win/all-loss records finite


def fit(games: list[tuple[str, str, float]], players: list[str], iters: int = 50) -> np.ndarray:
    """MAP Bradley-Terry log-strengths by Newton's method."""
    idx = {p: i for i, p in enumerate(players)}
    n = len(players)
    a = np.array([idx[g[0]] for g in games], dtype=int)
    b = np.array([idx[g[1]] for g in games], dtype=int)
    s = np.array([g[2] for g in games])
    th = np.zeros(n)
    for _ in range(iters):
        p = 1 / (1 + np.exp(-(th[a] - th[b])))
        grad = -th / PRIOR_SD**2
        np.add.at(grad, a, s - p)
        np.add.at(grad, b, p - s)
        w = p * (1 - p)
        H = -np.eye(n) / PRIOR_SD**2
        np.add.at(H, (a, a), -w)
        np.add.at(H, (b, b), -w)
        np.add.at(H, (a, b), w)
        np.add.at(H, (b, a), w)
        step = np.linalg.solve(H, grad)
        th -= step
        if np.abs(step).max() < 1e-9:
            break
    return th


def elo_ratings(games: list[tuple[str, str, float]], anchor: str | None = None, anchor_elo: float = 0.0,
                players: list[str] = ()) -> dict[str, float]:
    """Rating of every player in `games` (plus `players`) from (a, b, score of a) triples, `anchor` set to `anchor_elo`.

    Without the anchor among the players the scale is centred by the prior alone."""
    names = sorted({p for g in games for p in g[:2]} | set(players))
    th = fit(games, names) if games else np.zeros(len(names))
    base = th[names.index(anchor)] if anchor in names else 0.0
    return {p: float(anchor_elo + ELO * (th[i] - base)) for i, p in enumerate(names)}
