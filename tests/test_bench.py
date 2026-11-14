"""Offline checks of the bench: spec resolution, track assignment, the fit, and one scheduling decision."""
import random

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


def test_timeouts_retired_and_decided_pairings():
    # a game with no recorded winner goes to more stocks, then lower percent
    assert ratings.winner({"winner": None, "stocks": {"1": 2, "2": 3}}) == 2
    assert ratings.winner({"winner": None, "stocks": {"1": 2, "2": 2}, "percent": {"1": 40.0, "2": 90.5}}) == 1
    assert ratings.winner({"winner": None, "stocks": {"1": 2, "2": 2}, "percent": {"1": 0.0, "2": 0.0}}) is None
    ents = entrants.by_id()
    g = lambda a, b, w: {"p1": a, "p2": b, "winner": w, "status": "ok"}
    games = [g("faynt", "phillip:gm", 1)] * 8 + [g("cpu:9", "cpu:7", 1)] * 7 + [g("cpu:7", "cpu:9", 1)] + \
            [g("baseline:rusher", "cpu:9", 1)] * 5
    rated = ratings.rated_games(games, ents)
    assert len(rated) == 16  # the retired scripted bot's games are left out
    assert ratings.decided_pairs(rated) == {frozenset(("faynt", "phillip:gm"))}
    st = ratings.standings(games, [], boot=0)
    rows = {r["id"]: r for r in st["board"]["players"]}
    assert "baseline:rusher" not in rows and rows["faynt"]["bound"] == "lower" and rows["cpu:7"]["bound"] is None
    assert [r["id"] for r in st["tracks"]["untimed"]["players"]] == [r["id"] for r in st["board"]["players"]]


def test_control_players_need_no_model():
    import random as rnd

    from melee_llm.actions import ACTIONS
    from melee_llm.agents.llm_common import random_decision
    from melee_llm.agents.llm_paused import PausedLLM

    rng = rnd.Random(0)
    assert all(random_decision(rng)["action"] in ACTIONS for _ in range(200))
    p = PausedLLM("random")
    assert p.llm is None and p.think("state").args["action"] in ACTIONS
    ents = entrants.by_id()
    assert ents["llm_live:none"].provider == "none" and ents["llm_paused:random"].group == "control"


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
    assert "retired" not in (b.entrants[job["p1"]].group, b.entrants[job["p2"]].group)


def test_spend_counts_discarded_replies(tmp_path):
    """Dropped replies' tokens count; old logs without usage on dropped records are estimated per call."""
    import json

    from melee_llm.bench.game import side_stats

    def log(name, recs):
        (tmp_path / name).write_text("\n".join(json.dumps(r) for r in recs) + "\n")

    start = {"type": "game_start", "model": "claude-haiku-4-5-20251001"}
    dec = {"type": "decision", "prompt_tokens": 1000, "completion_tokens": 50, "latency_s": 1.0}
    log("g.p1.llm.jsonl", [start, dec, dec, {"type": "dropped", "why": "stale", "prompt_tokens": 900,
                                              "completion_tokens": 40}])
    s = side_stats(tmp_path, 1)
    assert (s["decisions"], s["dropped"], s["calls"]) == (2, 1, 3)
    assert s["prompt_tokens"] + s["completion_tokens"] == 2 * 1050 + 940 and s["tokens_estimated"] == 0
    log("g.p2.llm.jsonl", [start, dec, {"type": "dropped", "stale_frames": 200}, {"type": "dropped"}])
    s2 = side_stats(tmp_path, 2)
    assert s2["dropped"] == 2 and s2["tokens_estimated"] == 2 * 1050
    assert s2["prompt_tokens"] + s2["completion_tokens"] == 3 * 1050

    res = [{"id": "g", "p1": "llm_live:claude-haiku-4-5-20251001", "p2": "cpu:9", "sides": {"1": s}},
           {"id": "h", "p1": "llm_live:claude-haiku-4-5-20251001", "p2": "cpu:9", "sides": {"1": s2}}]
    sp = ratings.spend(res)["llm_live:claude-haiku-4-5-20251001"]
    assert sp["tokens"] == 2 * 1050 + 940 + 3 * 1050 and sp["discarded_rate"] == round(3 / 6, 3)
    assert scheduler.total_spend(res, entrants.by_id())["tokens"] == sp["tokens"]


def test_live_player_logs_usage_of_unapplied_replies(tmp_path):
    """LiveLLM: a superseded reply, the one pending at game end and the call still in flight all log their tokens."""
    import json

    from melee_llm.agents.llm_common import DecisionLog
    from melee_llm.agents.llm_live import LiveLLM
    from melee_llm.llm import Reply

    a = LiveLLM("claude-haiku-4-5-20251001", log_dir=tmp_path)
    a._stop.set()  # no worker: results are queued by hand
    a.port = 1
    a.log, a.stats, a.dropped = DecisionLog(tmp_path, "t", replay=tmp_path / "g.slp", port=1), [], []
    rep = lambda n: Reply({"action": "wait"}, prompt_tokens=n, completion_tokens=10)  # noqa: E731
    a._drop(((5, {}, "", []), rep(100), 50), 60, "superseded")
    a.pending, a.inflight = ((40, {}, "", []), rep(200), 90), True
    a._res.put(((80, {}, "", []), rep(300)))
    a.on_game_end(None)
    recs = [json.loads(ln) for ln in (tmp_path / "g.p1.llm.jsonl").read_text().splitlines()]
    dropped = [r for r in recs if r["type"] == "dropped"]
    assert [r["prompt_tokens"] for r in dropped] == [100, 200, 300]
    assert recs[-1]["type"] == "game_end" and recs[-1]["dropped_prompt_tokens"] == 600
