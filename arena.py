"""Arena channel: learned bots (and CPU 9) play back to back on display :99 in lockstep.

Each game picks the pair that has played least, random characters both bots support, and a legal stage.
Writes the stream overlay (OVERLAY), every result to arena/results.jsonl and Elo standings to
arena/standings.json (served at http://m19182:8767/arena).

    DISPLAY=:99 uv run arena.py --iso ~/melee.iso [--games N]
"""
import argparse
import itertools
import json
import random
import signal
import sys
import time
from collections import Counter
from dataclasses import asdict
from pathlib import Path

import melee

from match import make
from melee_llm.runner import play

ROOT = Path(__file__).parent
DATA = ROOT / "arena"
OVERLAY = Path("/tmp/melee-arena/overlay.txt")
ENTRANTS = ["hal:MASTER", "phillip:gm", "mimic", "faynt", "cpu:9"]
CHARACTERS = ["FOX", "FALCO", "MARTH", "CPTFALCON"]  # every bot (incl. MIMIC's per-character checkpoints) has these
STAGES = ["BATTLEFIELD", "FINAL_DESTINATION", "YOSHIS_STORY", "DREAMLAND", "FOUNTAIN_OF_DREAMS"]
K = 24


def char_name(c: str) -> str:
    return {"CPTFALCON": "Falcon", "JIGGLYPUFF": "Puff"}.get(c, c.title())


def label(spec: str) -> str:
    return {"hal:MASTER": "HAL", "phillip:gm": "Phillip", "mimic": "MIMIC", "faynt": "Faynt", "cpu:9": "CPU 9"}.get(spec, spec)


def load_results() -> list[dict]:
    path = DATA / "results.jsonl"
    return [json.loads(line) for line in path.open()] if path.exists() else []


def standings(results: list[dict]) -> dict:
    elo = {e: 1500.0 for e in ENTRANTS}
    record = {e: Counter() for e in ENTRANTS}
    for r in results:
        a, b = r["p1"], r["p2"]
        elo.setdefault(a, 1500.0), elo.setdefault(b, 1500.0)
        record.setdefault(a, Counter()), record.setdefault(b, Counter())
        score = 1.0 if r["winner"] == 1 else 0.0 if r["winner"] == 2 else 0.5
        expected = 1 / (1 + 10 ** ((elo[b] - elo[a]) / 400))
        elo[a] += K * (score - expected)
        elo[b] -= K * (score - expected)
        for spec, s in ((a, score), (b, 1 - score)):
            record[spec]["W" if s == 1 else "L" if s == 0 else "D"] += 1
    rows = sorted(({"entrant": label(e), "spec": e, "elo": round(elo[e]), "wins": record[e]["W"],
                    "losses": record[e]["L"], "draws": record[e]["D"]} for e in elo), key=lambda r: -r["elo"])
    return {"updated": time.strftime("%Y-%m-%d %H:%M:%S"), "games": len(results), "table": rows}


def write_overlay(text: str) -> None:
    OVERLAY.parent.mkdir(parents=True, exist_ok=True)
    tmp = OVERLAY.with_suffix(".tmp")
    tmp.write_text(text)
    tmp.replace(OVERLAY)  # atomic, so ffmpeg's drawtext never reads a half-written file


def pick(results: list[dict], rng: random.Random) -> tuple[str, str]:
    played = Counter(frozenset((r["p1"], r["p2"])) for r in results)
    pairs = list(itertools.combinations(ENTRANTS, 2))
    least = min(played[frozenset(p)] for p in pairs)
    a, b = rng.choice([p for p in pairs if played[frozenset(p)] == least])
    return (a, b) if rng.random() < 0.5 else (b, a)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--iso", required=True)
    p.add_argument("--games", type=int, default=0, help="0 = forever")
    a = p.parse_args()
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
    DATA.mkdir(exist_ok=True)
    rng = random.Random()
    played = 0
    while not a.games or played < a.games:
        results = load_results()
        table = standings(results)
        p1, p2 = pick(results, rng)
        c1, c2, stage = rng.choice(CHARACTERS), rng.choice(CHARACTERS), rng.choice(STAGES)
        elo = {row["spec"]: row["elo"] for row in table["table"]}
        write_overlay(f"{label(p1)} ({char_name(c1)}) {elo.get(p1, 1500)}  vs  {label(p2)} ({char_name(c2)}) {elo.get(p2, 1500)}"
                      f"   |   {stage.replace('_', ' ').title()}   |   game {len(results) + 1}")
        t0 = time.time()
        try:
            [res] = play({1: make(p1, c1), 2: make(p2, c2)}, a.iso, melee.Stage[stage], "lockstep", 1)
        except (RuntimeError, OSError) as e:
            print(f"game failed: {p1} vs {p2}: {e}", flush=True)
            time.sleep(10)
            continue
        row = {"time": time.strftime("%Y-%m-%dT%H:%M:%S"), "p1": p1, "p2": p2, "char1": c1, "char2": c2,
               "stage": stage, "winner": res.winner, "stocks": {str(k): int(v) for k, v in res.stocks.items()},
               "percent": {str(k): round(float(v), 1) for k, v in res.percent.items()}, "frames": res.frames,
               "wall_s": round(time.time() - t0, 1), "replay": res.replay}
        with (DATA / "results.jsonl").open("a") as f:
            f.write(json.dumps(row) + "\n")
        (DATA / "standings.json").write_text(json.dumps(standings(load_results()), indent=1))
        print(json.dumps(row), flush=True)
        played += 1


if __name__ == "__main__":
    main()
