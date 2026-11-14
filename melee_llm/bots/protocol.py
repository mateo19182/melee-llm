"""Wire format between a BotAgent and its model subprocess. Stdlib only: both sides import it.

Frames are a 4-byte big-endian length plus a pickle. Both ends are our own trusted code.

Parent -> child:
  {"op": "init", "port", "opponent_port", "character": str, "config": dict, "steer": dict}
  {"op": "step", "events": [(type, bytes), ...], "steer": dict | None, "open_loop": bool}
  {"op": "close"}
Child -> parent:
  init reply: {"ok": True, "info": dict} or {"ok": False, "error": str}
  step reply: {"ctrl": CTRL | None, "frame": int | None, "ms": float, "steer": dict | None, "error": str | None}

`events` are the raw Slippi messages the parent's Console consumed since the last step
(type "game_event" or "frame_end"); the child replays them through its own libmelee build, so each
bot sees a GameState from the exact parser it was trained/deployed with.

CTRL is a full controller state in libmelee convention: sticks in [0, 1] (0.5 = neutral), analog
shoulders in [0, 1], `buttons` the names of pressed melee.Button members.
"""
from __future__ import annotations

import pickle
import struct

_LEN = struct.Struct(">I")


def send(f, obj) -> None:
    data = pickle.dumps(obj, protocol=5)
    f.write(_LEN.pack(len(data)) + data)
    f.flush()


def _read_exact(f, n: int) -> bytes:
    chunks, left = [], n
    while left:
        chunk = f.read(left)
        if not chunk:
            raise EOFError("bot pipe closed")
        chunks.append(chunk)
        left -= len(chunk)
    return b"".join(chunks)


def recv(f):
    (n,) = _LEN.unpack(_read_exact(f, 4))
    return pickle.loads(_read_exact(f, n))
