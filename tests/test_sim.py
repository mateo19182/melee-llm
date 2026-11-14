"""melee_llm.sim: controller conversion (offline), and against melee-sim-light when it and its data are installed."""
import glob
from pathlib import Path

import melee
import numpy as np
import pytest
from melee.controller import fix_analog_stick

from melee_llm.sim import world
from melee_llm.sim.controller import SimController

RAW_ROW = np.dtype([("buttons", "<u2"), ("main_x", "i1"), ("main_y", "i1"), ("c_x", "i1"), ("c_y", "i1"),
                    ("l", "u1"), ("r", "u1")])


def _raw(c: SimController) -> np.void:
    row = np.zeros((), RAW_ROW)
    c.raw_input(row)
    return row


def test_sticks_and_triggers_land_on_the_values_dolphin_gives_the_game():
    c = SimController(1)
    for x in np.linspace(0, 1, 161):
        c.tilt_analog(melee.Button.BUTTON_MAIN, x, 1 - x)
        c.press_shoulder(melee.Button.BUTTON_L, x)
        row = _raw(c)
        # libmelee's own target: the raw value Console.step reports back for an input x
        assert (row["main_x"], row["main_y"]) == (round((x - 0.5) * 160), round((0.5 - x) * 160))
        assert row["l"] == round(x * 140)


def test_buttons_use_the_gamecube_bit_layout():
    c = SimController(1)
    c.press_button(melee.Button.BUTTON_A)
    c.press_button(melee.Button.BUTTON_Z)
    c.press_button(melee.Button.BUTTON_D_UP)
    assert _raw(c)["buttons"] == 0x0100 | 0x0010 | 0x0008
    c.release_all()
    row = _raw(c)
    assert (row["buttons"], row["main_x"], row["c_y"], row["l"], row["r"]) == (0, 0, 0, 0, 0)


def test_unfixed_controller_values_convert_the_same_way_dolphin_reads_them():
    c = SimController(1, fix_analog_inputs=False)
    c.tilt_analog(melee.Button.BUTTON_C, fix_analog_stick(1.0), fix_analog_stick(0.25))
    assert (_raw(c)["c_x"], _raw(c)["c_y"]) == (80, -40)


needs_sim = pytest.mark.skipif(not world.available(), reason="melee-sim-light's game data is not extracted (docs/simulator.md)")


@needs_sim
def test_play_runs_agents_and_scores_the_game(monkeypatch):
    import melee_llm.sim.runner as sim
    from melee_llm.agents.base import Idle, Multishine
    monkeypatch.setenv("MELEE_MATCHES", "0")
    monkeypatch.setattr(sim, "TIMER_FRAMES", 600)
    seen = []
    [r] = sim.play({1: Idle(), 2: Multishine()}, melee.Stage.FINAL_DESTINATION, 1, seed=7,
                   observer=lambda event, info: seen.append(event))
    assert r.frames > 600 and r.stocks == {1: 4, 2: 4} and r.winner is None
    assert seen[0] == "game_start" and seen[-1] == "game_end" and seen.count("frame") == r.frames


@needs_sim
def test_cpu_players_are_refused():
    import melee_llm.sim.runner as sim
    from melee_llm.agents.base import CPU, Idle
    with pytest.raises(ValueError, match="CPU"):
        sim.play({1: CPU(9), 2: Idle()})


_REPLAYS = sorted(glob.glob(str(Path(__file__).parents[1] / "replays/bench/*/2026-11-Mainline/*.slp")))


@needs_sim
@pytest.mark.skipif(not _REPLAYS or __import__("importlib").util.find_spec("peppi_py") is None,
                    reason="needs a Dolphin bench replay and peppi-py")
def test_gamestates_match_libmelee_on_a_dolphin_replay():
    import peppi_py

    from melee_llm.sim.parity import compare
    # CPU inputs are recorded processed, not raw, so only games between controller-driven players replay
    slp = next(f for f in _REPLAYS if all(p.type.name == "HUMAN" for p in peppi_py.read_slippi(f, skip_frames=True).start.players))
    r = compare(Path(slp))
    assert r["compared"] > 1000
    # hitstun_frames_left is the one known difference: libmelee reports Melee's shared slot outside hitstun
    assert set(r["mismatches"]) <= {"hitstun_frames_left"}, r["examples"]
