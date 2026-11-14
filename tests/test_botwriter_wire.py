"""BotAgent's wire to its bot process: the GameState a bot receives, and the begin/step split."""
import math
import pickle
from pathlib import Path

import numpy as np

from melee_llm.botwriter.agent import BotAgent, sanitize
from melee_llm.botwriter.host import _SLOTTED, FakeController, dumps
from melee_llm.runner import replay_states

ROOT = Path(__file__).resolve().parent.parent
SAMPLE = ROOT / "replays/sample-slippi-js-itemExport.slp"  # Falco vs Samus: projectiles, stock loss
RUSHER = ROOT / "melee_llm/botwriter/baselines/rusher.py"


def _same(a, b, path="gs"):
    assert type(a) is type(b), path
    if isinstance(a, (list, tuple)):
        assert len(a) == len(b), path
        for i, (x, y) in enumerate(zip(a, b)):
            _same(x, y, f"{path}[{i}]")
    elif isinstance(a, dict):
        assert a.keys() == b.keys(), path
        for k in a:
            _same(a[k], b[k], f"{path}.{k}")
    elif type(a) in _SLOTTED:
        for k in _SLOTTED[type(a)]:
            assert hasattr(a, k) == hasattr(b, k), f"{path}.{k}"
            if hasattr(a, k):
                _same(getattr(a, k), getattr(b, k), f"{path}.{k}")
    elif isinstance(a, (float, np.floating)) and math.isnan(a):
        assert math.isnan(b), path
    else:
        assert a == b, path


def test_bots_receive_the_same_gamestate_as_plain_pickle():
    states = [sanitize(gs, 2) for gs in replay_states(SAMPLE)]
    assert any(gs.projectiles for gs in states)
    for gs in states[::5]:
        _same(pickle.loads(pickle.dumps(gs)), pickle.loads(dumps(gs)))


def test_bot_answers_through_begin_and_step_or_step_alone(tmp_path):
    states = list(replay_states(SAMPLE))[:300]
    bot, moved = BotAgent(RUSHER, budget_ms=None, log_path=tmp_path / "bot.log"), 0
    try:
        bot.setup(FakeController(1), 1, 2)
        for i, gs in enumerate(states):
            if i % 2:
                bot.begin(gs)
            bot.step(gs)
            moved += bot.controller.current.main_stick != (0.5, 0.5)
        bot.on_game_end(states[-1])
    finally:
        bot.close()
    stats = bot.game_stats[0]
    assert (stats["frames"], stats["answered"], stats["exceptions"], stats["crashed"]) == (300, 300, 0, False)
    assert bot.seq == 300 and moved > 0
