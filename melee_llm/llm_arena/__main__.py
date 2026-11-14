"""CLI: python -m melee_llm.llm_arena {run,one,standings,schedule}. See docs/llm-arena.md."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from melee_llm.llm_arena import ratings, tournament
from melee_llm.runner import ROOT

DEFAULT_OUT = ROOT / "data/llm-arena"


def main() -> None:
    p = argparse.ArgumentParser(prog="python -m melee_llm.llm_arena")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("run", "schedule"):
        r = sub.add_parser(name)
        r.add_argument("--name", required=True, help="run name: results go to data/llm-arena/<name>/")
        r.add_argument("--model", action="append", required=True)
        r.add_argument("--stage", action="append", choices=tournament.STAGES)
        r.add_argument("--games", type=int, default=2, help="games per ordered pair per stage")
        r.add_argument("--anchor-games", type=int, default=2, help="games per model, CPU level and stage")
        r.add_argument("--anchor", action="append", help="CPU anchors (default cpu:5, cpu:9)")
        r.add_argument("--opts", default="", help="extra llm_paused spec options, e.g. interval=30")
        r.add_argument("--seed", type=int, default=0)
        r.add_argument("--rotate", action="store_true", help="counts per pairing, not per stage; stages rotate")
        if name == "run":
            r.add_argument("--iso", default=str(Path.home() / "melee.iso"))
            r.add_argument("--parallel", type=int, default=16)
            r.add_argument("--cap-frames", type=int, default=3600, help="end each game at this frame (0 = no cap)")
            r.add_argument("--retries", type=int, default=4)
            r.add_argument("--timeout", type=int, default=3600, help="wall seconds per game")
            r.add_argument("--max-attempts", type=int, default=2)
            r.add_argument("--max-tokens", type=int, default=0, help="stop starting games past this many tokens")
            r.add_argument("--display", default=":98")
    o = sub.add_parser("one", help="internal: play one game and print its result as JSON")
    o.add_argument("--iso", required=True)
    o.add_argument("--port", type=int, required=True)
    o.add_argument("--out", required=True)
    o.add_argument("--cap-frames", type=int, required=True)
    o.add_argument("--retries", type=int, required=True)
    o.add_argument("--job", required=True)
    s = sub.add_parser("standings")
    s.add_argument("--name", required=True)
    s.add_argument("--boot", type=int, default=1000)
    a = p.parse_args()

    if a.cmd == "one":
        rec = tournament.play_one(json.loads(a.job), a.iso, a.port, Path(a.out), a.cap_frames, a.retries)
        print(json.dumps(rec, default=float))
        return
    out = DEFAULT_OUT / a.name
    if a.cmd == "standings":
        print(ratings.markdown(ratings.write(out, a.boot)))
        return
    jobs = tournament.schedule(a.model, tuple(a.stage or tournament.STAGES), a.games, a.anchor_games,
                               tuple(a.anchor or tournament.ANCHORS), a.opts, a.seed, a.rotate)
    if a.cmd == "schedule":
        for j in jobs:
            print(j.key)
        print(f"{len(jobs)} games, {sum(j.kind == 'llm' for j in jobs)} model-vs-model")
        return
    out.mkdir(parents=True, exist_ok=True)
    (out / "config.json").write_text(json.dumps({k: v for k, v in vars(a).items() if k != "cmd"}, indent=1))
    tournament.run(jobs, a.iso, out, a.parallel, a.cap_frames, a.retries, a.timeout, a.max_attempts, a.max_tokens,
                   display=a.display)
    st = ratings.write(out)
    print(ratings.markdown(st))


if __name__ == "__main__":
    main()
