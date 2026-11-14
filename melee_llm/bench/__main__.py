"""CLI: python -m melee_llm.bench {run,one,standings,entrants,imports}. See docs/bench.md."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from melee_llm.bench import scheduler


def main() -> None:
    p = argparse.ArgumentParser(prog="python -m melee_llm.bench")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="active-sampling fill until CIs are good or the budget is spent (resumable)")
    d = scheduler.Config()
    r.add_argument("--iso", default=d.iso)
    r.add_argument("--budget", type=float, default=d.budget_tokens / 1e6, help="CLIProxy tokens, millions")
    r.add_argument("--target", type=float, default=d.target, help="95%% CI half-width to reach, Elo")
    r.add_argument("--parallel", type=int, default=d.max_parallel)
    r.add_argument("--load-cap", type=float, default=d.load_cap)
    r.add_argument("--slots", default="", help="per kind, e.g. fast=3,realtime=6,untimed_llm=8")
    r.add_argument("--provider-slots", default="", help="LLM sides in flight, e.g. claude=6,gpt=6,jev=4")
    r.add_argument("--defer-unit", default=d.defer_unit)
    r.add_argument("--max-games", type=int, default=0)
    r.add_argument("--only", action="append", default=[], help="restrict to these entrant ids (repeatable)")
    r.add_argument("--stagger", type=float, default=d.stagger_s)
    r.add_argument("--out", default=str(scheduler.DATA))
    o = sub.add_parser("one", help="internal: play one game, print the result as JSON")
    o.add_argument("--iso", required=True)
    o.add_argument("--port", type=int, required=True)
    o.add_argument("--out", required=True)
    o.add_argument("--job", required=True)
    s = sub.add_parser("standings", help="recompute data/bench/standings.json")
    s.add_argument("--boot", type=int, default=1000)
    s.add_argument("--out", default=str(scheduler.DATA))
    sub.add_parser("entrants")
    sub.add_parser("imports")
    a = p.parse_args()

    if a.cmd == "one":
        from melee_llm.bench.game import play_one
        rec = play_one(json.loads(a.job), a.iso, a.port, Path(a.out))
        print(json.dumps(rec, default=float))
    elif a.cmd == "run":
        kv = lambda s: {k: int(v) for k, v in (x.split("=") for x in s.split(",") if x)}  # noqa: E731
        cfg = scheduler.Config(iso=a.iso, budget_tokens=int(a.budget * 1e6), target=a.target, max_parallel=a.parallel,
                               load_cap=a.load_cap, defer_unit=a.defer_unit, max_games=a.max_games, only=a.only,
                               stagger_s=a.stagger)
        cfg.slots.update(kv(a.slots))
        cfg.provider_slots.update(kv(a.provider_slots))
        scheduler.Bench(cfg, Path(a.out)).run()
    elif a.cmd == "standings":
        from melee_llm.bench import imports, ratings
        out = Path(a.out)
        imp, exc = imports.load()
        st = ratings.standings(scheduler.read_results(out / "results.jsonl"), imp, exc, boot=a.boot)
        out.mkdir(parents=True, exist_ok=True)
        scheduler._write_json(out / "standings.json", st)
        for t, tr in st["tracks"].items():
            print(f"\n== {t}: {tr['games']} games")
            for i, row in enumerate(tr["players"], 1):
                print(f"{i:3d} {row['id']:42s} {row['elo']:5d}  [{row['elo_lo']}, {row['elo_hi']}] ±{row['half_width']:.0f} "
                      f"n={row['games']} {row['wins']}-{row['losses']}-{row['draws']}")
    elif a.cmd == "entrants":
        from melee_llm.bench.entrants import registry
        for x in registry():
            print(f"{x.id:45s} {x.category:9s} {x.track:9s} {x.provider:7s} {'active' if x.active else '-':7s} {x.spec}")
    elif a.cmd == "imports":
        from melee_llm.bench import imports
        games, excluded = imports.load()
        print(f"{len(games)} imported; excluded: {json.dumps(excluded, indent=1)}")


if __name__ == "__main__":
    main()
