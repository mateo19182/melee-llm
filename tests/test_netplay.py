"""Offline tests for melee_llm.netplay (no Dolphin, no Slippi account). Run: uv run --with pytest pytest -q tests/"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import melee  # noqa: E402

from melee_llm.netplay.host import HostConfig, _find_port, _winner, bot_code, check, normalize_code  # noqa: E402


def test_normalize_code():
    assert normalize_code(" abcd#123 ") == "ABCD#123"
    assert normalize_code("ab-1") == "AB#1"
    for bad in ("ABCD", "ABCD#", "AB CD#1", "ABCDEFGH#1"):
        with pytest.raises(ValueError):
            normalize_code(bad)


def test_check(tmp_path):
    uj = tmp_path / "user.json"
    uj.write_text(json.dumps({"uid": "u", "playKey": "k", "connectCode": "BOT#1"}))
    assert bot_code(uj) == "BOT#1"
    base = dict(connect_code="ABCD#123", iso=__file__, user_json=str(uj), display=":98")
    problems = lambda **kw: check(HostConfig(**{**base, "opponent": "hal", **kw}))  # noqa: E731
    if Path("/tmp/.X11-unix/X98").exists():
        assert problems() == []
    assert any("cpu" in p for p in problems(opponent="cpu:9"))
    assert any("llm_live" in p for p in problems(opponent="llm_paused:x"))
    assert any("own code" in p for p in problems(connect_code="bot#1"))
    assert any("missing" in p for p in problems(user_json=str(tmp_path / "nope.json")))


def test_find_port_and_winner():
    fox, falco = melee.Character.FOX, melee.Character.FALCO
    pl = lambda ch, code: SimpleNamespace(character=ch, costume=0, connectCode=code)  # noqa: E731
    gs = SimpleNamespace(players={1: pl(fox, "ABCD#123"), 2: pl(fox, "BOT#1")})
    assert _find_port(gs, "BOT#1", fox, 0) == 2  # ditto: only the code can tell
    assert _find_port(gs, "", fox, 0) == 0
    gs = SimpleNamespace(players={1: pl(fox, ""), 2: pl(falco, "")})
    assert _find_port(gs, "BOT#1", falco, 0) == 2  # fallback: character and costume
    assert _winner({1: 2, 2: 1}, {1: 50, 2: 0}, 1, 2) == "bot"
    assert _winner({1: 1, 2: 1}, {1: 20, 2: 10}, 1, 2) == "human"
    assert _winner({1: 1, 2: 1}, {1: 10, 2: 10}, 1, 2) is None
