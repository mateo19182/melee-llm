"""Job queue in SQLite (data/web.sqlite). The web server adds and cancels jobs; the worker runs them."""
from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

from melee_llm.web.paths import DB, JOBS

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created REAL NOT NULL,
  status TEXT NOT NULL,              -- queued | running | done | failed | cancelled
  lane TEXT NOT NULL,                -- live (display :99, port 51441) | headless (display :98, pool)
  p1 TEXT NOT NULL, p2 TEXT NOT NULL, char1 TEXT NOT NULL, char2 TEXT NOT NULL,
  stage TEXT NOT NULL, mode TEXT NOT NULL, games INTEGER NOT NULL,
  preempt INTEGER NOT NULL DEFAULT 0, -- live jobs: abort the running arena game instead of waiting for it
  started REAL, finished REAL, pid INTEGER, port INTEGER,
  cancel INTEGER NOT NULL DEFAULT 0, error TEXT,
  results TEXT NOT NULL DEFAULT '[]', -- one GameResult dict per finished game
  tokens TEXT                        -- {"prompt": n, "completion": n, "by_model": {...}} from the decision logs
);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""
FIELDS = ("p1", "p2", "char1", "char2", "stage", "mode", "games", "preempt")


@contextmanager
def connect(path: Path = DB):
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.executescript(SCHEMA)
    try:
        yield db
        db.commit()
    finally:
        db.close()


def row(r: sqlite3.Row | None) -> dict | None:
    if r is None:
        return None
    d = dict(r)
    d["results"] = json.loads(d["results"] or "[]")
    d["tokens"] = json.loads(d["tokens"]) if d["tokens"] else None
    d["dir"] = str(job_dir(d["id"]))
    return d


def job_dir(job_id: int) -> Path:
    return JOBS / str(job_id)


def add(spec: dict) -> dict:
    lane = "headless" if spec["mode"] == "fast" else "live"
    with connect() as db:
        cur = db.execute(f"INSERT INTO jobs (created, status, lane, {', '.join(FIELDS)}) VALUES (?, 'queued', ?, "
                         f"{', '.join('?' * len(FIELDS))})", (time.time(), lane, *(spec[k] for k in FIELDS)))
        return row(db.execute("SELECT * FROM jobs WHERE id = ?", (cur.lastrowid,)).fetchone())


def get(job_id: int) -> dict | None:
    with connect() as db:
        return row(db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone())


def listing(limit: int = 100) -> list[dict]:
    with connect() as db:
        active = db.execute("SELECT * FROM jobs WHERE status IN ('queued', 'running') ORDER BY id").fetchall()
        done = db.execute("SELECT * FROM jobs WHERE status NOT IN ('queued', 'running') ORDER BY id DESC LIMIT ?",
                          (limit,)).fetchall()
        return [row(r) for r in active + done]


def queued(lane: str) -> list[dict]:
    with connect() as db:
        return [row(r) for r in db.execute("SELECT * FROM jobs WHERE status = 'queued' AND lane = ? ORDER BY id",
                                           (lane,)).fetchall()]


def update(job_id: int, **fields) -> None:
    for k in ("results", "tokens"):
        if k in fields and not isinstance(fields[k], str):
            fields[k] = json.dumps(fields[k])
    with connect() as db:
        db.execute(f"UPDATE jobs SET {', '.join(f'{k} = ?' for k in fields)} WHERE id = ?", (*fields.values(), job_id))


def cancel(job_id: int) -> dict | None:
    """Queued jobs are cancelled at once; running ones are flagged and the worker kills them."""
    with connect() as db:
        db.execute("UPDATE jobs SET status = 'cancelled', finished = ? WHERE id = ? AND status = 'queued'",
                   (time.time(), job_id))
        db.execute("UPDATE jobs SET cancel = 1 WHERE id = ? AND status = 'running'", (job_id,))
        return row(db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone())


def setting(key: str, default: str = "") -> str:
    with connect() as db:
        r = db.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return r["value"] if r else default


def set_setting(key: str, value: str) -> None:
    with connect() as db:
        db.execute("INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                   (key, value))
