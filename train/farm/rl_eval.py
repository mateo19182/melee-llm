"""Evaluate an RL run's checkpoints in the farm as they appear: fixed opponents, fixed seeds.

    cd train && PYTHONPATH=. ../vendor/Faynt-Tournament/.venv/bin/python -m farm.rl_eval RUN [--games 48] [--once]

Each checkpoint (and the starting policy, as step 0) plays --games games, as Yoshi, against each opponent, over the
six stages and both ports, at the run's final delay (--delay overrides; with delay it reads its own last pad unless
the run used --no-own). Results go to data/train/runs/RUN/evals.jsonl, which the web Training page charts.
"""
import argparse
import json
import time

from .common import LIVE
from .rl import final_delay
from .run import Player, play

OPPONENTS = ["phillip:fox_d18_vs_yoshi_v3/FOX", "phillip:yoshi_d18_ditto/YOSHI", "phillip:marth_d18_vs_yoshi_v3/MARTH",
             "faynt:10M-Arena/YOSHI"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run")
    ap.add_argument("--games", type=int, default=48)
    ap.add_argument("--every", type=int, default=50, help="evaluate checkpoints whose step is a multiple of this")
    ap.add_argument("--opponents", default=",".join(OPPONENTS))
    ap.add_argument("--delay", type=int, help="input delay for the learner (default: the run's final delay)")
    ap.add_argument("--once", action="store_true", help="evaluate what exists, then stop")
    a = ap.parse_args()
    run = LIVE / "data/train/runs" / a.run
    out = run / "evals.jsonl"
    info = json.loads((run / "run.json").read_text())
    start = info["init"].rsplit("/", 1)[0]
    args = info.get("args", {})
    delay = a.delay if a.delay is not None else final_delay(str(args.get("delay", 0)))
    options = f",delay={delay}" + (",own=1" if args.get("own", True) else "") if delay else ""
    while True:
        done = set()
        if out.exists():
            done = {(r["step"], r["opponent"]) for r in map(json.loads, out.read_text().splitlines())
                    if r.get("delay", 0) == delay}
        todo = [(0, start)] + [(int(d.name.split("-")[1]), str(d)) for d in sorted((run / "ckpt").glob("step-*"))
                               if int(d.name.split("-")[1]) % a.every == 0]
        work = [(s, p, o) for s, p in todo for o in a.opponents.split(",") if (s, o) not in done]
        if not work:
            if a.once:
                return
            time.sleep(120)
            continue
        step, path, opponent = work[0]
        t0 = time.monotonic()
        me = Player.parse(f"faynt:{path}{options}/YOSHI")
        rows, _, _ = play(me, Player.parse(opponent), a.games, lanes=a.games, seed=10_000, quiet=True)
        line = dict(step=step, opponent=opponent, delay=delay, games=len(rows), wins=sum(r["score"] for r in rows),
                    margin=sum(r["stocks_a"] - r["stocks_b"] for r in rows) / len(rows), time=time.time(),
                    minutes=round((time.monotonic() - t0) / 60, 1))
        print(json.dumps(line), flush=True)
        with open(out, "a") as f:
            f.write(json.dumps(line) + "\n")


if __name__ == "__main__":
    main()
