"""The experiment log in docs/experiments/: one Markdown file per experiment, with a header of `key: value` lines.

    python scripts/experiments.py new SLUG "Title"   # next free number, status planned; then fill it in
    python scripts/experiments.py index              # rewrite the table in docs/experiments/README.md
    python scripts/experiments.py check              # exit 1 if a header is incomplete or the index is stale

Header keys: id, title, date, status (planned, running, done, abandoned), result, verdict (one line each, shown in
the index), runs (directories in data/train/runs), prs, follows (ids this builds on). Lists are comma-separated.
"""
import datetime, re, sys
from pathlib import Path

DIR = Path(__file__).resolve().parent.parent / "docs/experiments"
KEYS = ["id", "title", "date", "status", "result", "verdict", "runs", "prs", "follows"]
STATUS = ["planned", "running", "done", "abandoned"]
START, END = "<!-- index:start -->", "<!-- index:end -->"
TEMPLATE = """## Question

What we want to know, and why it matters now.

## Setup

Model, data, settings, and the one thing that changes.

## Judged by

Which games, how many, at what delay. Written before launching.

## Result

## Verdict
"""


def read(path):
    head, _, body = path.read_text().removeprefix("---\n").partition("\n---\n")
    return dict(re.match(r"(\w+):\s*(.*)", l).groups() for l in head.splitlines() if l.strip()), body


def entries():
    return [(read(p)[0], p) for p in sorted(DIR.glob("E[0-9]*.md"))]


def table():
    rows = ["| # | Date | Status | Experiment | Result | Verdict |", "|---|---|---|---|---|---|"]
    for h, p in entries():
        rows.append(f"| [{h['id']}]({p.name}) | {h['date'][5:]} | {h['status']} | {h['title']} | {h['result']} | {h['verdict']} |")
    return "\n".join(rows)


def index(write=True):
    readme = DIR / "README.md"
    text = readme.read_text()
    new = text[: text.index(START) + len(START)] + "\n" + table() + "\n" + text[text.index(END):]
    if write:
        readme.write_text(new)
    return new == text


def check():
    bad = []
    for h, p in entries():
        missing = [k for k in KEYS[:6] if k not in h] + [k for k in ("title", "date") if not h.get(k)]
        if missing or h.get("status") not in STATUS or not p.name.startswith(h.get("id", "?") + "-"):
            bad.append(f"{p.name}: missing {missing or ''} status={h.get('status')}")
        elif h["status"] in ("done", "abandoned") and not (h["result"] and h["verdict"]):
            bad.append(f"{p.name}: {h['status']} without result and verdict")
    if not index(write=False):
        bad.append("README.md index is stale: run `python scripts/experiments.py index`")
    print("\n".join(bad) or f"{len(entries())} experiments ok")
    return 1 if bad else 0


def new(slug, title):
    n = max([int(h["id"][1:]) for h, _ in entries()], default=0) + 1
    head = dict(id=f"E{n:02d}", title=title, date=datetime.date.today().isoformat(), status="planned")
    path = DIR / f"E{n:02d}-{slug}.md"
    path.write_text("---\n" + "\n".join(f"{k}: {head.get(k, '')}".rstrip() for k in KEYS) + f"\n---\n\n{TEMPLATE}")
    index()
    print(path)


if __name__ == "__main__":
    cmd, *args = sys.argv[1:] or ["check"]
    sys.exit({"new": lambda: new(*args), "index": index, "check": check}[cmd]() and cmd == "check")
