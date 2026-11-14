"""Coach deep-dive: mine the coach decision logs of bench (and ablation) games. See docs/coach-deepdive.md.

  uv run python scripts/coach_deepdive.py logs        # per coach: changes, commands, router, latency
  uv run python scripts/coach_deepdive.py windows     # command -> outcome in the following window (random coach = RCT)
  uv run python scripts/coach_deepdive.py games       # game-level: win vs opponent Elo, by coach behaviour
  uv run python scripts/coach_deepdive.py ablations [results.jsonl]   # Elo of ablation entrants on the bench scale

Windows are the spans between consecutive coach calls (~5 s at interval 300); outcomes come from the percent and
stocks in the state text each call saw. The effective command is Reyn's `active` (router row) after each call:
an abstained phrase keeps the previous command.
"""
from __future__ import annotations

import json
import math
import re
import statistics as S
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
BENCH = ROOT / "data/bench/results.jsonl"
STATE = re.compile(r"^(YOU|OPP) \w+ ([\d.]+)% (\d)stk", re.M)
SHORT = {"coach:claude-haiku-4-5-20251001": "haiku", "coach:claude-sonnet-5-5": "sonnet", "coach:gpt-6-luna": "luna",
         "coach:gpt-6.1-sol": "sol", "coach:random": "random", "coach_jev": "jev", "reyn": "reyn"}


def read(path):
    out = []
    for ln in Path(path).read_text().splitlines():
        try:
            out.append(json.loads(ln))
        except ValueError:
            pass
    return out


def coach_sides(results):
    """(result, port, entrant id, log path) for every ok game side with a coach log."""
    for r in results:
        if r.get("status") != "ok":
            continue
        for port, s in (r.get("sides") or {}).items():
            eid = r[f"p{port}"]
            if s.get("log", "").endswith(".coach.jsonl") and Path(s["log"]).exists():
                yield r, int(port), eid, Path(s["log"])


def sections():
    """Router row (Reyn's `active`) → menu section, via each command's phrase."""
    import melee

    from melee_llm.agents.coach import reyn_commands
    out = {}
    for stage in (melee.Stage.BATTLEFIELD, melee.Stage.FINAL_DESTINATION):
        for c in reyn_commands(melee.Character.FOX, stage):
            out[c.phrase] = c.section
    return out


def parse_state(text):
    d = {who: (float(p), int(k)) for who, p, k in STATE.findall(text or "")}
    return d if len(d) == 2 else None


def timeline(log):
    """Decisions with the effective (router) command and the state they saw."""
    recs = [r for r in read(log) if r.get("type") == "decision"]
    active, out = None, []
    for r in recs:
        if r.get("changed") and "active" in r:
            active = r.get("active")
        elif r.get("changed") and r.get("command") == "none":
            active = None
        out.append({**r, "eff": active, "st": parse_state(r.get("state"))})
    return out


def windows(tl, end):
    """Per decision: what happened between its state and the next call's state (or the game end)."""
    out = []
    for a, b in zip(tl, tl[1:] + [None]):
        s0 = a["st"]
        s1 = b["st"] if b else end
        if not s0 or not s1:
            continue
        (mp0, mk0), (op0, ok0) = s0["YOU"], s0["OPP"]
        (mp1, mk1), (op1, ok1) = s1["YOU"], s1["OPP"]
        taken, lost = ok0 - ok1, mk0 - mk1
        dealt = op1 - op0 if not taken else op1
        got = mp1 - mp0 if not lost else mp1
        span = ((b["asked_frame"] if b else a["frame"] + 300) - (a["asked_frame"] or a["frame"]))
        out.append({"cmd": a["command"], "eff": a["eff"], "changed": a["changed"], "taken": taken, "lost": lost,
                    "dealt": max(0.0, dealt), "got": max(0.0, got), "span": span, "my_pct": mp0, "opp_pct": op0})
    return out


def end_state(r, port):
    st, pc = r.get("stocks") or {}, r.get("percent") or {}
    o = "2" if port == 1 else "1"
    if str(port) not in st:
        return None
    return {"YOU": (float(pc.get(str(port), 0)), int(st[str(port)])), "OPP": (float(pc.get(o, 0)), int(st[o]))}


def mean_ci(xs):
    if not xs:
        return float("nan"), float("nan")
    m = S.fmean(xs)
    return m, (1.96 * S.stdev(xs) / math.sqrt(len(xs)) if len(xs) > 1 else float("nan"))


# ---------------------------------------------------------------- reports

def cmd_logs(results):
    per = defaultdict(lambda: defaultdict(list))
    cmds, effs = defaultdict(Counter), defaultdict(Counter)
    for r, port, eid, log in coach_sides(results):
        tl = timeline(log)
        if not tl:
            continue
        p = per[eid]
        p["games"].append(1)
        p["calls"].append(len(tl))
        p["change_rate"].append(sum(d["changed"] for d in tl) / len(tl))
        lat = [d["latency_s"] for d in tl if d.get("latency_s") is not None]
        p["lat"] += lat
        p["lat_frames"] += [d["latency_frames"] for d in tl if d.get("latency_frames") is not None]
        routed = [d for d in tl if d["changed"] and d.get("router")]
        p["abstain"] += [(d["router"] or {}).get("outcome") == "abstain" for d in routed]
        p["none_frac"].append(sum(d["eff"] is None for d in tl) / len(tl))
        p["errors"] += [bool(d.get("error")) for d in tl]
        p["distinct"].append(len({d["eff"] for d in tl}))
        for d in tl:
            cmds[eid][d["command"]] += 1
            effs[eid][d["eff"]] += 1
    print(f"{'coach':8s} {'games':>5s} {'calls/g':>7s} {'change%':>7s} {'abst%':>6s} {'none%':>6s} {'distinct':>8s} "
          f"{'lat s':>6s} {'lat f':>6s} {'err%':>5s}")
    for eid, p in sorted(per.items(), key=lambda kv: SHORT.get(kv[0], kv[0])):
        print(f"{SHORT.get(eid, eid):8s} {len(p['games']):5d} {S.fmean(p['calls']):7.1f} {100 * S.fmean(p['change_rate']):7.1f} "
              f"{100 * S.fmean(p['abstain'] or [0]):6.1f} {100 * S.fmean(p['none_frac']):6.1f} {S.fmean(p['distinct']):8.1f} "
              f"{S.fmean(p['lat'] or [0]):6.2f} {S.fmean(p['lat_frames'] or [0]):6.1f} {100 * S.fmean(p['errors']):5.1f}")
    ab = defaultdict(Counter)
    for r, port, eid, log in coach_sides(results):
        for d in timeline(log):
            if d["changed"] and d.get("router"):
                ab[d["command"]][d["router"].get("outcome")] += 1
    worst = sorted(((c["abstain"] / sum(c.values()), k, sum(c.values())) for k, c in ab.items() if sum(c.values()) >= 8),
                   reverse=True)
    print("\nRouter abstains on (share of sends, n sends): " +
          ", ".join(f"{k} {100 * f:.0f}% ({n})" for f, k, n in worst[:10] if f > 0))
    for eid in sorted(per, key=lambda e: SHORT.get(e, e)):
        n = sum(effs[eid].values())
        top = ", ".join(f"{k or 'NONE'} {100 * v / n:.0f}%" for k, v in effs[eid].most_common(8))
        print(f"\n{SHORT.get(eid, eid)} effective (time share by calls): {top}")
        n = sum(cmds[eid].values())
        print(f"{SHORT.get(eid, eid)} chosen: " + ", ".join(f"{k} {100 * v / n:.0f}%" for k, v in cmds[eid].most_common(8)))


def all_windows(results, which=None):
    out = []
    for r, port, eid, log in coach_sides(results):
        if which and eid not in which:
            continue
        tl = timeline(log)
        for w in windows(tl, end_state(r, port)):
            out.append({**w, "eid": eid, "game": r["id"], "opp": r[f"p{3 - port}"]})
    return out


def cmd_windows(results):
    ws = all_windows(results)
    print("Per coach: mean per 5-s window (stocks taken - lost, % dealt - % taken)")
    by = defaultdict(list)
    for w in ws:
        by[w["eid"]].append(w)
    for eid, xs in sorted(by.items(), key=lambda kv: SHORT.get(kv[0], kv[0])):
        net = [w["taken"] - w["lost"] for w in xs]
        dmg = [w["dealt"] - w["got"] for w in xs]
        print(f"  {SHORT.get(eid, eid):8s} n={len(xs):5d} stock net {mean_ci(net)[0]:+.3f}±{mean_ci(net)[1]:.3f} "
              f"dmg net {mean_ci(dmg)[0]:+.1f}±{mean_ci(dmg)[1]:.1f}")
    # Random coach: effective command is randomised, so command -> window outcome is causal (short-term).
    rnd = [w for w in ws if w["eid"] == "coach:random"]
    base = [w["dealt"] - w["got"] for w in rnd if w["eff"] is None]
    print(f"\nRandom coach windows by effective command (n={len(rnd)}); NONE baseline dmg net "
          f"{mean_ci(base)[0]:+.1f}±{mean_ci(base)[1]:.1f} (n={len(base)})")
    by = defaultdict(list)
    for w in rnd:
        by[w["eff"]].append(w)
    rows = []
    for k, xs in by.items():
        if len(xs) < 15:
            continue
        dmg = [w["dealt"] - w["got"] for w in xs]
        net = [w["taken"] - w["lost"] for w in xs]
        rows.append((mean_ci(dmg)[0], k, len(xs), mean_ci(dmg)[1], mean_ci(net)[0], S.fmean(w["dealt"] for w in xs),
                     S.fmean(w["got"] for w in xs)))
    rows.sort(reverse=True)
    for row in rows[:12]:
        print(f"  {str(row[1] or 'NONE'):40s} n={row[2]:4d} dmg net {row[0]:+6.1f}±{row[3]:4.1f}  stock net {row[4]:+.3f} "
              f"dealt {row[5]:4.1f} got {row[6]:4.1f}")
    print("  ...")
    for row in rows[-8:]:
        print(f"  {str(row[1] or 'NONE'):40s} n={row[2]:4d} dmg net {row[0]:+6.1f}±{row[3]:4.1f}  stock net {row[4]:+.3f} "
              f"dealt {row[5]:4.1f} got {row[6]:4.1f}")
    sec = sections()
    by = defaultdict(list)
    for w in rnd:
        by[sec.get(w["eff"], "NONE" if w["eff"] is None else "?")].append(w["dealt"] - w["got"])
    print("  by menu section:")
    for k, xs in sorted(by.items(), key=lambda kv: -S.fmean(kv[1])):
        print(f"    {k:28s} n={len(xs):4d} dmg net {mean_ci(xs)[0]:+6.1f}±{mean_ci(xs)[1]:4.1f}")
    # windows right after a change vs held
    for eid, xs in sorted(defaultdict(list, {e: [w for w in ws if w["eid"] == e] for e in {w["eid"] for w in ws}}).items()):
        ch = [w["dealt"] - w["got"] for w in xs if w["changed"]]
        hd = [w["dealt"] - w["got"] for w in xs if not w["changed"]]
        if ch and hd:
            print(f"  {SHORT.get(eid, eid):8s} after change {mean_ci(ch)[0]:+.1f}±{mean_ci(ch)[1]:.1f} (n={len(ch)}) "
                  f"held {mean_ci(hd)[0]:+.1f}±{mean_ci(hd)[1]:.1f} (n={len(hd)})")


def elo_table(path=ROOT / "data/bench/standings.json"):
    st = json.loads(Path(path).read_text())
    return {r["id"]: r["elo"] for r in st["tracks"]["realtime"]["players"]}


def cmd_games(results):
    """Per coach game: score minus the score expected from the coach's own Elo, vs behaviour stats."""
    elo = elo_table()
    rows = []
    for r, port, eid, log in coach_sides(results):
        tl = timeline(log)
        opp = r[f"p{3 - port}"]
        if not tl or opp not in elo or eid not in elo:
            continue
        exp = 1 / (1 + 10 ** ((elo[opp] - elo[eid]) / 400))
        won = 1.0 if r.get("winner") == port else 0.0 if r.get("winner") else 0.5
        rows.append({"eid": eid, "resid": won - exp, "change": sum(d["changed"] for d in tl) / len(tl),
                     "none": sum(d["eff"] is None for d in tl) / len(tl), "distinct": len({d["eff"] for d in tl})})
    for key in ("change", "none", "distinct"):
        xs = sorted(rows, key=lambda x: x[key])
        h = len(xs) // 2
        lo, hi = [x["resid"] for x in xs[:h]], [x["resid"] for x in xs[h:]]
        print(f"{key:9s}: low half resid {mean_ci(lo)[0]:+.3f}±{mean_ci(lo)[1]:.3f}  high half {mean_ci(hi)[0]:+.3f}"
              f"±{mean_ci(hi)[1]:.3f}  (n={len(xs)}, split at {xs[h][key]:.2f})")


def cmd_ablations(results_path):
    """Fit ablation games together with the bench (+imports) on the real-time board; print new entrants."""
    from melee_llm.bench import imports, ratings
    from melee_llm.bench.entrants import by_id
    from melee_llm.bench.scheduler import read_results
    bench = read_results(BENCH)
    imp, _ = imports.load()
    abl = [r for r in read_results(Path(results_path)) if r.get("status") == "ok"]
    ents = by_id()
    tg = ratings.track_games(bench + imp, "realtime", ents) + abl
    f = ratings.Fit(tg)
    lo, hi = ratings.bootstrap(tg, f.players, 300)
    new = sorted({r["p1"] for r in abl} | {r["p2"] for r in abl})
    for i, p in enumerate(f.players):
        if p in new or p in SHORT:
            rec = ratings.record(p, tg)
            half = max(f.half_width(p), (hi[i] - lo[i]) / 2)
            print(f"{p:50s} {f.elo(p):6.0f} ±{half:4.0f}  n={rec['games']:3d} {rec['wins']}-{rec['losses']}-{rec['draws']}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "logs"
    res = read(BENCH)
    if len(sys.argv) > 2 and cmd != "ablations":
        res += read(sys.argv[2])
    {"logs": cmd_logs, "windows": cmd_windows, "games": cmd_games}.get(cmd, lambda r: None)(res)
    if cmd == "ablations":
        cmd_ablations(sys.argv[2])
