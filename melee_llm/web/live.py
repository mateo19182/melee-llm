"""The text strip under the live video (drawn by scripts/stream.sh), written by whatever owns display :99.

What the live slot is playing comes from the match registry (melee_llm.matches, read by web/registry.py).
"""
from __future__ import annotations

from pathlib import Path

from melee_llm.util import write_atomic
from melee_llm.web.specs import char_name, label, stage_name

OVERLAY = Path("/tmp/melee-arena/overlay.txt")


def write_overlay(text: str) -> None:
    write_atomic(OVERLAY, text)


def match_text(p1: str, p2: str, char1: str, char2: str, stage: str, tag: str, game: int = 0, games: int = 1) -> str:
    of = f"   |   game {game + 1}/{games}" if games > 1 else ""
    return (f"{label(p1)} ({char_name(char1)})  vs  {label(p2)} ({char_name(char2)})"
            f"   |   {stage_name(stage)}   |   {tag}{of}")
