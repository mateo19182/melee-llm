"""Exact solution of a two-player zero-sum matrix game: the value and both players' optimal (mixed) strategies.

The row player maximizes `A[i, j]`, the column player minimizes it. Solved as the textbook linear program
(shift A positive, then maximize sum(y) subject to A y <= 1, y >= 0) with a dense tableau simplex: our matrices
are at most a few dozen rows, so no LP library is needed.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

_EPS = 1e-9


@dataclass(frozen=True)
class Solution:
    value: float
    row: np.ndarray  # row player's mixed strategy
    col: np.ndarray  # column player's mixed strategy


def solve(a: np.ndarray) -> Solution:
    a = np.asarray(a, dtype=float)
    m, n = a.shape
    saddle = _saddle(a)
    if saddle is not None:
        return saddle
    shift = 1.0 - a.min()
    b = a + shift  # every entry >= 1, so the game value is positive
    # Tableau: m constraint rows [b | I | 1], objective row [-1 | 0 | 0]; slack basis is feasible at y = 0.
    t = np.zeros((m + 1, n + m + 1))
    t[:m, :n], t[:m, n:n + m], t[:m, -1] = b, np.eye(m), 1.0
    t[m, :n] = -1.0
    basis = list(range(n, n + m))
    while True:
        enter = next((j for j in range(n + m) if t[m, j] < -_EPS), None)  # Bland's rule: no cycling
        if enter is None:
            break
        col = t[:m, enter]
        ratios = [(t[i, -1] / col[i], basis[i], i) for i in range(m) if col[i] > _EPS]
        _, _, leave = min(ratios)
        t[leave] /= t[leave, enter]
        for i in range(m + 1):
            if i != leave and abs(t[i, enter]) > 0:
                t[i] -= t[i, enter] * t[leave]
        basis[leave] = enter
    y = np.zeros(n)
    for i, v in enumerate(basis):
        if v < n:
            y[v] = t[i, -1]
    x = t[m, n:n + m].copy()  # duals of the slack rows are the row player's weights
    total = y.sum()
    return Solution(1.0 / total - shift, _norm(x), _norm(y))


def payoff(a: np.ndarray, row: np.ndarray, col: np.ndarray) -> float:
    return float(row @ np.asarray(a, dtype=float) @ col)


def _saddle(a: np.ndarray) -> Solution | None:
    """A pure-strategy equilibrium, which most of our nodes have (one side has nothing that matters)."""
    i = int(np.argmax(a.min(axis=1)))
    j = int(np.argmin(a.max(axis=0)))
    if a[i].min() < a[:, j].max() - _EPS:
        return None
    row, col = np.zeros(a.shape[0]), np.zeros(a.shape[1])
    row[i], col[j] = 1.0, 1.0
    return Solution(float(a[i, j]), row, col)


def _norm(v: np.ndarray) -> np.ndarray:
    v = np.clip(v, 0.0, None)
    return v / v.sum()
