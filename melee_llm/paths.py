"""Where everything lives, and which X display and Slippi port block each track owns.

Code, vendored bots and results all hang off the repo root. `replays/`, `data/`, `bin/` and `vendor/`
are gitignored; the bot-writer keeps its sandboxes outside the repo (BOTWRITER).
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / "vendor"  # learned bots (each with its own venv), Slippi Lab, noVNC
REPLAYS = ROOT / "replays"  # .slp files and the decision logs written next to them
DATA = Path(os.environ.get("MELEE_WEB_DATA", ROOT / "data"))
VOICE_HEARTBEAT = DATA / "voice-listeners"  # touched by Live pages with the commentator voice on
DB = DATA / "web.sqlite"
JOBS = REPLAYS / "jobs"  # one dir per web job: replays, decision logs, results.jsonl, output.log
ARENA = DATA / "arena"  # learned-bot arena: results.jsonl, standings.json
BOTWRITER = Path(os.environ.get("BOTWRITER_HOME", Path.home() / ".local/share/melee-llm/botwriter"))
ISO = os.environ.get("MELEE_ISO", str(Path.home() / "melee.iso"))
VENV_PY = ROOT / ".venv/bin/python"

DOLPHIN_RENDERED = ROOT / "scripts/dolphin-gpu.sh"  # mainline beta.19 through VirtualGL
DOLPHIN_HEADLESS = ROOT / "bin/Slippi_Mainline_ExiAI.AppImage"  # vladfi1 ExiAI build: no rendering, unthrottled

LIVE_DISPLAY = ":99"  # rendered and streamed; one game at a time
HEADLESS_DISPLAY = os.environ.get("MELEE_HEADLESS_DISPLAY", ":98")  # the ExiAI build still wants an X display
LIVE_PORT = 51441
HEADLESS_MAX = 4  # fast web jobs at once

# Slippi spectator ports: the one resource parallel Dolphins share. Each track draws from its own block.
BOTWRITER_PORTS = range(51500, 51600)  # default of $MELEE_SLIPPI_PORTS (botwriter/dolphin.py, flock-claimed)
HEADLESS_PORTS = range(51700, 51800)  # web jobs in fast mode
# scripts/coach_pilot.py takes --port0 (default 51480; the Jev pilot used 51840-51859)
PERCEPTION_PORTS = range(51860, 51880)
LLM_ARENA_PORTS = range(51880, 51920)
BENCH_PORTS = range(51920, 52000)
