"""Let several Dolphins run at once: each process claims its own Slippi spectator port.

libmelee already gives every Console a temporary home (tmp_home_directory=True), so controller
pipes and configs never clash; the only shared resource is the Slippi UDP port (default 51441).
runner.play() does not take a port yet, so `claim_slippi_port` rebinds melee.Console's default in
this process. Remove the patch once play() accepts slippi_port.
"""
from __future__ import annotations

import fcntl
import functools
import os
import socket
from pathlib import Path

import melee

LOCK_DIR = Path("/tmp/melee-llm-slippi-ports")
_held = []
_Console = melee.Console


def _udp_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def claim_slippi_port(start: int = 51441, count: int = 200) -> int:
    """Lock the first free port in [start, start+count) for this process's lifetime and make
    every melee.Console created here use it."""
    LOCK_DIR.mkdir(exist_ok=True)
    for port in range(start, start + count):
        f = open(LOCK_DIR / f"{port}.lock", "w")
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            f.close()
            continue
        if not _udp_free(port):
            f.close()
            continue
        f.write(str(os.getpid()))
        f.flush()
        _held.append(f)
        melee.Console = functools.partial(_Console, slippi_port=port)
        return port
    raise RuntimeError(f"no free Slippi port in {start}..{start + count - 1}")


def find_iso(cli_value: str | None) -> str:
    iso = cli_value or os.environ.get("MELEE_ISO")
    if not iso or not Path(iso).is_file():
        raise SystemExit("No Melee ISO configured (set MELEE_ISO or pass --iso). "
                         "Without it you can still run check-bot, which replays recorded games through your bot.")
    return iso
