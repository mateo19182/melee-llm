"""BotAgent: runs a submitted single-file bot in a child process behind a per-frame time budget.

Each frame the parent sends a sanitized GameState and waits up to `budget_ms` for the bot's
controller state. A late answer is a violation: the controller keeps its previous inputs, the
bot is not sent new frames until it catches up, and the stale answer is dropped. A crashed bot
releases all buttons for the rest of the match. Opponent inputs and identity are hidden.
"""
from __future__ import annotations

import copy
import json
import os
import pickle
import resource
import select
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

import melee
from melee.controller import fix_analog_trigger

from melee_llm.agents.base import Agent
from melee_llm.botwriter.host import BUTTONS, write_frame
from melee_llm.paths import ROOT

_NEUTRAL = melee.ControllerState()
_BY_NAME = {b.name: b for b in BUTTONS}
_FORBIDDEN_BUTTONS = {melee.Button.BUTTON_START}  # START pauses the match


@dataclass
class FrameStats:
    frames: int = 0
    answered: int = 0
    late: int = 0  # answer did not arrive within budget
    skipped: int = 0  # bot still busy with an older frame
    exceptions: int = 0
    policy_violations: int = 0
    crashed: bool = False
    step_ms: list[float] = field(default_factory=list)

    def summary(self) -> dict:
        ms = sorted(self.step_ms)
        pct = lambda q: round(ms[min(len(ms) - 1, int(q * len(ms)))], 3) if ms else None
        return {"frames": self.frames, "answered": self.answered, "late": self.late, "skipped": self.skipped,
                "exceptions": self.exceptions, "policy_violations": self.policy_violations, "crashed": self.crashed,
                "ms_mean": round(statistics.fmean(ms), 3) if ms else None, "ms_p99": pct(0.99), "ms_max": pct(1.0)}


def sanitize(gs: melee.GameState, opp: int) -> melee.GameState:
    """Shallow copy of gs with the opponent's controller inputs and identity removed."""
    g = copy.copy(gs)
    g.players = dict(gs.players)
    o = g.players.get(opp)
    if o is not None:
        o = copy.copy(o)
        o.controller_state = _NEUTRAL
        o.cpu_level, o.displayName, o.connectCode, o.nickName = 0, "", "", ""
        if getattr(o, "nana", None) is not None:
            o.nana = copy.copy(o.nana)
            o.nana.controller_state = _NEUTRAL
        g.players[opp] = o
    return g


def _limits():
    resource.setrlimit(resource.RLIMIT_AS, (4 << 30, 4 << 30))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    os.setsid()


class BotAgent(Agent):
    def __init__(self, bot_file: str | Path, budget_ms: float | None = 16.0, startup_s: float = 20.0,
                 log_path: str | Path | None = None, label: str | None = None):
        super().__init__()
        self.bot_file = str(Path(bot_file).resolve())
        self.budget_ms, self.label = budget_ms, label
        self.scratch = tempfile.mkdtemp(prefix="botwriter_")
        self.log_path = Path(log_path) if log_path else Path(self.scratch + ".log")
        self._log = open(self.log_path, "ab")
        env = {"PATH": "/usr/bin:/bin", "HOME": self.scratch, "PYTHONDONTWRITEBYTECODE": "1",
               "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1", "LANG": "C.UTF-8"}
        boot = f"import sys; sys.path.insert(0, {str(ROOT)!r}); from melee_llm.botwriter.host import main; main()"
        self.proc = subprocess.Popen([sys.executable, "-I", "-B", "-c", boot, self.bot_file, self.scratch],
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self._log,
                                     env=env, cwd=self.scratch, preexec_fn=_limits)
        self._buf = b""
        self.seq, self.pending, self.dead = 0, None, False
        self.stats, self.game_stats = FrameStats(), []
        self.applied = None  # None: real controller state unknown, next apply writes everything
        msg = self._recv(startup_s)
        if msg is None or msg.get("type") != "ready":
            err = (msg or {}).get("error") or "no answer within startup time"
            self.close()
            raise RuntimeError(f"bot {bot_file} failed to load:\n{err}")
        self.character = melee.Character[msg["character"]]
        self.bot_name = msg.get("name") or Path(bot_file).stem

    @property
    def name(self) -> str:
        return self.label or self.bot_name

    # --- protocol -------------------------------------------------------------------------
    def _send(self, obj) -> bool:
        try:
            write_frame(self.proc.stdin, pickle.dumps(obj, protocol=pickle.HIGHEST_PROTOCOL))
            return True
        except (BrokenPipeError, OSError):
            self._die("pipe closed")
            return False

    def _recv(self, timeout_s: float) -> dict | None:
        """Next JSON message from the child, or None on timeout/death."""
        deadline = time.perf_counter() + timeout_s
        fd = self.proc.stdout.fileno()
        while True:
            if len(self._buf) >= 4:
                n = int.from_bytes(self._buf[:4], "big")
                if n > 1 << 20:
                    self._die("oversized message")
                    return None
                if len(self._buf) >= 4 + n:
                    raw, self._buf = self._buf[4:4 + n], self._buf[4 + n:]
                    try:
                        return json.loads(raw)
                    except ValueError:
                        self._die("malformed message")
                        return None
            if not select.select([fd], [], [], max(0.0, deadline - time.perf_counter()))[0]:
                return None
            chunk = os.read(fd, 1 << 16)
            if not chunk:
                self._die(f"exited with code {self.proc.poll()}")
                return None
            self._buf += chunk

    def _die(self, why: str) -> None:
        if self.dead:
            return
        self.dead, self.stats.crashed = True, True
        self._log.write(f"\n[botwriter] bot stopped: {why}\n".encode())
        self._log.flush()
        if hasattr(self, "controller"):
            try:
                self.controller.release_all()
            except Exception:
                pass

    # --- Agent contract -------------------------------------------------------------------
    def setup(self, controller, port, opponent_port):
        super().setup(controller, port, opponent_port)
        self._send(("setup", port, opponent_port))

    def step(self, gs):
        self.stats.frames += 1
        if self.dead:
            return
        t0 = time.perf_counter()
        if self.pending is not None:
            msg = self._recv(0)
            if msg is None:
                self.stats.skipped += 1
                return
            self._account(msg)  # stale answer: counted, not applied
            self.pending = None
        self.seq += 1
        if not self._send(("step", self.seq, sanitize(gs, self.opponent_port))):
            return
        budget = None if self.budget_ms is None else self.budget_ms / 1000
        msg = self._recv(3600 if budget is None else max(0.0, budget - (time.perf_counter() - t0)))
        if msg is None:
            if not self.dead:
                self.stats.late += 1
                self.pending = self.seq
            return
        self._account(msg)
        self.stats.answered += 1
        self.stats.step_ms.append((time.perf_counter() - t0) * 1000)
        if msg.get("type") == "act":
            self._apply(msg["state"])

    def _account(self, msg: dict) -> None:
        if msg.get("err"):
            self.stats.exceptions += 1
        self.stats.policy_violations = max(self.stats.policy_violations, int(msg.get("viol", 0)))

    def _apply(self, s: dict) -> None:
        """Write only what changed, so the real controller ends in exactly the bot's state."""
        c, cur = self.controller, self.applied
        try:
            want = {_BY_NAME[b] for b in s["buttons"] if b in _BY_NAME} - _FORBIDDEN_BUTTONS
            sticks = {k: tuple(min(1.0, max(0.0, float(v))) for v in s[k][:2]) for k in ("main", "c")}
            shoulders = {k: min(1.0, max(0.0, float(s[k]))) for k in ("l", "r")}
        except (KeyError, TypeError, ValueError):
            self.stats.exceptions += 1
            return
        out = []
        if cur is None:  # real state unknown: assume the opposite of everything, so all of it is written
            cur = {"buttons": set(BUTTONS) - want, "main": None, "c": None, "l": None, "r": None}
        for b in want - cur["buttons"]:
            out.append(f"PRESS {b.value}\n")
            c.current.button[b] = True
        for b in cur["buttons"] - want:
            out.append(f"RELEASE {b.value}\n")
            c.current.button[b] = False
        for k, btn in (("main", melee.Button.BUTTON_MAIN), ("c", melee.Button.BUTTON_C)):
            if sticks[k] != cur[k]:
                out.append(f"SET {btn.value} {sticks[k][0]} {sticks[k][1]}\n")
                setattr(c.current, "main_stick" if k == "main" else "c_stick", sticks[k])
        for k, btn in (("l", melee.Button.BUTTON_L), ("r", melee.Button.BUTTON_R)):
            if shoulders[k] != cur[k]:
                out.append(f"SET {btn.value} {fix_analog_trigger(shoulders[k])}\n")  # libmelee stores triggers unfixed
                setattr(c.current, f"{k}_shoulder", shoulders[k])
        if out:
            c._write("".join(out))
        self.applied = {"buttons": want, **sticks, **shoulders}

    def on_game_end(self, gs):
        self.game_stats.append(self.stats.summary())
        self.stats = FrameStats(crashed=self.dead)
        if not self.dead:
            self._send(("end", gs))
            self.applied = None  # menus drive the controller between games
            if self.pending is not None and self._recv(5.0) is None and not self.dead:
                self._die("still busy 5 s after the game ended")
            self.pending = None

    def close(self):
        if self.proc.poll() is None:
            try:
                write_frame(self.proc.stdin, pickle.dumps(("close",)))
                self.proc.wait(timeout=2)
            except Exception:
                pass
        if self.proc.poll() is None:
            try:
                os.killpg(self.proc.pid, 9)
            except ProcessLookupError:
                pass
            self.proc.wait()
        self._log.close()
        shutil.rmtree(self.scratch, ignore_errors=True)
