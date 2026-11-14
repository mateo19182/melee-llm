"""Offline checks of the bench: spec resolution, track assignment, the fit, and one scheduling decision."""
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from melee_llm.bench import entrants, ratings, scheduler


def test_resolve_and_tracks():
    ents = entrants.by_id()
    assert entrants.resolve("coach:haiku,interval=300", ents) == "coach:claude-haiku-4-5-20251001"
    assert entrants.resolve("coach:haiku,interval=60", ents) is None
    assert entrants.resolve("coach_jev:,interval=300", ents) == "coach_jev"
    assert entrants.resolve("agent:melee_llm.bots:Phillip:gm", ents) == "phillip:gm"
    assert entrants.resolve("jev_live", ents) == "jev_live"
    live, paused, cpu = ents["llm_live:gpt-6-luna"], ents["llm_paused:gpt-6-luna"], ents["cpu:9"]
    assert entrants.game_track(live, cpu) == "realtime" and entrants.game_mode(live, cpu) == "realtime"
    assert entrants.game_track(paused, cpu) == "untimed" and entrants.game_mode(paused, cpu) == "fast"
    assert entrants.game_track(live, paused) is None
    assert entrants.game_track(cpu, ents["faynt"]) == "shared"


def test_fit_recovers_order():
    rng = random.Random(0)
    true = {"cpu:9": 0.0, "cpu:5": -1.0, "faynt": 1.5}
    games = []
    for _ in range(300):
        a, b = rng.sample(sorted(true), 2)
        p = 1 / (1 + 2.718281828 ** -(true[a] - true[b]))
        games.append({"p1": a, "p2": b, "winner": 1 if rng.random() < p else 2, "status": "ok"})
    f = ratings.Fit(games)
    assert f.elo("faynt") > 1500 > f.elo("cpu:5")
    assert abs(f.elo("cpu:9") - 1500) < 1e-6 and f.half_width("faynt") > 0


def test_pick_returns_a_feasible_job(tmp_path, monkeypatch):
    monkeypatch.setattr(scheduler, "_gpu_free_mb", lambda: 20000)
    monkeypatch.setattr(scheduler, "_unit_active", lambda unit: False)
    b = scheduler.Bench(scheduler.Config(), tmp_path)
    job = b.pick()
    assert job and job["p1"] != job["p2"] and job["mode"] in ("fast", "realtime")
    assert job["track"] in ("realtime", "untimed", "shared")
