"""Let several Dolphins run at once: each process claims its own Slippi spectator port.

libmelee gives every Console a temporary home (tmp_home_directory=True), so controller pipes and
configs never clash; the only shared resource is the Slippi UDP port. Callers pass the claimed
port to runner.play(slippi_port=...). The range defaults to 51500-51599 (51441 is the arena's,
51480-51499 belong to other experiments); override with MELEE_SLIPPI_PORTS=START-END.
"""
from __future__ import annotations

import fcntl
import os
import signal
import socket
import sys
from pathlib import Path

LOCK_DIR = Path("/tmp/melee-llm-slippi-ports")
_held: dict[int, object] = {}


def _udp_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def port_range() -> range:
    start, _, end = os.environ.get("MELEE_SLIPPI_PORTS", "51500-51599").partition("-")
    return range(int(start), int(end or start) + 1)


def claim_slippi_port() -> int:
    """Lock the first free port in port_range() for this process's lifetime (idempotent per process)."""
    if _held:
        return next(iter(_held))
    LOCK_DIR.mkdir(exist_ok=True)
    for port in port_range():
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
        _held[port] = f
        return port
    r = port_range()
    raise RuntimeError(f"all {len(r)} emulator slots ({r.start}-{r.stop - 1}) are busy: wait for other games to finish")


def exit_on_term() -> None:
    """Turn SIGTERM/SIGHUP (a tool timeout, a killed ladder) into SystemExit so play() stops its Dolphin."""
    for sig in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, lambda *_: sys.exit(143))


def find_iso(cli_value: str | None) -> str:
    iso = cli_value or os.environ.get("MELEE_ISO")
    if not iso or not Path(iso).is_file():
        raise SystemExit("No Melee ISO configured (set MELEE_ISO or pass --iso). "
                         "Without it you can still run check-bot, which replays recorded games through your bot.")
    return iso
