"""Small helpers every track used to carry its own copy of: jsonl files, atomic writes, ports, child games."""
from __future__ import annotations

import fcntl
import json
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

from melee_llm.paths import ROOT


def read_jsonl(path: Path) -> list[dict]:
    """Every parseable line; a missing file is empty and a line cut by a crash or still being written is skipped."""
    out = []
    try:
        with open(path) as f:
            for line in f:
                try:
                    out.append(json.loads(line))
                except ValueError:
                    pass
    except OSError:
        pass
    return out


def append_jsonl(path: Path, rec: dict) -> None:
    with open(path, "a") as f:
        f.write(json.dumps(rec, default=float) + "\n")


def write_atomic(path: Path, text: str) -> None:
    """Readers (the web server, ffmpeg's drawtext) never see a half-written file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(text)
    tmp.replace(path)


def port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


SLOTS = Path("/tmp/melee-llm-slots")


def unthrottled_games() -> int:
    """How many unthrottled games the machine runs at once, over every track ($MELEE_UNTHROTTLED_GAMES).

    Each one keeps a Dolphin flat out on about two cores. Past a quarter of the hardware threads the total
    frames per second stop growing, and past half they fall (docs/performance.md)."""
    return int(os.environ.get("MELEE_UNTHROTTLED_GAMES") or max(1, (os.cpu_count() or 4) // 4))


def claim_slot(wait: bool = True):
    """Take one of the machine's slots for an unthrottled game: fast mode with no player the game waits for.

    Returns an open lock file: close it to give the slot back (the kernel does when the process dies). With
    `wait=False`, None when every slot is taken."""
    SLOTS.mkdir(exist_ok=True)
    while True:
        for i in range(unthrottled_games()):
            f = open(SLOTS / f"{i}.lock", "w")
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return f
            except BlockingIOError:
                f.close()
        if not wait:
            return None
        time.sleep(1)


def exit_on_term(*extra: int) -> None:
    """Turn SIGTERM (a timeout, a cancelled job, a stopped unit) into SystemExit so play() stops its Dolphin."""
    for sig in (signal.SIGTERM, *extra):
        signal.signal(sig, lambda *_: sys.exit(143))


def run_game_process(cmd: list[str], timeout: float, env: dict | None = None, grace: float = 30,
                     unthrottled: bool = False) -> tuple[dict | None, str, str, bool]:
    """Run one game as a child in its own process group, so a timeout kills its Dolphin and bots with it.

    Returns (result, stdout, stderr, timed_out): `result` is the last JSON line the child printed, None if it
    printed none or was killed. An `unthrottled` game first waits for a machine slot (claim_slot); the wait
    does not count towards `timeout`.
    """
    if unthrottled:
        with claim_slot():
            return run_game_process(cmd, timeout, env, grace)
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env, cwd=ROOT,
                         start_new_session=True)
    try:
        stdout, stderr = p.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(p.pid, signal.SIGTERM)
        try:
            _, stderr = p.communicate(timeout=grace)
        except subprocess.TimeoutExpired:
            os.killpg(p.pid, signal.SIGKILL)
            _, stderr = p.communicate()
        return None, "", stderr, True
    line = next((ln for ln in reversed(stdout.splitlines()) if ln.startswith("{")), None)
    return (json.loads(line) if line else None), stdout, stderr, False
