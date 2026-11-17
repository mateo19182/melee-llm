"""Lane B league: our runs (always Yoshi) against a fixed roster of published bots, rated on one Elo scale.

    uv run python -m meleebot.league play RUN_OR_ROSTER... [--opponents NAME,...] [--games 6] [--parallel 4]
    uv run python -m meleebot.league table

A player is a run directory in data/train/runs/ (plays Yoshi), optionally `RUN@dN` to play at N frames of
input delay (netplay is about 2-4; each delay is rated as its own player), or a ROSTER name. `play` pits each named
player against each opponent (default: the whole roster), cycling the six legal stages. Games append to
data/train/league/games.jsonl; `table` fits Bradley-Terry ratings (melee_llm.ratings) over all of them, with
cpu9-fox at 0. The roster's Phillip tiers give the scale fixed points; roster-vs-roster games
(e.g. `play phillip-gm-fox --opponents hal-master-fox`) tighten it.
"""
import argparse, json, os, sys, time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

from .evaluate import LIVE, REPO, STAGES, game

sys.path.insert(0, str(REPO))
from melee_llm.ratings import elo_ratings  # noqa: E402  (pure numpy)

ROSTER = {  # name -> (match spec, character); see docs/bots.md
    "cpu9-fox": ("cpu:9", "FOX"),
    "phillip-plat-fox": ("phillip:plat", "FOX"),
    "phillip-diamond-fox": ("phillip:diamond", "FOX"),
    "phillip-master-fox": ("phillip:master", "FOX"),
    "phillip-gm-fox": ("phillip:gm", "FOX"),
    "mimic-fox": ("mimic:fox-master", "FOX"),
    "mimic-marth": ("mimic:marth", "MARTH"),
    "hal-master-fox": ("hal:MASTER", "FOX"),
    "hal-master-yoshi": ("hal:MASTER", "YOSHI"),
    "hal-amsa-yoshi": ("hal:AMSA#0", "YOSHI"),   # imitating aMSa, the one pro Yoshi in its training data
    "faynt-10m-fox": ("faynt:10M-Arena", "FOX"),
    "faynt-75m-fox": ("faynt:75M-Arena", "FOX"),
    "phillip-super-gm-fox": ("phillip:super-gm", "FOX"),
    "phillip-fox-v6.2": ("phillip:fox_d21_v6.2", "FOX"),       # per-character RL agents, 21 frames of delay
    "phillip-marth-v6.2": ("phillip:marth_d21_v6.2", "MARTH"),
    "phillip-falco-v6.2": ("phillip:falco_d21_v6.2", "FALCO"),
    # Phillip's RL agents trained against Yoshi (18 frames of delay)
    "phillip-fox-vs-yoshi": ("phillip:fox_d18_vs_yoshi_v3", "FOX"),
    "phillip-marth-vs-yoshi": ("phillip:marth_d18_vs_yoshi_v3", "MARTH"),
    "phillip-falco-vs-yoshi": ("phillip:falco_d18_vs_yoshi", "FALCO"),
    "phillip-sheik-vs-yoshi": ("phillip:sheik_d18_vs_yoshi", "SHEIK"),
    "phillip-peach-vs-yoshi": ("phillip:peach_d18_vs_yoshi_v3", "PEACH"),
    # Phillip's own Yoshi agents: rivals for ours. Each RL one was trained for one matchup.
    "phillip-yoshi-imitation": ("phillip:yoshi_d18_imitation_v3", "YOSHI"),
    "phillip-yoshi-ditto": ("phillip:yoshi_d18_ditto", "YOSHI"),
    "phillip-yoshi-vs-fox": ("phillip:yoshi_d18_vs_fox_v3", "YOSHI"),
    "phillip-yoshi-vs-marth": ("phillip:yoshi_d18_vs_marth_v3", "YOSHI"),
    "phillip-yoshi-vs-falco": ("phillip:yoshi_d18_vs_falco", "YOSHI"),
    "phillip-yoshi-vs-sheik": ("phillip:yoshi_d18_vs_sheik_v4", "YOSHI"),
    "phillip-yoshi-vs-peach": ("phillip:yoshi_d18_vs_peach_v3", "YOSHI"),
}
ANCHOR = "cpu9-fox"
DIR = LIVE / "data/train/league"
RUNS = LIVE / "data/train/runs"


def player(name):
    if name in ROSTER:
        return ROSTER[name]
    if ":" in name:  # a raw match spec, e.g. hal:AMSA#0,temperature=0.9 or phillip:gm/FOX (default Yoshi)
        spec, _, char = name.partition("/")
        return spec, char or "YOSHI"
    run, _, delay = name.partition("@d")
    if (RUNS / run / "last.pt").exists():
        return f"meleebot:{run}" + (f",delay={int(delay)}" if delay else ""), "YOSHI"
    sys.exit(f"{name}: not a roster bot ({', '.join(ROSTER)}) nor a run with last.pt")


def load():
    path = DIR / "games.jsonl"
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()] if path.exists() else []


def play(a):
    env = {**os.environ, "PYTHONPATH": str(REPO), "MELEE_WEB_DATA": str(LIVE / "data")}
    opponents = a.opponents.split(",") if a.opponents else list(ROSTER)
    jobs = [(p, o, STAGES[i % len(STAGES)]) for p in a.players for o in opponents if o != p for i in range(a.games)]
    for n in {*a.players, *opponents}:
        player(n)
    DIR.mkdir(parents=True, exist_ok=True)

    def one(job):
        p, o, stage = job
        (spec, char), (ospec, ochar) = player(p), player(o)
        return job, game(spec, ospec, ochar, stage, a.iso, env, char=char)

    with ThreadPoolExecutor(a.parallel) as ex, open(DIR / "games.jsonl", "a") as log:
        for (p, o, stage), r in ex.map(one, jobs):
            if "error" in r:
                print(f"{p} vs {o} on {stage}: error {r['error'][-300:]}", flush=True)
                continue
            score = 0.5 if r["winner"] not in (1, 2) else float(r["winner"] == 1)
            row = dict(time=time.time(), a=p, b=o, a_char=player(p)[1], b_char=player(o)[1], stage=stage,
                       score=score, stocks_a=r["stocks"]["1"], stocks_b=r["stocks"]["2"], frames=r["frames"],
                       replay=r["replay"])
            log.write(json.dumps(row) + "\n"); log.flush()
            print(f"{p} vs {o} on {stage}: {score} ({row['stocks_a']}-{row['stocks_b']} stocks)", flush=True)
    table(a)


def table(_=None):
    rows = load()
    if not rows:
        print("no league games yet"); return
    elo = elo_ratings([(r["a"], r["b"], r["score"]) for r in rows], anchor=ANCHOR)
    n = {p: sum(p in (r["a"], r["b"]) for r in rows) for p in elo}
    print(f"{'player':28} {'elo':>6} {'games':>5}")
    for p, e in sorted(elo.items(), key=lambda kv: -kv[1]):
        print(f"{p:28} {e:6.0f} {n[p]:5d}")
    return elo


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    pp = sub.add_parser("play")
    pp.add_argument("players", nargs="+")
    pp.add_argument("--opponents", help="comma-separated roster names or runs; default the whole roster")
    pp.add_argument("--games", type=int, default=6, help="per pairing; stages cycle over the six legal ones")
    pp.add_argument("--parallel", type=int, default=4)
    pp.add_argument("--iso", default=str(Path.home() / "melee.iso"))
    sub.add_parser("table")
    a = ap.parse_args()
    play(a) if a.cmd == "play" else table(a)


if __name__ == "__main__":
    main()
