"""Render docs/*.md for the Docs page: HTML with heading anchors, a table of contents, repo links rewritten, and search."""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from markdown_it import MarkdownIt

from melee_llm.paths import ROOT

DOCS = ROOT / "docs"
# Nav order; any other docs/*.md follows alphabetically.
ORDER = ["research", "bots", "llm-player", "bot-writer", "coach", "llm-arena", "jev", "netplay"]
_md = MarkdownIt("commonmark", {"html": False}).enable("table")


def _slug(text: str, seen: set[str]) -> str:
    base = re.sub(r"[^\w\s-]", "", text.lower()).strip()
    base = re.sub(r"[\s_]+", "-", base) or "section"
    slug, n = base, 2
    while slug in seen:
        slug, n = f"{base}-{n}", n + 1
    seen.add(slug)
    return slug


def _plain(text: str) -> str:
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)  # links → their text
    return re.sub(r"[*`]", "", text)


def _path(name: str) -> Path | None:
    path = DOCS / f"{name}.md"
    return path if re.fullmatch(r"[\w-]+", name) and path.is_file() else None


@lru_cache(maxsize=64)
def _parse(name: str, mtime: float) -> dict:
    """Tokens with heading ids and rewritten links, plus title, TOC and searchable sections. Keyed on mtime."""
    tokens = _md.parse((DOCS / f"{name}.md").read_text())
    toc, seen, title = [], set(), name
    sections = [{"id": None, "heading": "", "text": []}]
    for i, tok in enumerate(tokens):
        if tok.type == "heading_open":
            text = _plain(tokens[i + 1].content)
            if tok.tag == "h1":
                title = text
                continue
            tok.attrSet("id", _slug(text, seen))
            sections.append({"id": tok.attrGet("id"), "heading": text, "text": []})
            if tok.tag in ("h2", "h3"):
                toc.append({"level": int(tok.tag[1]), "id": tok.attrGet("id"), "text": text})
        elif tok.type == "inline":
            if tokens[i - 1].type != "heading_open":
                sections[-1]["text"].append(_plain(tok.content))
            for child in tok.children or []:
                if child.type != "link_open":
                    continue
                href = child.attrGet("href") or ""
                if m := re.fullmatch(r"([\w-]+)\.md(#[\w-]+)?", href):
                    child.attrSet("href", f"/docs/{m[1]}{m[2] or ''}")
                    child.attrSet("data-link", "")
                elif href.startswith(("http://", "https://")):
                    child.attrSet("target", "_blank")
                    child.attrSet("rel", "noopener")
    html = _md.renderer.render(tokens, _md.options, {})
    return {"title": title, "html": html, "toc": toc, "sections": sections}


def listing() -> list[dict]:
    names = sorted(p.stem for p in DOCS.glob("*.md"))
    names.sort(key=lambda n: ORDER.index(n) if n in ORDER else len(ORDER))
    return [{"name": n, "title": _parse(n, (DOCS / f"{n}.md").stat().st_mtime)["title"]} for n in names]


def render(name: str) -> dict | None:
    if not (path := _path(name)):
        return None
    mtime = path.stat().st_mtime
    d = _parse(name, mtime)
    return {"name": name, "title": d["title"], "html": d["html"], "toc": d["toc"], "updated": mtime}


def search(q: str, limit: int = 40) -> list[dict]:
    """Case-insensitive match of every word in q; one hit per (doc, section), ranked by heading matches first."""
    words = [w for w in q.lower().split() if w]
    if not words or len(q) > 200:
        return []
    hits = []
    for d in listing():
        doc = _parse(d["name"], (DOCS / f"{d['name']}.md").stat().st_mtime)
        for sec in doc["sections"]:
            body = " ".join(sec["text"])
            hay = f"{sec['heading']} {body}".lower()
            if not all(w in hay for w in words):
                continue
            pos = body.lower().find(words[0])
            start = max(0, pos - 60) if pos >= 0 else 0
            snippet = ("…" if start else "") + body[start:start + 180].strip() + ("…" if start + 180 < len(body) else "")
            in_heading = sum(w in sec["heading"].lower() for w in words)
            hits.append({"doc": d["name"], "doc_title": d["title"], "id": sec["id"], "heading": sec["heading"] or d["title"],
                         "snippet": snippet, "score": in_heading * 10 + hay.count(words[0])})
    hits.sort(key=lambda x: -x["score"])
    return hits[:limit]
