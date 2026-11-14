"""Render writeup/melee-bench.md as a standalone page, writeup/index.html (figures and media stay relative).

    uv run python writeup/build_page.py
"""
from __future__ import annotations

import html
import re
from pathlib import Path

from markdown_it import MarkdownIt

HERE = Path(__file__).resolve().parent

CSS = """
:root{--fg:#1b1b1a;--muted:#5d5c58;--bg:#fcfcfb;--rule:#e1e0d9;--code:#f1f0ec;--link:#1f63b8;--p1:#e5383b;--p2:#2a78d6}
@media (prefers-color-scheme:dark){:root{--fg:#ecebe7;--muted:#a9a8a1;--bg:#1a1a19;--rule:#33332f;--code:#252523;--link:#7fb2f0}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:18px/1.65 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:46rem;margin:0 auto;padding:3rem 1.25rem 5rem}
h1{font-size:2.6rem;line-height:1.1;margin:0 0 .3rem;letter-spacing:-.02em}
.meta{color:var(--muted);margin-bottom:2rem;font-size:.95rem}
h2{font-size:1.6rem;margin:2.6rem 0 .6rem;line-height:1.2}
h3{font-size:1.2rem;margin:2rem 0 .4rem}
a{color:var(--link)}
hr{border:0;border-top:1px solid var(--rule);margin:2.5rem 0}
img{display:block;max-width:100%;height:auto;margin:1.4rem auto;border-radius:8px}
blockquote{margin:1.4rem 0;padding:.2rem 1.1rem;border-left:4px solid var(--p2);background:var(--code);border-radius:0 8px 8px 0}
blockquote:first-of-type{border-left-color:var(--p1)}
code{background:var(--code);padding:.1em .3em;border-radius:4px;font-size:.88em}
pre{background:var(--code);padding:1rem;border-radius:8px;overflow-x:auto;font-size:.8rem;line-height:1.45}
pre code{background:none;padding:0}
table{border-collapse:collapse;width:100%;font-size:.88rem;margin:1rem 0;font-variant-numeric:tabular-nums}
th,td{text-align:left;padding:.35rem .5rem;border-bottom:1px solid var(--rule)}
em{color:var(--muted)}
p>em:only-child{display:block;text-align:center;font-size:.9rem;margin-top:-.8rem}
"""


def main() -> None:
    src = (HERE / "melee-bench.md").read_text()
    meta = {}
    if m := re.match(r"---\n(.*?)\n---\n", src, re.S):
        meta = dict(re.findall(r'^(\w+):\s*"?([^"\n]*)"?$', m[1], re.M))
        src = src[m.end():]
    src = re.sub(r"<!--.*?-->\n?", "", src, flags=re.S)
    body = MarkdownIt("commonmark", {"html": False}).enable("table").render(src)
    body = re.sub(r'<a href="(https?://[^"]+)"', r'<a href="\1" target="_blank" rel="noopener"', body)
    title = meta.get("title", "Melee Bot Elo")
    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title>
<meta name="description" content="LLMs, learned bots and Melee's CPUs on one Elo scale, in real-time Super Smash Bros. Melee.">
<style>{CSS}</style></head>
<body><main><h1>{html.escape(title)}</h1><div class="meta">Mateo Amado · {html.escape(meta.get("date", ""))}</div>
{body}</main></body></html>
"""
    (HERE / "index.html").write_text(page)
    print("wrote writeup/index.html")


if __name__ == "__main__":
    main()
