"""Process-level API for one netplay session at a time (the bot account can only be in one lobby).

    from melee_llm.netplay import start, status, stop
    start(opponent="hal:MASTER", connect_code="ABCD#123", char="FOX", games=3)
    status()  # {"running": True, "phase": "waiting", ...}
    stop()    # after the current game; stop(force=True) kills at once

The session runs as `python -m melee_llm.netplay host ...` in its own process group, so the caller (CLI or
web UI) never loads Dolphin or a bot. It writes its state to replays/netplay/status.json on every change.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from dataclasses import asdict, fields
from pathlib import Path

from melee_llm.netplay.host import DISPLAY, OUT, HostConfig, check
from melee_llm.runner import ROOT

STATUS = OUT / "status.json"
LOG = OUT / "session.log"
VNC_PORT, NOVNC_PORT, BIND = 5998, 6081, "100.83.166.6"  # :99's live.sh uses 5900/6080


def write_status(st: dict) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    st = {**st, "pid": os.getpid(), "updated": time.time()}
    tmp = STATUS.with_suffix(".tmp")
    tmp.write_text(json.dumps(st, default=str))
    tmp.replace(STATUS)


def _alive(pid: int) -> bool:
    try:
        return b"melee_llm.netplay" in Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        return False


def status() -> dict:
    """Last reported state plus `running`. Phases: starting, booting, loading bot, waiting, playing,
    stopping, done, failed."""
    try:
        st = json.loads(STATUS.read_text())
    except (OSError, ValueError):
        return {"running": False, "phase": None}
    st["running"] = bool(st.get("pid")) and _alive(st["pid"])
    if not st["running"] and st.get("phase") not in ("done", "failed"):
        st["phase"] = "dead"
    return st


def start(**kw) -> dict:
    """Start a session in the background. Keys are HostConfig fields. Raises if one is running or the
    preflight check fails; returns the first status."""
    if status()["running"]:
        raise RuntimeError("a netplay session is already running; stop() it first")
    cfg = HostConfig(**kw)
    problems = check(cfg)
    if problems:
        raise RuntimeError("; ".join(problems))
    args = [sys.executable, "-m", "melee_llm.netplay", "host"]
    for f in fields(HostConfig):
        args += [f"--{f.name.replace('_', '-')}", str(getattr(cfg, f.name))]
    OUT.mkdir(parents=True, exist_ok=True)
    write_status({"phase": "starting", "config": asdict(cfg), "error": None})
    with open(LOG, "ab") as log:
        proc = subprocess.Popen(args, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                start_new_session=True)
    st = json.loads(STATUS.read_text())
    st["pid"] = proc.pid
    STATUS.write_text(json.dumps(st))
    return status()


def stop(force: bool = False) -> dict:
    """Ask the session to end after the current game (at once while it waits in menus). `force` kills
    the whole process group, Dolphin and bots included."""
    st = status()
    if st["running"]:
        if force:
            os.killpg(st["pid"], signal.SIGKILL)
        else:
            os.kill(st["pid"], signal.SIGTERM)
    return st


def screenshot(path: str | Path | None = None, display: str = DISPLAY) -> Path:
    """PNG of the whole hidden display."""
    path = Path(path or OUT / f"screen-{time.strftime('%Y%m%d-%H%M%S')}.png")
    path.parent.mkdir(parents=True, exist_ok=True)
    size = subprocess.run(["xdpyinfo", "-display", display], capture_output=True, text=True).stdout
    dims = next((ln.split()[1] for ln in size.splitlines() if "dimensions:" in ln), "640x480")
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "x11grab", "-video_size", dims, "-i", display,
                    "-frames:v", "1", str(path)], check=True)
    return path


def view(display: str = DISPLAY) -> str:
    """Start an interactive noVNC view of the hidden display, bound to the Tailscale IP. Idempotent."""
    if subprocess.run(["pgrep", "-f", f"[x]11vnc -display {display} -rfbport {VNC_PORT}"],
                      capture_output=True).returncode:
        subprocess.run(["x11vnc", "-display", display, "-rfbport", str(VNC_PORT), "-localhost", "-forever",
                        "-shared", "-nopw", "-quiet", "-bg", "-o", "/tmp/melee-netplay-x11vnc.log"], check=True)
    if subprocess.run(["pgrep", "-f", f"[w]ebsockify.*{NOVNC_PORT}"], capture_output=True).returncode:
        subprocess.Popen([str(ROOT / ".venv/bin/websockify"), "--web", str(ROOT / "vendor/noVNC"),
                          f"{BIND}:{NOVNC_PORT}", f"localhost:{VNC_PORT}"], cwd=ROOT, start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=open("/tmp/melee-netplay-novnc.log", "ab"))
    return f"http://m19182:{NOVNC_PORT}/vnc.html?autoconnect=1&resize=scale"
