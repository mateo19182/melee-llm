"""Offline tests for the Jev client and players (no network, no ISO): uv run --with pytest pytest -q tests/test_jev.py"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx
import melee
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from melee_llm import jev as J  # noqa: E402
from melee_llm.actions import ACTIONS  # noqa: E402


@pytest.fixture(autouse=True)
def fake_key(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key")


def client(handler, **kw) -> J.Jev:
    c = J.Jev(**kw)
    c.http = httpx.Client(base_url="https://x", transport=httpx.MockTransport(handler))
    return c


def answer(choices: dict[str, str], nouls: dict[str, float] | None = None, tokens: int = 1000) -> dict:
    ans = {n: {"type": "choice", "choice": c, "confidence": .5, "probabilities": {c: .6, "other": .4}}
           for n, c in choices.items()}
    ans |= {n: {"type": "noul", "noul": v} for n, v in (nouls or {}).items()}
    return {"model": "jev-1.14.0", "answers": ans, "usage": {"input_tokens": tokens, "output_tokens": 10}}


def test_retry_then_success_and_accounting():
    calls = []

    def handler(req):
        calls.append(json.loads(req.content))
        return httpx.Response(529) if len(calls) == 1 else httpx.Response(200, json=answer({"q": "a"}))

    c = client(handler, retries=2, timeout=1)
    rep = c.ask("s", {"q": J.choice({"a": "A", "b": "B"}, "?")})
    assert rep.ok and rep.attempts == 2 and rep.pick("q") == "a" and rep.model == "jev-1.14.0"
    assert calls[0]["questions"]["q"]["criteria"] == {"a": "A", "b": "B"}
    assert c.stats()["input_tokens"] == 1000 and c.stats()["usd"] == pytest.approx(1000 * J.USD_PER_MTOK / 1e6)
    assert rep.top("q", 1) == [("a", .6)]


def test_auth_error_is_not_retried():
    n = []
    c = client(lambda req: n.append(1) or httpx.Response(401, text="bad key"), retries=3)
    rep = c.ask("s", {"q": J.noul("?")})
    assert not rep.ok and "401" in rep.error and len(n) == 1 and c.stats()["errors"] == 1


def test_choice_limit():
    J.choice({str(i): "" for i in range(255)}, "?")
    with pytest.raises(ValueError):
        J.choice({str(i): "" for i in range(256)}, "?")


def test_player_maps_answers_to_macro(monkeypatch):
    from melee_llm.agents.jev_player import JevPaused
    p = JevPaused("jev-latest,shuffle=0")
    p.brief = {}
    sent = {}

    def handler(req):
        sent.update(json.loads(req.content))
        return httpx.Response(200, json=answer({"action": "fair", "dir": "away", "jump": "full", "frames": "long"},
                                               {"fastfall": .2}))

    p.jev = client(handler)
    rep = p.think("state text\nChoose the next action.")
    assert rep.args["action"] == "fair" and rep.args["dir"] == "away" and rep.args["jump"] == "full"
    assert rep.args["fastfall"] is False and "frames" not in rep.args  # aerials take no frames
    assert set(sent["questions"]["action"]["criteria"]) == set(ACTIONS)
    assert list(sent["questions"]["action"]["criteria"])[0] == "wait"  # shuffle=0 keeps registry order
    assert sent["state"]["situation"] == "state text"
    assert rep.extra["probabilities"]["action"][0] == ("fair", .6)


def test_player_error_falls_back():
    from melee_llm.agents.jev_player import JevLive
    p = JevLive()
    p.brief = {}
    p.jev = client(lambda req: httpx.Response(422, json={"detail": []}), retries=0)
    rep = p.think("x")
    assert rep.args is None and "422" in rep.error
    p.close()


def test_every_action_has_text():
    from melee_llm.agents.jev_player import ACTION_TEXT
    assert set(ACTIONS) <= set(ACTION_TEXT)


@pytest.mark.skipif(not (Path(__file__).parent.parent / "vendor/Reyn/docs/commands.md").exists(), reason="no Reyn")
def test_reyn_menu_fits_one_choice():
    from melee_llm.agents.coach import reyn_commands
    for ch in melee.Character:
        if ch.value < 26:
            try:
                n = len(reyn_commands(ch, melee.Stage.BATTLEFIELD)) + 2  # + keep, none
            except Exception:
                continue
            assert n <= J.MAX_CHOICES
