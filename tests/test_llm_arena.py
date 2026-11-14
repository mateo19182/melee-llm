"""LLM arena: schedule balance and Bradley-Terry recovery on synthetic games (no ISO, no API)."""
import math
import random
from collections import Counter

from melee_llm.llm_arena.ratings import standings
from melee_llm.llm_arena.tournament import schedule


def test_schedule_full_and_rotated():
    full = schedule(["a", "b", "c"], games=2, anchor_games=2)
    assert len(full) == 3 * 2 * 2 * 2 + 3 * 2 * 2 * 2  # ordered pairs x stages x games + models x cpus x stages x games
    assert len({j.key for j in full}) == len(full)
    rot = schedule(["a", "b", "c", "d"], games=1, anchor_games=1, rotate=True)
    llm = [j for j in rot if j.kind == "llm"]
    assert len(llm) == 12 and len(rot) == 20
    pairs = Counter(frozenset(j.players()) for j in llm)
    assert set(pairs.values()) == {2}
    for pair in pairs:  # both port orders, on different stages
        games = [j for j in llm if frozenset(j.players()) == pair]
        assert len({j.p1 for j in games}) == 2 and len({j.stage for j in games}) == 2


def spec(name: str) -> str:
    return name if name.startswith("cpu") else f"llm_paused:{name}"


def test_bradley_terry_recovers_order():
    rng = random.Random(0)
    true = {"strong": 1.5, "mid": 0.5, "cpu:9": 0.0, "cpu:5": -1.0}
    side = {"prompt_tokens": 1, "completion_tokens": 1, "decisions": 1, "invalid": 0, "api_failed": 0,
            "api_retries": 0, "mean_latency_s": 1.0, "mean_think_s": 1.0, "actions": {"wait": 1}}
    rows = []
    for _ in range(600):
        x, y = rng.sample(list(true), 2)
        if x.startswith("cpu") and y.startswith("cpu"):
            continue
        win = rng.random() < 1 / (1 + math.exp(true[y] - true[x]))
        rows.append({"status": "ok", "p1": spec(x), "p2": spec(y), "winner": 1 if win else 2,
                     "stocks": {"1": 1, "2": 1}, "percent": {"1": 0, "2": 0},
                     "sides": {str(p): side for p, n in ((1, x), (2, y)) if not n.startswith("cpu")}})
    st = standings(rows, boot=50)
    assert [p["player"] for p in st["players"]] == ["strong", "mid", "cpu:9", "cpu:5"]
    cpu9 = next(p for p in st["players"] if p["player"] == "cpu:9")
    assert cpu9["elo"] == cpu9["elo_lo"] == cpu9["elo_hi"] == 1500
