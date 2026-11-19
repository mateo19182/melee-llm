"""Regenerate the Melee Bench write-up: figures and every number quoted in the post.

    python3 writeup/make_figures.py                  # snapshot the live bench data, then render
    python3 writeup/make_figures.py --from-snapshot  # render from writeup/snapshot.json only

Stage 1 (extract) reads data/bench/, the bench decision logs, the perception pilot and the
bot-writer ladder, and writes writeup/snapshot.json (committed, so the figures are reproducible
without the gitignored data). Stage 2 (render) writes writeup/figures/*.svg and fills
writeup/melee-bench.template.md into writeup/melee-bench.md. Edit prose in the template. The slides
(writeup/slides.html) are edited by hand; their numbers don't update from here.

Template placeholders, {{...}}:
    elo TRACK ID / ci TRACK ID / rec TRACK ID / n_games TRACK ID   (TRACK is rt or ut)
    delta TRACK A B          Elo of A minus Elo of B
    drop ID                  share of live replies dropped as stale
    any key of snapshot["numbers"]
Standard library only.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
from datetime import datetime, timezone, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
BENCH = ROOT / "data" / "bench"
PERCEPTION = ROOT / "replays" / "perception" / "paused" / "results.jsonl"
BOTWRITER = Path.home() / ".local/share/melee-llm/botwriter"
SNAPSHOT = HERE / "snapshot.json"
FIGS = HERE / "figures"
TRACKS = {"rt": "realtime", "ut": "untimed"}
CET = timezone(timedelta(hours=1))

LLMS = [  # model id, short name
    ("claude-haiku-4-5-20251001", "Haiku 4.5"),
    ("claude-sonnet-5-5", "Sonnet 5.5"),
    ("gpt-6-luna", "GPT-6 Luna"),
    ("gpt-6.1-sol", "GPT-6.1 Sol"),
]
LABELS = {
    "faynt": "Faynt 10M", "mimic": "MIMIC", "hal:MASTER": "HAL (master)", "reyn": "Reyn, uncoached",
    "phillip:gm": "Phillip gm", "phillip:plat": "Phillip plat", "phillip:silver": "Phillip silver",
    "llm_live:none": "No model: the live autopilot alone", "llm_live:random": "Random actions, live",
    "llm_paused:random": "Random actions, untimed",
    "coach:random": "Random coach", "coach_jev": "Jev coach", "jev_live": "Jev, live", "jev_paused": "Jev, untimed",
    "reyn:stock_protection": "Reyn holding \"Don't die.\"", "coach:random,fixed": "One random command, held",
    "coach:random,sticky": "Random coach, sticky", "coach:random,jev6": "Random coach, Jev's top 6",
    "coach_jev,interval=60": "Jev coach, every 1 s", "coach_jev,interval=900": "Jev coach, every 15 s",
    "coach_jev,features": "Jev coach + features", "coach:claude-haiku-4-5-20251001,features": "Haiku 4.5 coach + features",
}
# Coach deep-dive variants share the board's fit but stay off the overview chart, except this one.
SHOW_INACTIVE = {"reyn:stock_protection"}


def deepdive(p: dict) -> bool:
    return not p.get("active", True) and ("," in p["id"] or p["id"].startswith("reyn:")) and p["id"] not in SHOW_INACTIVE
for _m, _n in LLMS:
    LABELS[f"llm_live:{_m}"] = f"{_n}, live"
    LABELS[f"llm_paused:{_m}"] = f"{_n}, untimed"
    LABELS[f"coach:{_m}"] = f"{_n} coach"


STARTER = "written:haiku-5.5-high/run1"  # handed in the round-2 starter bot unchanged


def label(i: str) -> str:
    if m := re.fullmatch(r"written:(\w+)-([\d.]+)(?:-(\w+))?/run(\d)", i):
        model, ver, effort, run = m.groups()
        name = f"{model.capitalize()} {ver}, {effort + ' effort' if effort else 'first try'}, run {run}"
        return "The starter bot (Haiku left it as it was)" if i == STARTER else name
    return LABELS.get(i) or (f"CPU {i[4:]}" if i.startswith("cpu:") else i)


# ---------------------------------------------------------------- extract

def extract() -> dict:
    st = json.loads((BENCH / "standings.json").read_text())
    status = json.loads((BENCH / "status.json").read_text())
    ents = st["entrants"]
    boards = {}
    for key, track in TRACKS.items():
        boards[key] = [
            {"id": p["id"], "category": ents.get(p["id"], {}).get("category", "?"), "elo": p["elo"],
             "lo": p["elo_lo"], "hi": p["elo_hi"], "games": p["games"], "w": p["wins"], "l": p["losses"],
             "d": p["draws"], "stock_diff": p["stock_diff"], "converged": p.get("converged"),
             "active": ents.get(p["id"], {}).get("active", True)}
            for p in st["tracks"][track]["players"]
        ]

    # Live players: replies older than max_stale are dropped, and their tokens are not in `sides`.
    drops: dict[str, dict] = {}
    fps: dict[str, list] = {}
    for line in (BENCH / "results.jsonl").open():
        r = json.loads(line)
        if r.get("status") != "ok":
            continue
        for port, side in r["sides"].items():
            spec = r["spec" + port]
            if not spec.startswith(("llm_live", "jev_live")):
                continue
            d = drops.setdefault(spec, {"decisions": 0, "dropped": 0, "games": 0, "tokens_counted": 0})
            d["games"] += 1
            d["tokens_counted"] += side.get("prompt_tokens", 0) + side.get("completion_tokens", 0)
            fps.setdefault(spec, []).append(r.get("fps") or 0)
            try:
                for x in open(side["log"]):
                    t = json.loads(x).get("type")
                    d["decisions"] += t == "decision"
                    d["dropped"] += t == "dropped"
            except OSError:
                pass
    for spec, d in drops.items():
        per_call = d["tokens_counted"] / max(d["decisions"], 1)
        d["tokens_est_total"] = round(d["tokens_counted"] + d["dropped"] * per_call)
        d["median_fps"] = round(statistics.median(fps[spec]), 1)

    perception = {}
    if PERCEPTION.exists():
        for line in PERCEPTION.open():
            r = json.loads(line)
            obs = r["cond"].split("obs=")[-1]
            p = perception.setdefault(obs, {"n": 0, "w": 0, "stock_diff": []})
            p["n"] += 1
            p["w"] += r["winner"] == 1
            p["stock_diff"].append(r["stocks"]["1"] - r["stocks"]["2"])
        for p in perception.values():
            p["stock_diff"] = round(statistics.fmean(p["stock_diff"]), 2)

    botwriter = {}
    for m in (BOTWRITER / "sessions").glob("*/meta.json"):
        meta = json.loads(m.read_text())
        botwriter[meta["name"]] = {"cost_usd": meta.get("cost_usd"), "lines": meta.get("bot_lines"),
                                   "minutes": round(meta.get("wall_s", 0) / 60, 1)}

    return {
        "as_of": st["generated"],
        "games": {"bench": st["games"]["bench"], "imported": st["games"]["imported"],
                  "board": st["board"]["games"]},
        "status": {k: status[k] for k in ("started_at", "updated", "phase", "stop_reason", "budget_tokens",
                                          "spent", "spent_recounted", "games_started", "unconverged") if k in status},
        "boards": boards, "live": drops, "perception": perception, "botwriter": botwriter,
    }


# ---------------------------------------------------------------- numbers

def numbers(s: dict) -> dict:
    t0, t1 = s["status"]["started_at"], s["status"]["updated"]
    rt = {p["id"]: p for p in s["boards"]["rt"]}
    coaches = [rt[f"coach:{m}"]["elo"] for m, _ in LLMS if f"coach:{m}" in rt]
    live = [rt[f"llm_live:{m}"]["elo"] for m, _ in LLMS if f"llm_live:{m}" in rt]
    ut = {p["id"]: p for p in s["boards"]["ut"]}
    paused = [ut[f"llm_paused:{m}"]["elo"] for m, _ in LLMS if f"llm_paused:{m}" in ut]
    taxes = [ut[f"llm_paused:{m}"]["elo"] - rt[f"llm_live:{m}"]["elo"] for m, _ in LLMS]
    per = s["perception"]
    groups: dict[str, list] = {}
    for i, p in rt.items():
        if m := re.fullmatch(r"written:(\w+)-[\d.]+-(\w+)/run\d", i):
            groups.setdefault(f"{m[1]}_{m[2]}", []).append(p["elo"])
    written = [p["elo"] for i, p in rt.items() if i.startswith("written:")]
    return {
        **{f"w_{g}_mean": f"{statistics.fmean(v):.0f}" for g, v in groups.items()},
        **{f"w_{g}_min": f"{min(v):.0f}" for g, v in groups.items()},
        **{f"w_{g}_max": f"{max(v):.0f}" for g, v in groups.items()},
        "n_written": str(len(written)), "written_min": f"{min(written):.0f}", "written_max": f"{max(written):.0f}",
        "n_written_above_cpu9": str(sum(e > 1500 for e in written)),
        "as_of": datetime.fromtimestamp(s["as_of"], CET).strftime("%Y-%m-%d %H:%M CET"),
        "hours": f"{(t1 - t0) / 3600:.1f}",
        "games_bench": f"{s['games']['bench']:,}", "games_imported": f"{s['games']['imported']:,}",
        "games_board": f"{s['games']['board']:,}",
        "coach_llm_min": f"{min(coaches):.0f}", "coach_llm_max": f"{max(coaches):.0f}",
        "coach_delta_min": f"{min(coaches) - rt['coach:random']['elo']:+.0f}",
        "coach_delta_max": f"{max(coaches) - rt['coach:random']['elo']:+.0f}",
        "live_min": f"{min(live):.0f}", "live_max": f"{max(live):.0f}",
        "paused_rest_min": f"{sorted(paused)[0]:.0f}", "paused_rest_max": f"{sorted(paused)[-2]:.0f}",
        "tax_min": f"{min(taxes):.0f}", "tax_max": f"{max(taxes):.0f}",
        "phase": s["status"]["phase"],
        "n_entrants": str(len({p["id"] for b in s["boards"].values() for p in b})),
        **{f"perc_{k}": f"{v['w']}–{v['n'] - v['w']}" for k, v in per.items()},
        **{f"perc_{k}_n": str(v["n"]) for k, v in per.items()},
    }


def resolve(key: str, s: dict, nums: dict) -> str:
    parts = key.split()
    boards = {t: {p["id"]: p for p in s["boards"][t]} for t in TRACKS}
    match parts:
        case ["elo", t, i]:
            return f"{boards[t][i]['elo']:.0f}"
        case ["ci", t, i]:
            return f"{boards[t][i]['lo']:.0f}–{boards[t][i]['hi']:.0f}"
        case ["rec", t, i]:
            p = boards[t][i]
            return f"{p['w']}–{p['l']}" + (f"–{p['d']}" if p["d"] else "")
        case ["n_games", t, i]:
            return str(boards[t][i]["games"])
        case ["delta", t, a, b]:
            return f"{boards[t][a]['elo'] - boards[t][b]['elo']:+.0f}"
        case ["drop", i]:
            d = s["live"][i]
            return f"{100 * d['dropped'] / (d['decisions'] + d['dropped']):.0f}%"
        case [k] if k in nums:
            return nums[k]
    raise KeyError(f"unknown placeholder {{{{{key}}}}}")


# ---------------------------------------------------------------- SVG

# Reference palette (dataviz skill), its dark-background slots in fixed order.
SERIES = {"learned": "#3987e5", "coach": "#d95926", "written": "#199e70", "llm": "#c98500", "jev": "#d55181", "ref": "#898781"}
SHAPES = {"learned": "circle", "coach": "diamond", "written": "square", "llm": "triangle", "jev": "tri_down",
          "ref": "circle", "scripted": "square"}
CAT = {"cpu": "ref", "scripted": "ref", "learned": "learned", "coach": "coach", "written": "written",
       "llm": "llm", "jev": "jev"}
LEGEND = [("learned", "learned", "Learned bot"), ("coach", "coach", "LLM or Jev coaching Reyn"),
          ("written", "written", "Bot written by an LLM"), ("llm", "llm", "LLM playing directly"),
          ("jev", "jev", "Jev playing directly"), ("ref", "ref", "Built-in CPU or a player with no model")]

FONT = 'system-ui, -apple-system, "Segoe UI", sans-serif'
BLOG_FONT = 'Geist, Inter, system-ui, -apple-system, "Segoe UI", sans-serif'

# "site": the web UI's dark navy (melee_llm/web/static/style.css). The blog pair sits on the blog's
# own surfaces (blog-19182 assets/styles.css) with no background of its own; series steps from the
# reference palette, validated against #e9e7e1 and #0c0c0c.
THEMES = {
    "site": {"bg": "#080b28", "ring": "#080b28", "t1": "#e8ebf7", "t2": "#b5bbdc", "tm": "#8088b4",
             "grid": "#1b2250", "axis": "#2e3878", "band": "#9198c0", "conn": "#3a4590", "font": FONT,
             "series": SERIES},
    "blog-light": {"bg": None, "ring": "#e9e7e1", "t1": "#2b2926", "t2": "#4a4640", "tm": "#7d786e",
                   "grid": "#d8d5cd", "axis": "#a8a398", "band": "#6a655c", "conn": "#bdb8ad", "font": BLOG_FONT,
                   "series": {"learned": "#2a78d6", "coach": "#eb6834", "written": "#1baf7a", "llm": "#eda100",
                              "jev": "#e87ba4", "ref": "#8a8579"}},
    "blog-dark": {"bg": None, "ring": "#0c0c0c", "t1": "#f5f5f5", "t2": "#c8c8c8", "tm": "#8a8a8a",
                  "grid": "#232323", "axis": "#4a4a4a", "band": "#b0b0b0", "conn": "#3a3a3a", "font": BLOG_FONT,
                  "series": SERIES},
}
THEME = THEMES["site"]
OUT = FIGS


def style() -> str:
    th = THEME
    series = "".join(f".c-{k}{{fill:{c};stroke:{c}}}" for k, c in th["series"].items())
    base = (f".bg{{fill:{th['bg']}}}.ring{{stroke:{th['ring']}}}.t1{{fill:{th['t1']}}}.t2{{fill:{th['t2']}}}"
            f".tm{{fill:{th['tm']}}}.grid{{stroke:{th['grid']}}}.axis{{stroke:{th['axis']}}}"
            f".band{{fill:{th['band']};fill-opacity:.12}}.conn{{stroke:{th['conn']}}}")
    return (f"<style>text{{font-family:{th['font']};font-variant-numeric:tabular-nums}}{base}{series}"
            f".ci{{fill:none;stroke-width:2;stroke-linecap:round}}.hollow{{fill-opacity:0}}</style>")


def esc(t: str) -> str:
    return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def text(x, y, t, cls="t1", size=12, anchor="start", weight=None) -> str:
    w = f' font-weight="{weight}"' if weight else ""
    return f'<text x="{x:.1f}" y="{y:.1f}" class="{cls}" font-size="{size}" text-anchor="{anchor}"{w}>{esc(t)}</text>'


def marker(x, y, cls, shape, r=4.5, hollow=False) -> str:
    c = f'c-{cls} ring{" hollow" if hollow else ""}'
    sw = 'stroke-width="2"'
    if hollow:  # outline in series color, no ring
        c, sw = f"c-{cls} hollow", 'stroke-width="2"'
    if shape == "circle":
        return f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r}" class="{c}" {sw}/>'
    if shape == "square":
        return f'<rect x="{x - r:.1f}" y="{y - r:.1f}" width="{2 * r}" height="{2 * r}" rx="1" class="{c}" {sw}/>'
    k = r * 1.3
    pts = {"diamond": [(0, -k), (k, 0), (0, k), (-k, 0)],
           "triangle": [(0, -k), (k, k * .8), (-k, k * .8)],
           "tri_down": [(0, k), (k, -k * .8), (-k, -k * .8)]}[shape]
    p = " ".join(f"{x + a:.1f},{y + b:.1f}" for a, b in pts)
    return f'<polygon points="{p}" class="{c}" {sw} stroke-linejoin="round"/>'


class Chart:
    def __init__(self, title, subtitle, n_rows, x0, x1, ticks, width=760, label_w=200, right_w=96,
                 row_h=20, legend=None, top_extra=0):
        self.W, self.lx, self.rw, self.rh = width, label_w, right_w, row_h
        self.px0, self.px1 = label_w + 16, width - right_w - 12
        self.x0, self.x1, self.ticks = x0, x1, ticks
        rows, x = [[]], 16
        for item in legend or []:
            w = 28 + len(item[2]) * 6.9
            if x + w > width - 16:
                rows.append([])
                x = 16
            rows[-1].append((x, item))
            x += w
        self.top = 58 + (20 * len(rows) + 4 if legend else 0) + top_extra
        self.H = self.top + n_rows * row_h + 40
        self.out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {self.W} {self.H}" '
                    f'width="{self.W}" height="{self.H}" role="img" aria-label="{esc(title)}">',
                    f"<title>{esc(title)}</title>", style(),
                    *([f'<rect class="bg" x="0" y="0" width="{self.W}" height="{self.H}" rx="8"/>'] if THEME["bg"] else []),
                    text(16, 26, title, "t1", 15, weight=600), text(16, 45, subtitle, "t2", 12)]
        for r, items in enumerate(rows if legend else []):
            y = 64 + 20 * r
            for x, (cls, shape, name) in items:
                self.out.append(marker(x + 5, y, cls, SHAPES[shape]))
                self.out.append(text(x + 15, y + 4, name, "t2", 11.5))
        self.grid()

    def sx(self, v):
        return self.px0 + (min(max(v, self.x0), self.x1) - self.x0) / (self.x1 - self.x0) * (self.px1 - self.px0)

    def ry(self, i):
        return self.top + i * self.rh + self.rh / 2

    def grid(self):
        y0, y1 = self.top - 6, self.H - 34
        for t in self.ticks:
            x = self.sx(t)
            self.out.append(f'<line x1="{x:.1f}" x2="{x:.1f}" y1="{y0}" y2="{y1}" class="grid" stroke-width="1"/>')
            self.out.append(text(x, y1 + 16, f"{t:,}", "tm", 11, "middle"))
        self.out.append(text(self.px1, y1 + 32, "Elo (CPU 9 = 1500)", "tm", 11, "end"))

    def ref(self, v, name, anchor="start"):
        x = self.sx(v)
        self.out.append(f'<line x1="{x:.1f}" x2="{x:.1f}" y1="{self.top - 6}" y2="{self.H - 34}" '
                        f'class="axis" stroke-width="1.5"/>')
        self.out.append(text(x + (4 if anchor == "start" else -4), self.top + 4, name, "tm", 10.5, anchor))

    def band(self, lo, hi, name):
        a, b = self.sx(lo), self.sx(hi)
        self.out.append(f'<rect x="{a:.1f}" y="{self.top - 6}" width="{b - a:.1f}" '
                        f'height="{self.H - 34 - self.top + 6}" class="band"/>')
        self.out.append(text((a + b) / 2, self.top - 10, name, "tm", 10.5, "middle"))

    def row(self, i, name, elo, lo, hi, cls, shape, right="", hollow=False, dy=0, emph=False):
        y = self.ry(i) + dy
        self.out.append(text(self.lx, y + 4, name, "t1" if emph else "t2", 12, "end", 600 if emph else None))
        if lo is not None:
            self.out.append(f'<line x1="{self.sx(lo):.1f}" x2="{self.sx(hi):.1f}" y1="{y:.1f}" y2="{y:.1f}" '
                            f'class="ci c-{cls}" stroke-opacity=".55"/>')
        self.out.append(marker(self.sx(elo), y, cls, shape, hollow=hollow))
        if elo > self.x1:
            self.out.append(text(self.px1 + 2, y + 4, "→", "t2", 12))
        if right:
            self.out.append(text(self.W - 14, y + 4, right, "tm", 11, "end"))

    def header(self, i, name):
        self.out.append(text(16, self.ry(i) + 5, name, "t1", 12.5, weight=600))

    def save(self, name):
        self.out.append("</svg>")
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / name).write_text("\n".join(self.out) + "\n")


def kind(p):
    cat = p["category"]
    return CAT.get(cat, "ref"), SHAPES["scripted" if cat == "scripted" else CAT.get(cat, "ref")]


BLOG_HIDE = {f"cpu:{k}" for k in (2, 3, 4, 6, 7, 8)}


def fig_leaderboard(s, n, blog=False):
    # 27 written bots would swamp the chart: keep the best and the weakest, the rest are in their own figure
    written = sorted((p for p in s["boards"]["rt"] if p["id"].startswith("written:")), key=lambda p: p["elo"])
    hide = {p["id"] for p in written[1:-1]}
    names = {written[-1]["id"]: f"Best written bot ({label(written[-1]['id']).split(',')[0]})",
             written[0]["id"]: f"Weakest written bot ({label(written[0]['id']).split(',')[0]})"}
    rows = [p for p in s["boards"]["rt"] if not deepdive(p) and p["id"] not in hide]
    if blog:
        coaches = sorted((p for p in rows if p["category"] == "coach" and p["id"].startswith("coach:")
                          and not p["id"].startswith("coach:random")), key=lambda p: -p["elo"])
        drop = BLOG_HIDE | {written[0]["id"], written[-1]["id"]} | {p["id"] for p in coaches[1:]}
        names[coaches[0]["id"]] = "Best LLM coach"
        rows = [p for p in rows if p["id"] not in drop]
        # written bots: one setting only, the high-effort batch, each model's best run
        best = {}
        for p in s["boards"]["rt"]:
            if (m := re.fullmatch(r"written:(\w+)-[\d.]+-high/run\d", p["id"])) and p["id"] != STARTER:
                if m[1] not in best or p["elo"] > best[m[1]]["elo"]:
                    best[m[1]] = p
        for model, p in best.items():
            names[p["id"]] = f"{label(p['id']).split(',')[0]} bot, best of 5"
        rows = sorted(rows + list(best.values()), key=lambda p: -p["elo"])
    c = Chart("Every bot that plays in real time" if blog else "Melee Bench, everyone who plays in real time",
              f"Fox ditto, BF/FD, full games. Dot: Bradley-Terry Elo; line: 95% interval. Snapshot {n['as_of']}.",
              len(rows), 500, 2700, list(range(500, 2701, 250)), legend=LEGEND)
    c.ref(1500, "CPU 9 anchor")
    for i, p in enumerate(rows):
        cls, shape = kind(p)
        right = f"{p['elo']:.0f}"
        if p["elo"] > c.x1:
            right = f"{p['elo']:.0f}, {p['w']}–{p['l']}"
        c.row(i, names.get(p["id"]) or label(p["id"]), p["elo"], p["lo"], p["hi"], cls, shape, right,
              emph=p["id"] in SHOW_INACTIVE)
    c.save("leaderboard-realtime.svg")


def fig_coach(s, n, blog=False):
    rt = {p["id"]: p for p in s["boards"]["rt"]}
    coaches = sorted((f"coach:{m}" for m, _ in LLMS if f"coach:{m}" in rt), key=lambda i: rt[i]["elo"])
    held = [] if blog else ["coach:random,fixed"]  # the post doesn't discuss the held random command
    ids = [i for i in ["reyn", *held, "coach:random", *coaches, "coach_jev", "reyn:stock_protection"]
           if i in rt]
    c = Chart("Coaching Reyn: what actually helps?",
              "Real-time board. Coaches pick one of Reyn's ~100 commands every 5 s. Shaded: random coach's 95% interval.",
              len(ids), 1600, 2700, list(range(1600, 2701, 200)), top_extra=6,
              legend=[("learned", "learned", "Reyn, no coach"), ("ref", "coach", "Random commands"),
                      ("coach", "coach", "LLM or Jev coach")])
    rnd = rt["coach:random"]
    c.band(rnd["lo"], rnd["hi"], "random coach")
    for ref in ("hal:MASTER", "phillip:gm"):
        if ref in rt:
            c.ref(rt[ref]["elo"], label(ref))
    for i, k in enumerate(ids):
        p = rt[k]
        cls = "learned" if k.startswith("reyn") else ("ref" if k.startswith("coach:random") else "coach")
        shape = "circle" if k.startswith("reyn") else "diamond"
        c.row(i, label(k), p["elo"], p["lo"], p["hi"], cls, shape, f"{p['elo']:.0f}  n={p['games']}",
              emph=k in ("coach_jev", "reyn:stock_protection"))
    c.save("coaching.svg")


def fig_latency(s, n):
    rt = {p["id"]: p for p in s["boards"]["rt"]}
    ut = {p["id"]: p for p in s["boards"]["ut"]}
    pairs = [(name, f"llm_paused:{m}", f"llm_live:{m}") for m, name in LLMS] + [("Jev", "jev_paused", "jev_live")]
    pairs.sort(key=lambda t: -ut[t[1]]["elo"])
    c = Chart("The latency tax: same model, untimed vs real time",
              "Untimed: the game waits for every decision. Real time: 60 fps, never waits. 95% intervals are about ±125-190.",
              len(pairs), 600, 1900, list(range(600, 1901, 200)), right_w=120,
              legend=[("learned", "learned", "Untimed (game waits)"), ("coach", "learned", "Real time")])
    for v, nm in ((1500, "CPU 9"), (rt["cpu:1"]["elo"], "CPU 1"), (rt["llm_live:none"]["elo"], "no model")):
        c.ref(v, nm, "end" if nm == "no model" else "start")
    c.out.append(text(c.W - 14, c.top - 10, "replies too stale", "tm", 10.5, "end"))
    for i, (name, a, b) in enumerate(pairs):
        y = c.ry(i)
        pa, pb = ut[a], rt[b]
        c.out.append(f'<line x1="{c.sx(pb["elo"]):.1f}" x2="{c.sx(pa["elo"]):.1f}" y1="{y}" y2="{y}" '
                     f'class="conn" stroke-width="2"/>')
        d = s["live"].get(b)
        drop = f"{100 * d['dropped'] / (d['decisions'] + d['dropped']):.0f}% dropped" if d else ""
        c.row(i, name, pa["elo"], None, None, "learned", "circle", drop, emph=True)
        c.out.append(marker(c.sx(pb["elo"]), y, "coach", "circle"))
    c.save("latency-tax.svg")


BATCHES = [(None, "One try per model"), ("medium", "Three runs each, medium effort"),
           ("high", "Five runs each, high effort, new starter bot")]


def fig_botwriter_blog(s, n):
    rt = {p["id"]: p for p in s["boards"]["rt"]}
    bw = s["botwriter"]
    groups = []
    for effort, title in BATCHES:
        ids = [i for i in rt if (m := re.fullmatch(r"written:(\w+)-([\d.]+)(?:-(\w+))?/run(\d)", i)) and m[3] == effort]
        groups.append((title, sorted(ids, key=lambda i: -rt[i]["elo"])))
    c = Chart("Bots written by LLMs in 30 minutes",
              "One row per 30-minute coding session. Right: API-equivalent cost and the bot's length.",
              sum(len(g) + 1 for _, g in groups), 800, 2200, list(range(800, 2201, 200)), label_w=200, right_w=120)
    c.ref(1500, "CPU 9")
    c.ref(rt["mimic"]["elo"], "MIMIC")
    i = 0
    for title, ids in groups:
        c.header(i, title)
        i += 1
        for k in ids:
            p = rt[k]
            m = re.fullmatch(r"written:(\w+)-([\d.]+)(?:-(\w+))?/run(\d)", k)
            name = f"{m[1].capitalize()} {m[2]}" + (f", run {m[4]}" if m[3] else "")
            if k == STARTER:
                name = "Starter bot, unchanged"
            meta = bw.get(k.removeprefix("written:"), {})
            right = f"${meta['cost_usd']:.2f}, {meta['lines']} lines" if meta.get("cost_usd") else ""
            c.row(i, name, p["elo"], p["lo"], p["hi"], "ref" if k == STARTER else "written",
                  "circle" if k == STARTER else "square", right)
            i += 1
    c.save("bot-writer.svg")


def fig_botwriter_simple(s, n):
    """The high-effort batch only: same starter bot, five runs per model. One row per model,
    a dot per session, a bar at the mean."""
    rt = {p["id"]: p for p in s["boards"]["rt"]}
    runs = {}
    for k, p in rt.items():
        if m := re.fullmatch(r"written:(\w+)-([\d.]+)-high/run\d", k):  # the starter run counts: a real session
            runs.setdefault(f"{m[1].capitalize()} {m[2]}", []).append(p["elo"])
    models = sorted(runs, key=lambda k: -statistics.mean(runs[k]))
    c = Chart("Bots written by LLMs in 30 minutes",
              "Five 30-minute sessions per model at high effort, same starter bot. Dot: one session; bar: the average.",
              len(models), 1300, 2100, list(range(1300, 2101, 100)), label_w=110, right_w=150, row_h=44)
    c.ref(1500, "CPU 9")
    c.ref(rt[STARTER]["elo"], "starter bot")
    c.ref(rt["mimic"]["elo"], "MIMIC")
    for i, model in enumerate(models):
        y = c.ry(i)
        c.out.append(text(c.lx, y + 4, model, "t1", 13, "end", 600))
        for j, e in enumerate(sorted(runs[model])):
            c.out.append(marker(c.sx(e), y + (j % 2 * 2 - 1) * 5, "written", "circle", r=5))
        avg = statistics.mean(runs[model])
        c.out.append(f'<line x1="{c.sx(avg):.1f}" x2="{c.sx(avg):.1f}" y1="{y - 14:.1f}" y2="{y + 14:.1f}" '
                     f'class="c-written" stroke-width="3" stroke-linecap="round"/>')
        c.out.append(text(c.W - 14, y + 4, f"avg {avg:.0f}, {min(runs[model]):.0f}–{max(runs[model]):.0f}", "tm", 11, "end"))
    c.save("bot-writer-simple.svg")


def fig_botwriter(s, n):
    rt = {p["id"]: p for p in s["boards"]["rt"]}
    ids = [i for i in rt if i.startswith("written:")] + ["cpu:9", "cpu:7", "cpu:1", "mimic", "phillip:silver"]
    ids = sorted((i for i in ids if i in rt), key=lambda i: -rt[i]["elo"])
    bw = s["botwriter"]
    c = Chart("Bots written by LLMs in 30 minutes",
              "Each row is one 30-minute coding session. Right: API-equivalent cost of the session and the bot's length.",
              len(ids), 800, 2200, list(range(800, 2201, 200)), label_w=270, right_w=120,
              legend=[("written", "written", "Written by an LLM"), ("learned", "learned", "Learned bot"),
                      ("ref", "ref", "Built-in CPU")])
    c.ref(1500, "CPU 9 anchor")
    for i, k in enumerate(ids):
        p = rt[k]
        cls, shape = kind(p)
        meta = bw.get(k.removeprefix("written:"), {})
        right = f"${meta['cost_usd']:.2f}, {meta['lines']} lines" if meta.get("cost_usd") else ""
        c.row(i, label(k), p["elo"], p["lo"], p["hi"], cls, shape, right, emph=k.startswith("written:"))
    c.save("bot-writer.svg")


# ---------------------------------------------------------------- main

def render(s: dict) -> None:
    n = numbers(s)
    for f in (fig_leaderboard, fig_coach, fig_latency, fig_botwriter):
        f(s, n)
    tpl = (HERE / "melee-bench.template.md").read_text()
    out = re.sub(r"\{\{([^}]+)\}\}", lambda m: n.get(m.group(1).strip()) or resolve(m.group(1).strip(), s, n), tpl)
    (HERE / "melee-bench.md").write_text(out)
    print(f"rendered {len(list(FIGS.glob('*.svg')))} figures and melee-bench.md, snapshot {n['as_of']}")


def render_blog(s: dict, out: Path) -> None:
    """The four charts in the blog's colours, NAME.svg (light) and NAME-dark.svg, trimmed for the post."""
    global THEME, OUT
    n = numbers(s)
    for theme, suffix in (("blog-light", ""), ("blog-dark", "-dark")):
        THEME, OUT = THEMES[theme], out / theme
        fig_leaderboard(s, n, blog=True)
        fig_coach(s, n, blog=True)
        fig_latency(s, n)
        fig_botwriter_blog(s, n)
        fig_botwriter_simple(s, n)
        for f in OUT.glob("*.svg"):
            f.replace(out / f"{f.stem}{suffix}.svg")
        OUT.rmdir()
    THEME, OUT = THEMES["site"], FIGS
    print(f"rendered blog figures to {out}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--from-snapshot", action="store_true", help="skip extraction, use writeup/snapshot.json")
    ap.add_argument("--blog", type=Path, metavar="DIR", help="only write the blog's light and dark figures to DIR")
    a = ap.parse_args()
    if a.blog:
        return render_blog(json.loads(SNAPSHOT.read_text()), a.blog)
    if not a.from_snapshot:
        SNAPSHOT.write_text(json.dumps(extract(), indent=1) + "\n")
    render(json.loads(SNAPSHOT.read_text()))


if __name__ == "__main__":
    main()
