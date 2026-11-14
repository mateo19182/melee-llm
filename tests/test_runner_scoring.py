"""runner.play's game scoring, against a scripted console: no Dolphin, no ISO."""
import melee

from melee_llm import runner
from melee_llm.agents.base import Agent


def _gs(frame, menu=melee.Menu.IN_GAME, stocks=(4, 4), percent=(0.0, 0.0)):
    gs = melee.GameState(frame=frame, menu_state=menu)
    for port, (s, p) in enumerate(zip(stocks, percent), start=1):
        ps = melee.PlayerState()
        ps.stock, ps.percent = s, p
        gs.players[port] = ps
    return gs


class _Console:
    """Plays back `script`: GameStates, or callables run at that point (to create .slp files)."""
    script: list = []

    def __init__(self, **kwargs):
        self.items = iter(self.script)

    def run(self, iso_path):
        pass

    def connect(self):
        return True

    def stop(self):
        pass

    def step(self):
        for item in self.items:
            if callable(item):
                item()
                continue
            return item
        raise AssertionError("script ran out")


class _Controller:
    def __init__(self, console, port, type):
        pass

    def connect(self):
        return True


class _Counter(Agent):
    def __init__(self):
        super().__init__()
        self.steps = self.ends = 0

    def step(self, gs):
        self.steps += 1

    def on_game_end(self, gs):
        self.ends += 1


def test_timeout_with_tied_stocks_is_scored_at_the_timer_not_on_sudden_death(tmp_path, monkeypatch):
    slp = lambda name: (lambda: (tmp_path / name).write_bytes(b""))
    menu = _gs(0, melee.Menu.POSTGAME_SCORES)
    timed_out = [_gs(f, stocks=(4, 4), percent=(5.7, 0.0)) for f in range(-123, 5)]
    sudden_death = [_gs(f, stocks=(1, 1), percent=(300.0, 300.0)) for f in range(-123, -100)]
    second = [_gs(f, stocks=(3, 0), percent=(10.0, 0.0)) for f in range(-123, -110)]
    _Console.script = [menu, slp("Game_1.slp"), *timed_out, slp("Game_2.slp"), *sudden_death, menu,
                       slp("Game_3.slp"), *second, menu]
    monkeypatch.setattr(runner, "Console", _Console)
    monkeypatch.setattr(melee, "Controller", _Controller)
    monkeypatch.setattr(melee.MenuHelper, "menu_helper_simple", lambda *a, **k: None)
    monkeypatch.setattr(runner, "port_free", lambda port: True)
    monkeypatch.setattr(runner.matches, "publisher", lambda *a: None)
    a, b = _Counter(), _Counter()

    first, then = runner.play({1: a, 2: b}, "iso", mode="fast", games=2, replay_dir=tmp_path)

    assert (first.stocks, first.winner, first.frames) == ({1: 4, 2: 4}, 2, len(timed_out))
    assert first.replay.endswith("Game_1.slp")
    assert (then.stocks, then.winner, then.frames) == ({1: 3, 2: 0}, 1, len(second))
    assert then.replay.endswith("Game_3.slp")  # not the tie-break's file
    assert a.ends == 2 and a.steps == len(timed_out) + len(sudden_death) + len(second)
