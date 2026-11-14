"""Small helpers every track used to carry its own copy of: jsonl files, atomic writes, ports, child games."""
from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
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


def exit_on_term(*extra: int) -> None:
    """Turn SIGTERM (a timeout, a cancelled job, a stopped unit) into SystemExit so play() stops its Dolphin."""
    for sig in (signal.SIGTERM, *extra):
        signal.signal(sig, lambda *_: sys.exit(143))


def run_game_process(cmd: list[str], timeout: float, env: dict | None = None, grace: float = 30) -> tuple[dict | None, str, str, bool]:
    """Run one game as a child in its own process group, so a timeout kills its Dolphin and bots with it.

    Returns (result, stdout, stderr, timed_out): `result` is the last JSON line the child printed, None if it
    printed none or was killed.
    """
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
