"""Offline tests for the observation modes (no ISO, no network, no X display)."""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from melee_llm.actions import RecordingController
from melee_llm.agents import llm_common as C
from melee_llm.agents.llm_paused import PausedLLM
from melee_llm.llm import Reply
from melee_llm.runner import replay_states
from melee_llm.vision import Shot

SAMPLE = Path(__file__).resolve().parent.parent / "replays/sample-slippi-js-itemExport.slp"


class FakeCamera:
    def clip(self, frame, n, every):
        return [Shot(b"\xff\xd8jpeg" + bytes([k]), frame - every * (n - 1 - k), (512, 384), 10.0, 2.0) for k in range(n)]

    def tick(self, frame, every):
        pass


def play(tmp_path, obs, answer='{"action": "fair", "dir": "toward"}', clip=1, n=40):
    agent = PausedLLM("m,obs=%s,clip=%d" % (obs, clip), log_dir=tmp_path)
    calls = []
    agent.llm.choose = lambda system, user, tool, images=None: (
        calls.append((system, user, images)) or Reply(json.loads(answer) if answer else None, text=answer or "?", model="m"))
    gss = list(replay_states(SAMPLE))
    p1, p2 = sorted(gss[0].players)[:2]
    agent.setup(RecordingController(), p1, p2)
    if obs != "text":
        agent.camera = FakeCamera()  # setup() builds a real one on $DISPLAY
    for gs in gss[200:200 + n]:
        agent.step(gs)
    log = agent.log.path
    agent.on_game_end(gss[200 + n])
    return calls, [json.loads(ln) for ln in log.read_text().splitlines()], log


def test_text_mode_is_unchanged(tmp_path):
    calls, recs, _ = play(tmp_path, "text")
    system, user, images = calls[0]
    assert images is None and "YOU " in user and C.READ_TEXT in system
    d = next(r for r in recs if r["type"] == "decision")
    assert "images" not in d and d["invalid"] is False


def test_image_mode_sends_legend_and_saves_frames(tmp_path):
    calls, recs, log = play(tmp_path, "image", clip=3)
    system, user, images = calls[0]
    assert "SCREENSHOT LEGEND" in user and "YOU " not in user and "pos (" not in user
    assert C.READ_TEXT not in system and C.READ_IMAGE in system
    assert len(images) == 3 and all(u.startswith("data:image/jpeg;base64,") for u in images)
    d = next(r for r in recs if r["type"] == "decision")
    assert len(d["images"]) == 3 and d["image_tokens_est"] == 3 * round(512 * 384 / 750)
    media = log.with_suffix(".frames")
    assert all((media / i["file"]).exists() for i in d["images"])
    assert recs[0]["obs_mode"] == "image" and recs[-1]["obs_mode"] == "image"


def test_both_mode_keeps_text(tmp_path):
    calls, _, _ = play(tmp_path, "both")
    system, user, images = calls[0]
    assert "YOU " in user and len(images) == 1 and C.READ_BOTH in system


def test_invalid_actions_are_counted(tmp_path):
    _, recs, _ = play(tmp_path, "text", answer='{"action": "teleport"}')
    assert all(r["invalid"] for r in recs if r["type"] == "decision") and recs[-1]["invalid"] > 0


def test_log_rename_moves_frames(tmp_path):
    log = C.DecisionLog(tmp_path, "t")
    log.media_dir().mkdir()
    (log.media_dir() / "f1_1.jpg").write_bytes(b"x")
    time.sleep(0.01)
    (tmp_path / "Game_1.slp").write_bytes(b"")
    path = log.close(1)
    assert path.name == "Game_1.p1.llm.jsonl" and (tmp_path / "Game_1.p1.llm.frames/f1_1.jpg").exists()


def test_bad_obs_mode():
    with pytest.raises(AssertionError):
        PausedLLM("m,obs=video")
