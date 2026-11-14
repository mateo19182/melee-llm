"""Minimal .slp reader for the game list: characters, stage, player types and length, from a few KB of the file."""
from __future__ import annotations

import re
import struct
from pathlib import Path

# Slippi Game Start uses external character ids and in-game stage ids; names follow libmelee's enums.
EXTERNAL_CHARS = ["CPTFALCON", "DK", "FOX", "GAMEANDWATCH", "KIRBY", "BOWSER", "LINK", "LUIGI", "MARIO", "MARTH",
                  "MEWTWO", "NESS", "PEACH", "PIKACHU", "POPO", "JIGGLYPUFF", "SAMUS", "YOSHI", "ZELDA", "SHEIK",
                  "FALCO", "YLINK", "DOC", "ROY", "PICHU", "GANONDORF"]
STAGES = {2: "FOUNTAIN_OF_DREAMS", 3: "POKEMON_STADIUM", 8: "YOSHIS_STORY", 28: "DREAMLAND", 31: "BATTLEFIELD",
          32: "FINAL_DESTINATION"}
PLAYER_TYPES = {0: "human", 1: "cpu", 2: "demo"}


def header(path: Path) -> dict | None:
    """{"stage", "players": {port: {"character", "type"}}, "last_frame", "start_at"} or None if unreadable."""
    try:
        with path.open("rb") as f:
            head = f.read(4096)
            size = path.stat().st_size
            f.seek(max(0, size - 2048))
            tail = f.read()
    except OSError:
        return None
    i = head.find(b"raw[$U#l")
    if i < 0:
        return None
    raw = i + 12
    if head[raw:raw + 1] != b"\x35":
        return None
    payload_size = head[raw + 1]
    sizes = {head[raw + 2 + k]: struct.unpack(">H", head[raw + 3 + k:raw + 5 + k])[0]
             for k in range(0, payload_size - 1, 3)}
    gs = raw + 1 + payload_size
    if head[gs:gs + 1] != b"\x36" or 0x36 not in sizes or gs + 0x65 + 4 * 0x24 > len(head):
        return None
    stage = struct.unpack(">H", head[gs + 0x13:gs + 0x15])[0]
    players = {}
    for p in range(4):
        char, ptype = head[gs + 0x65 + 0x24 * p], head[gs + 0x66 + 0x24 * p]
        if ptype in PLAYER_TYPES and char < len(EXTERNAL_CHARS):
            players[p + 1] = {"character": EXTERNAL_CHARS[char], "type": PLAYER_TYPES[ptype]}
    out = {"stage": STAGES.get(stage, f"STAGE_{stage}"), "players": players, "last_frame": None, "start_at": None}
    if m := re.search(rb"U\x09lastFramel(.{4})", tail, re.S):
        out["last_frame"] = struct.unpack(">i", m.group(1))[0]
    if m := re.search(rb"U\x07startAtSU(.)", tail, re.S):
        j = m.end()
        out["start_at"] = tail[j:j + m.group(1)[0]].decode(errors="replace")
    return out
