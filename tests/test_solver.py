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
    assert names(melee.Action.KNEE_BEND.value) == {"wait", "in", "out", "shine"}
    assert "jump_oos" in names(179) and "jump" not in names(179)  # X alone only drops the shield
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


def test_nash_menus_cover_the_ways_out_of_a_shield():
    from melee_llm.solver import nash
    menu = lambda action: set(nash.MENUS[nash.kind({"action_id": action})])
    assert "spotdodge" in menu(melee.Action.STANDING.value)  # R and down: no shield first
    assert {"jump", "spotdodge"} <= menu(melee.Action.SHIELD_RELEASE.value)  # dropping a shield is not a lock
    assert {"shine", "upb", "usmash", "grab"} <= menu(melee.Action.KNEE_BEND.value)
    assert menu(melee.Action.SPOTDODGE.value) == {"wait"}
    wide = nash.menus_with({"ground": ("usmash", "jab")})["ground"]
    assert wide[-1] == "usmash" and wide.count("jab") == 1 and "usmash" not in nash.MENUS["ground"]


@needs_sim
def test_leaving_shield_near_a_free_fox_loses_to_a_reaction():
    """12.6 units from a standing Fox, every way out of shield is hit by an attacker who reacts one frame late
    (docs/optimal-play.md, section 13): on reaction, or for the spotdodge at its end."""
    from melee_llm.solver import force, nash
    sim = force.Sim()
    s = nash.Nash(force.corner(sim, 14, 12, shield=12), 10, dodge=True)
    sim.world.close()
    for exit_ in ("release", "jump_oos", "roll_out", "spotdodge"):
        s.rb.checkpoint(0)
        s.joint("wait", exit_)
        assert s.forced(1, 9, True), exit_
        s.back(0)
    assert s.value(0, 6) == 0.0  # while he may still hold the shield, nothing is forced


@needs_sim
def test_a_dropped_shield_can_still_spotdodge_and_the_spotdodge_is_hit_at_its_end():
    """The facts behind `Nash.dodged`: 22 frames, the first and the last 7 hittable, no way to cut it short."""
    from melee_llm.solver import force
    from melee_llm.solver.game import A, B, R, Sim
    n, dodge, shine, usmash = (0, 0, 0, 0), (R, 0, -80, 255), (B, 0, -80, 0), (A, 0, 80, 0)
    sim = Sim()
    root = force.corner(sim, 14, 12, shield=12)

    def play(p1: dict, p2: dict, frames: int):
        sim.restore(root)
        seen = []
        for f in range(frames):
            sim.step([p1.get(f, n), p2.get(f, n)])
            seen.append(melee.Action(int(sim.players()[1]["action_id"])))
        return seen, float(sim.players()[0]["percent"]), float(sim.players()[1]["percent"])

    seen, _, _ = play({}, {1: dodge}, 24)  # frame 0 drops the shield, frame 1 dodges out of the drop
    assert seen[0] == melee.Action.SHIELD_RELEASE and seen[1:23] == [melee.Action.SPOTDODGE] * 22
    assert seen[23] == melee.Action.STANDING
    assert play({1: shine}, {}, 3)[2] == 5.0  # the reaction shine hits the drop,
    assert play({1: shine}, {1: dodge}, 12)[2] == 0.0  # not the dodge,
    assert play({1: shine, 8: (0x0400, 0, 0, 0), 10: usmash}, {1: dodge}, 23)[1:] == (0.0, 18.0)  # whose end is hit
    assert play({1: n, 15: usmash}, {0: dodge}, 22)[1:] == (0.0, 18.0)  # as it is for an attacker who only waited
    assert play({1: usmash}, {1: dodge, 23: usmash}, 40)[1:] == (18.0, 0.0)  # a smash on reaction is what loses
    sim.world.close()


@needs_sim
def test_a_grab_counts_as_the_first_hit():
    from melee_llm.solver import force, nash
    sim = force.Sim()
    s = nash.Nash(force.corner(sim, 14, 12), 8)
    sim.world.close()
    s.rb.checkpoint(0)
    s.joint("grab", "wait")
    for _ in range(6):
        assert s.leaf() is None
        s.joint("wait", "wait")
    assert s.leaf() == 1.0  # Fox's standing grab reaches 12.59 on its 7th frame and moves no percent
    s.back(0)


@needs_sim
def test_nash_agrees_with_a_brute_force_on_a_short_horizon():
    """`forced` and `value` against a plain recursion on save and restore: no rollback, no table."""
    from melee_llm.solver import force, nash
    from melee_llm.solver.game import Sim
    sim = Sim()
    root = force.corner(sim, 14, 12, shield=12)
    base = [float(p["percent"]) for p in sim.players()]

    def kids(state):
        sim.restore(state)
        p = sim.players()
        att, dfn = nash._menus(p, nash.MENUS, nash.MENUS, False)
        out = []
        for a in att:
            out.append([])
            for d in dfn:
                sim.restore(state)
                (b, x, y, r), (db, dx, dy, dr) = nash.MOVES[a], nash.MOVES[d]
                sim.step([(b, x, y, r), (db, -dx, dy, dr)])  # P1 is on the left
                d1, d2 = (float(q["percent"]) - b0 + (int(q["action_id"]) in nash._HELD)
                          for q, b0 in zip(sim.players(), base))
                out[-1].append((None, sim.save()) if d1 == d2 == 0 else (float(d2 > 0 and d1 == 0), None))
        return out

    def forced(state, frames, attacking):
        if frames <= 0:
            return not attacking
        rows = kids(state) if attacking else list(zip(*kids(state)))
        return any(all(forced(st, frames - 1, attacking) if v is None else v == float(attacking) for v, st in row)
                   for row in rows)

    def value(state, frames):
        if frames <= 0:
            return 0.0
        return float(matrix.solve(np.array([[value(st, frames - 1) if v is None else v for v, st in row]
                                            for row in kids(state)])).value)

    s = nash.Nash(root, 3)
    for a, d in (("wait", "release"), ("wait", "jump_oos"), ("shine", "spotdodge"), ("jab", "roll_in")):
        sim.restore(root)
        sim.step([nash.MOVES[a], tuple(-v if i == 1 else v for i, v in enumerate(nash.MOVES[d]))])
        state = sim.save()
        s.rb.checkpoint(0)
        s.joint(a, d)
        for frames in (1, 2):
            for attacking in (True, False):
                assert s.forced(1, frames, attacking) == forced(state, frames, attacking), (a, d, frames, attacking)
        assert s.value(1, 1) == pytest.approx(value(state, 1)), (a, d)
        s.back(0)
    sim.world.close()


def test_fortress_attackers_parse_and_ask_for_the_menus_they_need():
    from melee_llm.solver import fortress
    hop = fortress.attacker("hop:14:in:shine:full")
    assert hop.g == 14 and "walk_in" in hop.add1["ground"] and hop.add1["squat"] == ("jump",)
    assert fortress.attacker("dash:16").add1 is None and fortress.attacker("crowd").g == 17
    assert isinstance(fortress.attacker("random:3"), fortress.Random)
    assert isinstance(fortress.attacker("adv:1"), fortress.Adversary)
    assert fortress.PREF[0] == "wait" and set(m for v in fortress.nash.MENUS.values() for m in v) <= set(fortress.PREF)


@needs_sim
def test_fortress_rules_no_shield_near_a_free_fox_and_the_stage_is_the_fortress():
    from melee_llm.solver import force, fortress
    sim = force.Sim()
    near, far, edge = force.corner(sim, 13, 60), force.corner(sim, 30, 60), force.corner(sim, 16, 1)
    sim.world.close()
    fz = fortress.Fortress(near, 6)
    assert "shield" not in fz.menus()[1] and "shield" in fz.menus()[0]
    fz.load(far)
    assert "shield" in fz.menus()[1]
    assert fz.far(1) and not fz.far(6)  # 28.9 apart: out of reach this frame, not for six
    fz.load(edge)
    fz.rb.checkpoint(0)
    for _ in range(3):  # a turn, a dash, and he is in the air past the ledge
        assert fz.leaf() is None
        fz.joint("wait", "out")
    assert fz.leaf() == 1.0 and fz.damage() == (0.0, 0.0)  # off the stage: counted as hit
    fz.back(0)


@needs_sim
def test_fortress_reach_shortcut_agrees_with_the_full_search():
    from melee_llm.solver import force, fortress
    sim = force.Sim()
    roots = [force.corner(sim, g, 60) for g in (22, 26, 32)]
    sim.world.close()
    fast, full = fortress.Fortress(roots[0], 6), fortress.Fortress(roots[0], 6, reach=False)
    for root in roots:
        fast.load(root)
        full.load(root)
        assert fast.safe_moves(4) == full.safe_moves(4)
        assert fast.expansions <= full.expansions
    assert fast.expansions < full.expansions


@needs_sim
def test_fortress_waits_at_the_opening_and_a_hit_never_comes_without_a_crack():
    from melee_llm.solver import force, fortress
    sim = force.Sim()
    start = sim.start()
    sim.world.close()
    fz = fortress.Fortress(start, 6)
    r = fortress.play(fz, fortress.attacker("dash:16"), 60, 4, start)
    assert r["result"] == "survived" and not r["cracks"] and r["shields"] == 0 and r["min_gap"] < 20
    r = fortress.play(fz, fortress.attacker("random:5"), 60, 4, start)
    assert r["result"] in ("survived", "P1 hit") or r["cracks"]


@needs_sim
def test_fortress_marked_positions_count_as_lost_and_a_crack_takes_the_game_back(tmp_path):
    from melee_llm.solver import force, fortress
    sim = force.Sim()
    root = force.corner(sim, 16, 60)
    sim.world.close()
    fz = fortress.Fortress(root, 6)
    assert fz.safe_moves(3)[0] == "wait"
    fz.rb.checkpoint(0)
    fz.joint("wait", "wait")
    fz.mark(str(tmp_path / "bad.jsonl"), "test", 1)  # pretend standing here one frame later is a crack
    fz.back(0)
    assert "wait" not in fz.safe_moves(3)
    other = fortress.Fortress(root, 6)
    other.learn(str(tmp_path / "bad.jsonl"))
    assert other.bad == fz.bad and "wait" not in other.safe_moves(3)
    # in a game the defender then steps around the marked position instead of waiting into it
    r = fortress.play(other, fortress.attacker("dash:0"), 3, 3, root, learn=str(tmp_path / "bad.jsonl"))
    assert r["inputs"][0][1] != "wait" or r["cracks"]
