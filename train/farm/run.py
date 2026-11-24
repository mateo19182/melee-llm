"""Many games at once in the simulator between learned bots: Faynt, Phillip and HAL, each batched over its seats.

    cd train && PYTHONPATH=. ../vendor/Faynt-Tournament/.venv/bin/python -m farm.run A B --games 64 \\
        [--lanes 64] [--workers 1] [--out DIR] [--no-ucf] [--check] [--stages BATTLEFIELD,...]

A player is `KIND:ARG[,option=value...]/CHARACTER` (default Yoshi):
- `faynt:10M-Arena[,temperature=T][,delay=N]` (farm.faynt, in this process, on the GPU)
- `phillip:MODEL[,temperature=T]`, a model in vendor/slippi-ai/models (farm.phillip, its own process, on the CPU)
- `hal:IDENTITY[,return_target=N][,temperature=T][,delay=N]` (farm.hal, its own process, on the GPU)

The first player takes port 1 on even lanes and port 2 on odd ones; stages cycle over the six legal ones (or
--stages). Rules: 4 stocks, 8 minutes, no items, UCF as on current Slippi and our Dolphin (--no-ucf turns off its 1.0
cardinals, as in some older Slippi games; the simulator's other UCF fixes are always on). Each seat reads what its live
bot reads on Dolphin (farm.common); --check also rebuilds every frame from Slippi events, as the live bots see
Dolphin, and reports any seat-frame where a model would have read something else.
"""
import argparse
import dataclasses
import json
import os
import time
from pathlib import Path

import numpy as np

from .common import LIVE, Frame

DATA = Path(os.environ.get("MSL_DATA_DIR", LIVE / "vendor/melee-sim-light/data"))
STAGES = ["BATTLEFIELD", "FINAL_DESTINATION", "YOSHIS_STORY", "DREAMLAND", "FOUNTAIN_OF_DREAMS", "POKEMON_STADIUM"]
TIMER = 8 * 60 * 60  # frames; Slippi's 8-minute timer
RING = 1024  # simulator frames per buffer pass; the cursor wraps
KINDS = ("faynt", "phillip", "hal")


@dataclasses.dataclass(frozen=True)
class Player:
    name: str
    kind: str
    spec: str  # without the character
    character: str

    @classmethod
    def parse(cls, name):
        spec, _, character = name.rpartition("/")
        if not spec or not character.replace("_", "").isalpha() or not character.isupper():
            spec, character = name, ""  # no character: a checkpoint path's last part is not one
        kind = spec.partition(":")[0]
        if kind not in KINDS:
            raise ValueError(f"{name}: the farm plays {', '.join(KINDS)}")
        return cls(name, kind, spec, character or "YOSHI")


def stage_of(game, stages):
    """Games 2k and 2k+1 share a stage. Lanes alternate ports, so a lane's games (and a worker's) cover every stage
    from both ports instead of tying each port to every other stage."""
    return stages[(game // 2) % len(stages)]


def brain(kind, spec, seats, seed, check, graph):
    if kind == "faynt":
        from .faynt import FayntBrain
        return FayntBrain(spec, seats, seed, check, graph)
    from .remote import RemoteBrain
    return RemoteBrain(kind, spec, seats, seed, check)


def play(a, b, games, lanes=64, out=None, seed=0, ucf=True, check=False, first=0, quiet=False, graph=True,
         stages=STAGES):
    """Play `games` games of a against b. Returns the result rows (a's score is 1 for a win, 0.5 for a draw) and, with
    check, each brain's input comparison. Games are numbered from `first` (a game's number picks its stage and seed),
    so workers can split a run. Stages cycle over `stages`."""
    import melee
    import melee_sim as msl

    from melee_llm.sim.slippi import Encoder
    from melee_llm.sim.state import SIM_STAGE

    lanes = min(lanes, games)
    a_port = [1 + lane % 2 for lane in range(lanes)]
    groups = {}
    for lane in range(lanes):
        for port in (1, 2):
            p = a if port == a_port[lane] else b
            groups.setdefault((p.kind, p.spec), []).append((lane, port))
    started = time.monotonic()
    brains = [(seats, brain(kind, spec, seats, seed + first, check, graph)) for (kind, spec), seats in groups.items()]
    load = time.monotonic() - started

    env = msl.EnvBatch(batch_size=lanes, length=RING, action_format="raw", data_dir=str(DATA),
                       ucf_cardinals_1_0_enabled=ucf)
    game = list(range(first, first + lanes))
    encoders = [None] * lanes
    encode = check or any(br.from_events for _, br in brains)

    def configure(lane):
        chars = (a.character, b.character) if a_port[lane] == 1 else (b.character, a.character)
        stage = melee.Stage[stage_of(game[lane], stages)]
        env.configure_matches([msl.MatchConfig(
            stage=SIM_STAGE[stage], seed=(seed + game[lane]) % 2**32, max_frame=TIMER, ucf_cardinals_1_0_enabled=ucf,
            players=tuple(msl.PlayerConfig(melee.Character[c].value, controller_port=i) for i, c in enumerate(chars)))],
            env_ids=[lane])
        if encode:
            encoders[lane] = Encoder(stage, [1, 2])

    for lane in range(lanes):
        configure(lane)
    env.reset_all()
    active, fresh, has_input = np.ones(lanes, bool), np.ones(lanes, bool), np.zeros(lanes, bool)
    inputs = np.zeros(lanes, dtype=env.raw_action_view.dtype)  # the raw input row that produced each current frame
    next_game, frames, results, started = first + lanes, 0, [], time.monotonic()
    if out:
        Path(out).mkdir(parents=True, exist_ok=True)

    try:
        while active.any():
            if env.t >= env.length:
                env.reset_cursor()
            obs = env.current_frame
            events = None
            if encode:
                events = {int(lane): encoders[lane].frame(obs[lane], inputs[lane] if has_input[lane] else None)
                          for lane in np.flatnonzero(active)}
            frame = Frame(obs, inputs, has_input, fresh, active, events)
            remote = [(seats, br) for seats, br in brains if hasattr(br, "submit")]
            for _, br in remote:
                br.submit(frame)  # brain processes work while this one steps its own
            raw = env.raw_action_view[env.t]
            for seats, br in brains:
                rows = br.collect() if hasattr(br, "submit") else br.act(frame)
                for (lane, port), r in zip(seats, rows):
                    if active[lane]:
                        raw[lane]["players"][port - 1] = r
            t = env.t
            env.step(active.astype(np.uint8))
            frames += int(active.sum())
            np.copyto(inputs, raw, where=active)
            has_input |= active
            fresh[:] = False
            done = active & env.terminal_view[t]["done"].astype(bool)
            if not done.any():
                continue
            obs = env.current_frame
            restart = []
            for lane in np.flatnonzero(done):
                slots = {int(s["source_player"]): s for s in obs[lane]["slots"] if s["source_player"] < 2}
                mine, theirs = (0, 1) if a_port[lane] == 1 else (1, 0)
                stocks = [int(slots[p]["stocks"]) for p in (mine, theirs)]
                percent = [float(slots[p]["percent"]) for p in (mine, theirs)]
                lead = (stocks[0] - stocks[1]) or (percent[1] - percent[0])  # timer: stocks, then the lower percent
                row = dict(time=time.time(), a=a.name, b=b.name, a_char=a.character, b_char=b.character,
                           stage=stage_of(game[lane], stages), score=0.5 if lead == 0 else float(lead > 0),
                           stocks_a=stocks[0], stocks_b=stocks[1], frames=int(obs[lane]["frame_id"]) + 123,
                           a_port=mine + 1, seed=seed + game[lane],
                           timeout=bool(env.terminal_view[t][lane]["max_frame_reached"]), sim=True, ucf=ucf)
                results.append(row)
                if out:
                    with open(Path(out) / "results.jsonl", "a") as f:
                        f.write(json.dumps(row) + "\n")
                quiet or print(f"{a.name} vs {b.name} on {row['stage']}: {row['score']} ({stocks[0]}-{stocks[1]} "
                               f"stocks, {row['frames']} frames)", flush=True)
                if next_game < first + games:
                    game[lane], next_game = next_game, next_game + 1
                    configure(lane)
                    restart.append(lane)
                else:
                    active[lane] = False
            if restart:
                env.reset_matches(restart)
                fresh[restart], has_input[restart] = True, False
        reports = {spec: br.report() for ((kind, spec), _), (_, br) in zip(groups.items(), brains)}
        for ((_, spec), _), (_, br) in zip(groups.items(), brains):
            if not quiet and getattr(br, "pressed", 0):
                print(f"{spec}: main stick changed on {br.moved / br.pressed:.1%} of frames", flush=True)
    finally:
        for _, br in brains:
            if hasattr(br, "close"):
                br.close()
        env.close()
    if not quiet:
        summary(a, b, results, frames, time.monotonic() - started, load)
        if check:
            print_reports(reports)
    return results, frames, reports


def summary(a, b, results, frames, wall, load=0.0):
    score = sum(r["score"] for r in results)
    stocks = sum(r["stocks_a"] - r["stocks_b"] for r in results) / max(1, len(results))
    print(f"{a.name}: {score:g} of {len(results)} against {b.name} ({stocks:+.2f} stocks a game); {frames:,} frames "
          f"in {wall / 60:.1f} min ({frames / wall:,.0f} a second; models took {load:.0f} s to load)", flush=True)


def print_reports(reports):
    for name, r in reports.items():
        if r is None:
            continue
        if r.get("from_events"):
            print(f"{name}: reads GameStates parsed from the Slippi events, as live")
            continue
        print(f"{name}: {r['compared']:,} seat-frames checked against libmelee's parse of the Slippi events")
        for field, n in sorted(r["diffs"].items(), key=lambda kv: -kv[1]):
            print(f"  {field}: {n:,} differ, e.g. (lane, frame, port, ours, live) {r['examples'][field]}")
        if not r["diffs"]:
            print("  every field equal")


def _worker(job):
    import torch

    torch.set_num_threads(1)
    *args, graph, stages = job
    return play(*args, quiet=True, graph=graph, stages=stages)


def play_parallel(a, b, games, lanes=64, out=None, seed=0, ucf=True, check=False, workers=1, graph=True,
                  stages=STAGES):
    """`play` split over worker processes, each with its own simulator batch and models."""
    import multiprocessing
    from concurrent.futures import ProcessPoolExecutor

    if workers <= 1:
        return play(a, b, games, lanes, out, seed, ucf, check, graph=graph, stages=stages)
    share = [games // workers + (i < games % workers) for i in range(workers)]
    firsts = np.cumsum([0, *share[:-1]])
    jobs = [(a, b, n, min(lanes, n), out, seed, ucf, check, int(f), graph, stages) for n, f in zip(share, firsts) if n]
    started, results, frames, reports = time.monotonic(), [], 0, []
    with ProcessPoolExecutor(len(jobs), mp_context=multiprocessing.get_context("spawn")) as ex:
        for r, f, rep in ex.map(_worker, jobs):
            results += r
            frames += f
            reports.append(rep)
    summary(a, b, results, frames, time.monotonic() - started)
    if check:
        merged = {}
        for rep in reports:
            for name, r in rep.items():
                if r is None or r.get("from_events"):
                    merged.setdefault(name, r)
                    continue
                m = merged.setdefault(name, {"compared": 0, "diffs": {}, "examples": {}})
                m["compared"] += r["compared"]
                for k, v in r["diffs"].items():
                    m["diffs"][k] = m["diffs"].get(k, 0) + v
                    m["examples"].setdefault(k, r["examples"][k])
        print_reports(merged)
    return results, frames, reports


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("a")
    ap.add_argument("b")
    ap.add_argument("--games", type=int, default=64)
    ap.add_argument("--lanes", type=int, default=64)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--no-ucf", dest="ucf", action="store_false", help="without UCF's 1.0 cardinals")
    ap.add_argument("--check", action="store_true", help="compare every seat's inputs with the live bot's")
    ap.add_argument("--workers", type=int, default=1, help="processes; each runs --lanes games at a time")
    ap.add_argument("--no-graph", action="store_true", help="step Faynt eagerly instead of replaying a CUDA graph")
    ap.add_argument("--stages", default=",".join(STAGES), help="comma-separated; games cycle over them")
    args = ap.parse_args()
    play_parallel(Player.parse(args.a), Player.parse(args.b), args.games, args.lanes, args.out, args.seed, args.ucf,
                  args.check, args.workers, not args.no_graph, args.stages.split(","))


if __name__ == "__main__":
    main()
