"""CLI: python -m melee_llm.bench {run,one,standings,recount,entrants,imports}. See docs/bench.md."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from melee_llm.bench import scheduler


def main() -> None:
    p = argparse.ArgumentParser(prog="python -m melee_llm.bench")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="active-sampling fill until more games stop being useful (resumable)")
    d = scheduler.Config()
    r.add_argument("--iso", default=d.iso)
    r.add_argument("--budget", type=float, default=None, help="optional CLIProxy token cap, millions (default: none)")
    r.add_argument("--target", type=float, default=d.target, help="95%% CI half-width to reach, Elo")
    r.add_argument("--min-gain", type=float, default=d.min_gain,
                   help="Elo of narrowing 20 more games must buy for a wider-than-target entrant to keep playing")
    r.add_argument("--parallel", type=int, default=d.max_parallel)
    r.add_argument("--load-cap", type=float, default=d.load_cap)
    r.add_argument("--slots", default="", help="per kind, e.g. fast=3,realtime=6,untimed_llm=8")
    r.add_argument("--provider-slots", default="", help="LLM sides in flight, e.g. claude=6,gpt=6,jev=4")
    r.add_argument("--defer-unit", default=d.defer_unit)
    r.add_argument("--max-games", type=int, default=0)
    r.add_argument("--only", action="append", default=[], help="restrict to these entrant ids (repeatable)")
    r.add_argument("--stagger", type=float, default=d.stagger_s)
    r.add_argument("--ports", default=f"{d.ports[0]}-{d.ports[1]}", help="Slippi port range [start-stop)")
    r.add_argument("--context", action="append", default=[], help="another results.jsonl whose games join the fit")
    r.add_argument("--gpu-slots", type=int, default=d.gpu_slots)
    r.add_argument("--out", default=str(scheduler.DATA))
    o = sub.add_parser("one", help="internal: play one game, print the result as JSON")
    o.add_argument("--iso", required=True)
    o.add_argument("--port", type=int, required=True)
    o.add_argument("--out", required=True)
    o.add_argument("--job", required=True)
    s = sub.add_parser("standings", help="recompute data/bench/standings.json")
    s.add_argument("--boot", type=int, default=1000)
    s.add_argument("--out", default=str(scheduler.DATA))
    c = sub.add_parser("recount", help="recount token spend from the decision logs (replies never applied included)")
    c.add_argument("--out", default=str(scheduler.DATA))
    sub.add_parser("entrants")
    sub.add_parser("imports")
    a = p.parse_args()

    if a.cmd == "one":
        from melee_llm.bench.game import play_one
        rec = play_one(json.loads(a.job), a.iso, a.port, Path(a.out))
        print(json.dumps(rec, default=float))
    elif a.cmd == "run":
        kv = lambda s: {k: int(v) for k, v in (x.split("=") for x in s.split(",") if x)}  # noqa: E731
        cfg = scheduler.Config(iso=a.iso, budget_tokens=None if a.budget is None else int(a.budget * 1e6),
                               target=a.target, min_gain=a.min_gain, max_parallel=a.parallel,
                               load_cap=a.load_cap, defer_unit=a.defer_unit, max_games=a.max_games, only=a.only,
                               stagger_s=a.stagger, ports=tuple(int(x) for x in a.ports.split("-")), context=a.context,
                               gpu_slots=a.gpu_slots)
        cfg.slots.update(kv(a.slots))
        cfg.provider_slots.update(kv(a.provider_slots))
        scheduler.Bench(cfg, Path(a.out)).run()
    elif a.cmd == "standings":
        from melee_llm.bench import imports, ratings
        out = Path(a.out)
        imp, exc = imports.load()
        imp = [g for g in imp if g["source"] != out.name]  # a side run's own games are already its results
        from melee_llm.bench import recount
        st = ratings.standings(recount.apply(scheduler.read_results(out / "results.jsonl"), recount.load(out / "recount.json")),
                               imp, exc, boot=a.boot)
        out.mkdir(parents=True, exist_ok=True)
        scheduler._write_json(out / "standings.json", st)
        print(f"{st['board']['games']} rated games")
        for i, row in enumerate(st["board"]["players"], 1):
            bound = {"lower": " (never lost: a lower bound)", "upper": " (never won: an upper bound)"}.get(row["bound"], "")
            print(f"{i:3d} {row['id']:42s} {row['elo']:5d}  [{row['elo_lo']}, {row['elo_hi']}] ±{row['half_width']:.0f} "
                  f"n={row['games']} {row['wins']}-{row['losses']}-{row['draws']} {row['clock']}/{row['group']}{bound}")
    elif a.cmd == "recount":
        from melee_llm.bench import recount
        from melee_llm.bench.entrants import by_id
        out = Path(a.out)
        results = scheduler.read_results(out / "results.jsonl")
        rc = recount.recount(results)
        scheduler._write_json(out / "recount.json", rc)
        ents = by_id()
        st = json.loads((out / "status.json").read_text()) if (out / "status.json").exists() else {}
        st["spent_recounted"] = scheduler.recounted_spend(results, ents, out)
        scheduler._write_json(out / "status.json", st)
        was, now = scheduler.total_spend(results, ents), st["spent_recounted"]
        print(f"{len(rc)} games recounted; CLIProxy tokens {was['tokens']:,} as counted → {now['tokens']:,} "
              f"({json.dumps(now['by_provider'])})")
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
