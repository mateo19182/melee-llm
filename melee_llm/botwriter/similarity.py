"""Near-copy check of a bot against public SmashBot (altf4/SmashBot), whose logic bots may not port.

  python -m melee_llm.botwriter.similarity BOT.py [--corpus vendor/SmashBot]

Both sides are tokenized (comments and layout dropped, string and number literals blanked) and cut
into 12-token shingles. `overlap` is the share of the bot's shingles that also occur in SmashBot;
`overlap_renamed` does the same with local identifiers renamed, so it also catches copies with
renamed variables. libmelee calls (`melee.Action.X`, `controller.press_button(...)`) are shared by
every bot, so the score is never 0; compare against the baselines (`--calibrate`).
"""
from __future__ import annotations

import argparse
import io
import json
import keyword
import tokenize
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "vendor" / "SmashBot"
N = 12
FLAG_AT = 0.25  # renamed overlap above this is worth a manual look


def _tokens(src: str, rename: bool) -> list[str]:
    out, prev = [], None
    skip = {tokenize.COMMENT, tokenize.NL, tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT, tokenize.ENCODING,
            tokenize.ENDMARKER}
    try:
        toks = list(tokenize.generate_tokens(io.StringIO(src).readline))
    except (tokenize.TokenError, SyntaxError, IndentationError):
        return out
    for t in toks:
        if t.type in skip:
            continue
        if t.type == tokenize.STRING or t.type == tokenize.NUMBER:
            out.append("<lit>")
        elif t.type == tokenize.NAME and rename and not keyword.iskeyword(t.string) and prev != ".":
            out.append("<id>")  # attribute names after '.' (the libmelee API) are kept
        else:
            out.append(t.string)
        prev = t.string
    return out


def _shingles(tokens: list[str]) -> set[tuple[str, ...]]:
    return {tuple(tokens[i:i + N]) for i in range(len(tokens) - N + 1)}


def _corpus(corpus: Path, rename: bool) -> set:
    s = set()
    for f in sorted(corpus.rglob("*.py")):
        s |= _shingles(_tokens(f.read_text(errors="replace"), rename))
    return s


def similarity(bot: Path, corpus: Path = CORPUS) -> dict:
    if not corpus.is_dir():
        return {"skipped": f"no corpus at {corpus} (git clone https://github.com/altf4/SmashBot {corpus})"}
    src = bot.read_text(errors="replace")
    out = {"corpus": str(corpus), "shingle_tokens": N}
    for key, rename in (("overlap", False), ("overlap_renamed", True)):
        mine = _shingles(_tokens(src, rename))
        out[key] = round(len(mine & _corpus(corpus, rename)) / max(1, len(mine)), 3)
    out["flagged"] = out["overlap_renamed"] > FLAG_AT
    return out


def main() -> None:
    ap = argparse.ArgumentParser(prog="similarity")
    ap.add_argument("bot", nargs="*")
    ap.add_argument("--corpus", default=str(CORPUS))
    ap.add_argument("--calibrate", action="store_true", help="also score the baselines and the starter bot")
    a = ap.parse_args()
    bots = [Path(b) for b in a.bot]
    if a.calibrate:
        here = Path(__file__).resolve().parent
        bots += sorted((here / "baselines").glob("*.py")) + [here / "template" / "bot.py"]
    for b in bots:
        print(json.dumps({"bot": str(b), **similarity(b, Path(a.corpus))}))


if __name__ == "__main__":
    main()
