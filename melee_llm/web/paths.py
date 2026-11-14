"""Shared locations and constants for the web UI, the worker and the job processes."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = Path(os.environ.get("MELEE_WEB_DATA", ROOT / "data"))  # gitignored
DB = DATA / "web.sqlite"
LIVE = DATA / "live.json"  # what the live slot is playing right now (written by the job/arena process)
JOBS = ROOT / "replays/jobs"  # one dir per job: replays, decision logs, results.jsonl, output.log
ARENA = ROOT / "arena"
BOTWRITER = Path(os.environ.get("BOTWRITER_HOME", Path.home() / ".local/share/melee-llm/botwriter"))
ISO = os.environ.get("MELEE_ISO", str(Path.home() / "melee.iso"))
VENV_PY = ROOT / ".venv/bin/python"

LIVE_DISPLAY, LIVE_PORT = ":99", 51441
HEADLESS_PORTS = range(51700, 51800)
HEADLESS_MAX = 4
