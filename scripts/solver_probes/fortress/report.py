"""Tables for section 14 of docs/optimal-play.md from data/fortress/*.jsonl (the output of scripts/fortress.sh)."""
import collections
import json
import sys

rows = [json.loads(line) for path in sys.argv[1:] if "bad-" not in path for line in open(path)]
bad = [json.loads(line) for path in sys.argv[1:] if "bad-" in path for line in open(path)]
plain = lambda r: not any(k in r["job"] for k in ("map", "value", "wb", "learn")) and "error" not in r
maps = sorted((r for r in rows if "map" in r["job"]), key=lambda r: (-r["job"]["ledge"], r["gap"]))
print("standing map (H, ledge, gap -> safe inputs)")
for r in maps:
    print(f"  H{r['job']['H']} ledge {r['job']['ledge']:>4} gap {r['gap']:6.2f}: {' '.join(r['safe']) or 'NONE'}  ({r['seconds']}s)")
groups = collections.defaultdict(list)
for r in rows:
    if plain(r):
        groups[(r["job"]["suite"], r["job"]["H"])].append(r)
print("\nsuite H games frames survived p2hit p1hit trade cracks(false/guess/forced/unsolved) min_gap min_ledge shields cpu_s")
for (suite, H), rs in sorted(groups.items()):
    res = collections.Counter(r["result"] for r in rs)
    cr = collections.Counter(str(c.get("verdict")) for r in rs for c in r["cracks"])
    print(f"{suite:13s} {H} {len(rs):3d} {sum(r['frames'] for r in rs):6d} {res['survived']:3d} "
          f"{res['P2 hit'] + res['P2 trapped']:3d} {res['P1 hit']:3d} {res['trade']:3d} "
          f"{sum(len(r['cracks']) for r in rs):3d} ({cr['false alarm']}/{cr['guess']}/{cr['forced']}/{cr['None']}) "
          f"{min(r['min_gap'] for r in rs):6.2f} {min(r['min_ledge'] for r in rs):6.2f} {sum(r['shields'] for r in rs):4d} "
          f"{sum(r['seconds'] for r in rs):7.0f}")
print("\ncracks and hits")
for r in rows:
    if not plain(r) or not (r["cracks"] or r["result"] != "survived"):
        continue
    print(f"{r['job']['id']}: {r['result']} after {r['frames']} frames, last inputs {' '.join(a + '/' + d for a, d in r['inputs'][-8:])}")
    for c in r["cracks"]:
        v = c["view"]
        print(f"   crack t={c['t']} gap {v['gap']:.2f} P1 {c['p1']} f{v['f1']} y{v['y1']:.1f} | P2 {c['p2']} f{v['f2']} ledge {v['ledge2']:.1f}"
              f" | values {c.get('values')} -> {c.get('verdict')} | walkback {c.get('walkback')}")
for r in rows:
    if "error" in r:
        print("ERROR", r["job"]["id"], r["error"][-300:])
print("\nexact values of standing positions")
for r in rows:
    if "value" in r["job"]:
        print(f"  ledge {r['job']['ledge']} gap {r['gap']}: {r['values']}")
print("\nwalk back (exact value k frames before the crack, replay at H)")
for r in rows:
    if "wb" in r["job"]:
        print(f"  {r['job']['id']}: values {r['values']}, replay {r['replay']['result']} {r['replay']['frames']} frames, cracks {r['replay_cracks']}")
print("\nlearning games (job: rounds, results, frames, cracks, positions marked, deepest walk back, closest to the ledge, cracks per round)")
for r in rows:
    if "learn" in r["job"] and "rounds" in r:
        rs = r["rounds"]
        res = dict(collections.Counter(x["result"] for x in rs))
        print(f"  {r['job']['id']:38s} {len(rs):3d} rounds {res}, {sum(x['frames'] for x in rs)} frames, {sum(x['cracks'] for x in rs)} cracks, "
              f"{sum(x['marked'] for x in rs)} marked, deepest {max(x['deepest'] for x in rs)}, ledge {min(x['min_ledge'] for x in rs):.2f}, "
              f"min gap {min(x['min_gap'] for x in rs):.2f}, per round {[x['cracks'] for x in rs][:12]}")
        for x in rs:
            if x["cracks"] or "no safe" in x["result"]:
                print(f"       {x['spec']:14s} {x['result']} {x['frames']} f, cracks {x['cracks']} marked {x['marked']} deepest {x['deepest']} first at {x['first_crack_t']}, ledge {x['min_ledge']:.2f}")
        print("       last round ends:", " ".join(a + "/" + d for a, d in rs[-1]["tail"][-8:]))
if bad:
    dec = [b for b in bad if b["p2"] in ("STANDING", "WALK_SLOW", "WALK_MIDDLE", "WALK_FAST", "DASHING", "RUNNING", "TURNING")]
    print(f"\n{len(bad)} marked positions, {len(dec)} with P2 free on the ground; earliest frame {min(b['t'] for b in bad)}, "
          f"largest gap {max(b['gap'] for b in bad)}, largest gap with P2 standing {max([b['gap'] for b in bad if b['p2'] == 'STANDING'] or [0])}")
    for k, n in collections.Counter((b["p1"], b["p2"]) for b in bad).most_common(15):
        print("   ", n, k)
    for b in sorted((b for b in bad if b["p2"] == "STANDING"), key=lambda b: -b["gap"])[:25]:
        print("    standing:", b["gap"], b["p1"], b["f1"], "y", b["y1"], "t", b["t"], "ledge", b["ledge"], b["spec"])
