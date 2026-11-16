"""melee_llm.solver: the matrix-game solver offline, and the shine facts optimal-play.md rests on in melee-sim-light."""
import melee
import numpy as np
import pytest

from melee_llm.sim import world
from melee_llm.solver import matrix

needs_sim = pytest.mark.skipif(not world.available(), reason="melee-sim-light's game data is not extracted (docs/simulator.md)")


def test_matching_pennies_is_an_even_mix_worth_zero():
    sol = matrix.solve(np.array([[1.0, -1.0], [-1.0, 1.0]]))
    assert sol.value == pytest.approx(0.0)
    assert sol.row == pytest.approx([0.5, 0.5]) and sol.col == pytest.approx([0.5, 0.5])


def test_a_saddle_point_is_found_pure():
    sol = matrix.solve(np.array([[3.0, 1.0], [4.0, 2.0]]))
    assert sol.value == pytest.approx(2.0) and sol.row.tolist() == [0, 1] and sol.col.tolist() == [0, 1]


@needs_sim
def test_same_frame_shines_clank_on_the_ground_whiff_in_the_air_and_one_frame_earlier_wins():
    from melee_llm.solver.game import Sim
    from melee_llm.solver.probe import trial
    sim = Sim()
    st = sim.setup(8)
    ground = trial(sim, st, "shine", "shine")
    assert ground.hit == [None, None] and ground.clank == 1
    air = trial(sim, st, "shine", "shine", air=6)
    assert air.hit == [None, None] and air.clank is None
    early = trial(sim, st, "shine", "shine", delay2=1)
    assert early.hit[1] == 1 and early.hit[0] is None and early.pct[1] == 5.0
    sim.world.close()


@needs_sim
def test_yoshis_double_jump_armor_takes_the_shine_without_knockback():
    from melee_llm.solver.game import NONE, Sim, X, move
    sim = Sim(melee.Character.YOSHI, melee.Character.FOX, (60, 0))
    sim.restore(sim.setup(12))
    shine, air = move("shine"), 0
    for f in range(30):
        a, b = sim.players()
        if not int(a["on_ground"]):
            air += 1
        jump = (X, 80, 0, 0, 0, 0) if f == 0 or air == 2 else NONE
        sim.step([jump, shine(f - 12, -1, b) if f >= 12 else NONE])
    a, _ = sim.players()
    assert float(a["percent"]) == 65.0 and int(a["hitstun"]) == 0
    assert melee.Action(int(a["action_id"])).name.startswith("JUMPING_ARIAL")
    sim.world.close()


def test_force_menus_follow_the_fighter_state():
    from melee_llm.solver import force
    names = lambda action: {force.NAMES[i] for i in force.menu({"action_id": action})}
    assert {"shine", "hop_in", "shield2"} <= names(melee.Action.STANDING.value)
    assert names(melee.Action.KNEE_BEND.value) == {"wait", "in", "out"}
    assert "roll_out" in names(melee.Action.SHIELD.value) and "shine" not in names(melee.Action.SHIELD.value)
    assert names(melee.Action.DOWN_B_GROUND.value) == {"wait", "hold_b", "jump"}
    assert names(melee.Action.GRABBED.value) == {"wait"}
    assert all(len(rows) == frames for frames, rows in force.MOVES.values())


def test_rollback_reproduces_the_game_exactly():
    """Needs the simulator's game data."""
    from melee_brute import rollback
    if not world.available():
        pytest.skip("patched melee-sim-light with game data not installed")
    from melee_llm.solver import force
    from melee_llm.solver.game import Sim
    sim = Sim()
    s = force.Search(force.corner(sim, 12, 12))
    sim.world.close()
    rng = np.random.default_rng(3)
    for _ in range(20):
        s.rb.checkpoint(0)
        seq = [tuple(rng.integers(len(force._WARMUP), size=2)) for _ in range(6)]
        for i, j in seq:
            s.step(force._WARMUP[i], force._WARMUP[j])
        first = s.env.save(0)
        s.back(0)
        for i, j in seq:
            s.step(force._WARMUP[i], force._WARMUP[j])
        assert s.env.save(0) == first
        s.back(0)
    assert len(s.rb.verify()) == 0
