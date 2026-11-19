"""Render writeup/melee-bench.md as writeup/index.html, dressed like the rest of the site.

    uv run python writeup/build_page.py

The page takes its look from the site's stylesheet and its top bar from the site's index.html, so it follows
both. Figures and media stay relative, and the stylesheet is linked twice (served path, repo path) so the page
also works opened from a checkout with no server.
"""
from __future__ import annotations

import html
import re
from pathlib import Path

from markdown_it import MarkdownIt

HERE = Path(__file__).resolve().parent
STATIC = HERE.parent / "melee_llm" / "web" / "static"

URL = "https://melee.m19182.dev/writeup/"
DESCRIPTION = "Melee bots are getting really good: ten years of them, how the best ones work, and one Elo scale for CPUs, learned bots and LLMs."
# Only what an article needs on top of style.css: a reading column and plain prose elements.
CSS = """
.frame{max-width:920px}
.post{max-width:44rem;margin:0 auto;font-size:17px;line-height:1.62}
.post .sub{font:italic 800 21px/1.25 var(--menu);font-variation-settings:"wdth" 108;color:var(--title);margin:-.2em 0 .7em}
.post .meta{color:var(--dim);font-size:14px;margin:-4px 0 26px}
.post h1{font-size:38px;margin-bottom:.35em}
.post h2{font-size:25px;margin:2.1em 0 .6em}
.post h3{font:italic 800 18px/1.2 var(--menu);font-variation-settings:"wdth" 108;text-transform:none;letter-spacing:0;color:var(--gold);text-shadow:var(--outline);margin:1.9em 0 .5em}
.post p,.post ul,.post ol{margin:0 0 1em}
.post li{margin:.3em 0}
.post li::marker{color:var(--gold)}
.post a{text-decoration:underline;text-decoration-color:rgba(102,224,255,.35);text-underline-offset:2px}
.post hr{border:0;height:2px;margin:2.4em 0;background:linear-gradient(90deg,transparent,var(--f-mid),transparent)}
.post img{display:block;max-width:100%;height:auto;margin:1.4em auto .6em;border:1px solid var(--line-hi);border-radius:8px}
.post blockquote{margin:1.3em 0;padding:12px 18px 2px;background:#030303;border:2px solid #c9ccd2;border-radius:7px;box-shadow:inset 0 0 0 1px #000,0 0 0 1px #000}
.post code{background:rgba(102,224,255,.1);color:#c9f4ff;padding:.05em .35em;border-radius:3px;font-size:.82em}
.post pre{background:rgba(3,4,18,.8);border:1px solid var(--line-hi);border-radius:6px;padding:12px 14px;margin:0 0 1em;overflow-x:auto;white-space:pre;font-size:12px;line-height:1.5}
.post pre code{background:none;color:var(--text);padding:0;font-size:inherit}
.post table{border-collapse:collapse;width:100%;font-size:14.5px;margin:0 0 1em}
.post th,.post td{text-align:left;padding:6px 10px;border-bottom:1px solid var(--line)}
.post th{font:700 12px var(--menu);font-variation-settings:"wdth" 85;text-transform:uppercase;letter-spacing:.08em;color:var(--dim)}
.post em{color:var(--dim)}
.post p>em:only-child{display:block;text-align:center;font-size:14px}
@media (max-width:700px){.frame{width:calc(100% - 30px);padding-left:16px;padding-right:16px}.post{font-size:16px}.post h1{font-size:30px}}
"""


def topbar() -> str:
    """The site's top bar, as plain links, with this page selected."""
    shell = (STATIC / "index.html").read_text()
    bar = re.search(r'<header class="topbar">.*?</header>', shell, re.S)[0]
    bar = re.sub(r'\s*<a id="onair".*?</a>', "", bar)  # filled by the app's script, which this page doesn't load
    bar = bar.replace(" data-link", "")
    return bar.replace('<a href="/writeup/"', '<a class="active" href="/writeup/"')


def main() -> None:
    src = (HERE / "melee-bench.md").read_text()
    meta = {}
    if m := re.match(r"---\n(.*?)\n---\n", src, re.S):
        meta = dict(re.findall(r'^(\w+):\s*"?([^"\n]*)"?$', m[1], re.M))
        src = src[m.end():]
    src = re.sub(r"<!--.*?-->\n?", "", src, flags=re.S)
    body = MarkdownIt("commonmark", {"html": False}).enable("table").render(src)
    body = re.sub(r'<a href="(https?://[^"]+)"', r'<a href="\1" target="_blank" rel="noopener"', body)
    title = meta.get("title", "Melee bots are getting really good")
    sub = f'<div class="sub">{html.escape(meta["subtitle"])}</div>' if meta.get("subtitle") else ""
    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title>
<meta name="description" content="{DESCRIPTION}">
<meta name="author" content="Mateo Amado Ares">
<link rel="canonical" href="{URL}">
<meta property="og:type" content="article">
<meta property="og:site_name" content="Melee × LLM">
<meta property="og:title" content="{html.escape(title)}">
<meta property="og:description" content="{DESCRIPTION}">
<meta property="og:url" content="{URL}">
<meta property="og:image" content="{URL}media/site-bench.webp">
<meta name="twitter:card" content="summary_large_image">
<meta name="theme-color" content="#070926">
<link rel="icon" href="/static/img/smash-emblem.svg" type="image/svg+xml">
<link rel="stylesheet" href="/static/style.css">
<link rel="stylesheet" href="../melee_llm/web/static/style.css">
<style>{CSS}</style></head>
<body>
{topbar()}
<div class="frame">
<span class="frame-stripes" aria-hidden="true"></span>
<div class="frame-title" aria-hidden="true">Write-up</div>
<main><article class="post"><h1>{html.escape(title)}</h1>{sub}<div class="meta"><a href="https://blog.m19182.dev/">Mateo Amado</a> · {html.escape(meta.get("date", ""))}</div>
{body}</article></main>
</div>
</body></html>
"""
    (HERE / "index.html").write_text(page)
    print("wrote writeup/index.html")


if __name__ == "__main__":
    main()
