"""Closed-loop strength check: a run's checkpoint plays real games (fast mode) and the scores are summed.

    uv run python -m meleebot.evaluate RUN [--opponent cpu:9] [--games 12] [--parallel 6] [--steer delay=0]

Games go through melee_llm.match in the repo that contains this train/ directory, using the live
checkout's venv and data. Results append to data/train/runs/<RUN>/eval.jsonl, one line per game.
"""
import argparse, json, os, queue, subprocess, sys, threading, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
LIVE = Path.home() / "projects/ai/melee-llm"
STAGES = ["BATTLEFIELD", "FINAL_DESTINATION", "YOSHIS_STORY", "DREAMLAND", "FOUNTAIN_OF_DREAMS", "POKEMON_STADIUM"]


PORTS = queue.Queue()
for _p in range(52200, 52240):  # melee_llm.paths.TRAIN_EVAL_PORTS
    PORTS.put(_p)


_START = threading.Lock()


def game(spec, opponent, opp_char, stage, iso, env):
    port = PORTS.get()
    with _START:  # Dolphin names replays by the second a game starts: keep starts apart
        time.sleep(2)
    cmd = [str(LIVE / ".venv/bin/python"), "-m", "melee_llm.match", "--iso", iso, "--mode", "fast", "--port", str(port),
           "--p1", spec, "--char1", "YOSHI", "--p2", opponent, "--char2", opp_char, "--stage", stage]
    try:
        out = subprocess.run(cmd, cwd=REPO, env=env, capture_output=True, text=True, timeout=1800)
    finally:
        PORTS.put(port)
    for line in reversed(out.stdout.splitlines()):
        if line.startswith("{"):
            return json.loads(line)
    return {"error": (out.stderr or out.stdout)[-500:]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run")
    ap.add_argument("--opponent", default="cpu:9"); ap.add_argument("--opp-char", default="FOX")
    ap.add_argument("--games", type=int, default=12); ap.add_argument("--parallel", type=int, default=6)
    ap.add_argument("--stages", default="BATTLEFIELD,FINAL_DESTINATION,YOSHIS_STORY,DREAMLAND")
    ap.add_argument("--iso", default=str(Path.home() / "melee.iso"))
    a = ap.parse_args()

    data = LIVE / "data"
    env = {**os.environ, "PYTHONPATH": str(REPO), "MELEE_WEB_DATA": str(data)}
    run_dir = data / "train/runs" / a.run
    if not (run_dir / "last.pt").exists():
        sys.exit(f"no checkpoint {run_dir}/last.pt")
    stages = a.stages.split(",")
    jobs = [(f"meleebot:{a.run}", a.opponent, a.opp_char, stages[i % len(stages)], a.iso, env) for i in range(a.games)]
    t0, rows = time.time(), []
    with ThreadPoolExecutor(a.parallel) as ex, open(run_dir / "eval.jsonl", "a") as log:
        for (_, _, _, stage, _, _), r in zip(jobs, ex.map(lambda j: game(*j), jobs)):
            if "error" in r:
                print("error:", r["error"], flush=True)
                continue
            row = dict(time=time.time(), opponent=a.opponent, opp_char=a.opp_char, stage=stage,
                       won=r["winner"] == 1, stocks_taken=4 - r["stocks"]["2"], stocks_lost=4 - r["stocks"]["1"],
                       frames=r["frames"], replay=r["replay"])
            rows.append(row)
            log.write(json.dumps(row) + "\n"); log.flush()
            print(json.dumps(row), flush=True)
    n = len(rows)
    if n:
        summary = dict(run=a.run, opponent=a.opponent, games=n, wins=sum(r["won"] for r in rows),
                       stocks_taken=round(sum(r["stocks_taken"] for r in rows) / n, 2),
                       stocks_lost=round(sum(r["stocks_lost"] for r in rows) / n, 2),
                       minutes=round((time.time() - t0) / 60, 1))
        print(json.dumps(summary))


if __name__ == "__main__":
    main()
