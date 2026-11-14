"""Child-process side of a submitted bot: loads the bot file, steps it, reports controller state.

Wire protocol: 4-byte big-endian length + payload. Parent -> child payloads are pickles (the parent
is trusted); child -> parent payloads are JSON, so a hostile bot cannot run code in the parent.
The bot's stdout is redirected to stderr (its log) so prints cannot corrupt the protocol.
"""
from __future__ import annotations

import copy
import copyreg
import importlib.util
import io
import json
import operator
import os
import pickle
import struct
import sys
import time
import traceback

import melee
import melee.controller
import melee.gamestate
import numpy as np

BUTTONS = [b for b in melee.Button if b not in (melee.Button.BUTTON_MAIN, melee.Button.BUTTON_C)]
_LEN = struct.Struct(">I")


class _Unset:
    """Marks a slot that was never assigned."""


def _slots(cls: type) -> tuple[str, ...]:
    return tuple(s for c in reversed(cls.__mro__) for s in vars(c).get("__slots__", ()))


def _rebuild(cls: type, values: tuple):
    o = object.__new__(cls)
    for k, v in zip(_SLOTTED[cls], values):
        if v is not _Unset:
            object.__setattr__(o, k, v)
    return o


def _reducer(cls: type, slots: tuple[str, ...]):
    get = operator.attrgetter(*slots) if len(slots) > 1 else lambda o: tuple(getattr(o, k) for k in slots)

    def reduce(o):
        try:
            values = get(o)
        except AttributeError:
            values = tuple(getattr(o, k, _Unset) for k in slots)
        return _rebuild, (cls, values)
    return reduce


# Default pickling costs ~110 us per frame for libmelee's GameState, because numpy scalars carry their dtype
# and slotted objects go through copyreg in Python. These reductions rebuild the same types and values in
# less than half the time.
_SLOTTED = {c: _slots(c) for m in (melee.gamestate, melee.controller) for c in vars(m).values()
            if isinstance(c, type) and c.__module__ == m.__name__ and "__slots__" in vars(c)}
_TABLE = copyreg.dispatch_table.copy()
_TABLE.update({t: (lambda x, t=t: (t, (float(x),))) for t in (np.float16, np.float32, np.float64)})
_TABLE.update({t: (lambda x, t=t: (t, (int(x),))) for t in
               (np.int8, np.uint8, np.int16, np.uint16, np.int32, np.uint32, np.int64, np.uint64)})
_TABLE[np.bool_] = lambda x: (np.bool_, (bool(x),))
_TABLE.update({c: _reducer(c, s) for c, s in _SLOTTED.items()})


def dumps(obj) -> bytes:
    f = io.BytesIO()
    p = pickle.Pickler(f, protocol=pickle.HIGHEST_PROTOCOL)
    p.dispatch_table = _TABLE
    p.dump(obj)
    return f.getvalue()


def write_frame(f, payload: bytes) -> None:
    f.write(_LEN.pack(len(payload)) + payload)
    f.flush()


def read_frame(f) -> bytes | None:
    head = f.read(4)
    if len(head) < 4:
        return None
    (n,) = _LEN.unpack(head)
    return f.read(n)


class FakeController(melee.Controller):
    """A Controller with libmelee's exact semantics (analog fixing, release_all...) but no pipe."""

    def __init__(self, port: int = 1):
        self.port, self.pipe, self.pipe_path, self.logger = port, None, "", None
        self.prev, self.current = melee.ControllerState(), melee.ControllerState()
        self._fix_analog_inputs, self._console, self._type = True, None, melee.ControllerType.STANDARD

    def connect(self):
        return True

    def disconnect(self):
        pass

    def _check_pipe(self):
        pass

    def _write(self, command):
        pass

    def flush(self):
        self.prev = copy.copy(self.current)


def controller_state(c: melee.ControllerState) -> dict:
    return {
        "buttons": [b.name for b in BUTTONS if c.button.get(b)],
        "main": [float(c.main_stick[0]), float(c.main_stick[1])],
        "c": [float(c.c_stick[0]), float(c.c_stick[1])],
        "l": float(c.l_shoulder), "r": float(c.r_shoulder),
    }


class Guard:
    """Audit-hook tripwire: no network, subprocesses, ctypes, foreign /proc, or files outside the
    interpreter, the bot file and its scratch dir. Not a security boundary (see docs), but it turns
    accidental or casual cheating into a logged, counted violation."""

    BLOCKED = {"socket.connect", "socket.bind", "socket.sendto", "socket.sendmsg", "socket.getaddrinfo",
               "subprocess.Popen", "os.system", "os.exec", "os.posix_spawn", "os.spawn", "os.fork",
               "os.forkpty", "pty.spawn", "ctypes.dlopen", "ctypes.dlsym", "os.kill", "os.killpg"}

    def __init__(self, bot_file: str, scratch: str):
        self.bot_file, self.scratch = os.path.realpath(bot_file), os.path.realpath(scratch)
        prefixes = {sys.prefix, sys.base_prefix, sys.exec_prefix, sys.base_exec_prefix}
        here = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))  # melee_llm package
        self.readable = tuple(os.path.realpath(p) + os.sep for p in prefixes | {here}) + (self.scratch + os.sep,)
        # HOME points at the scratch dir in the child, so list user-data roots explicitly
        self.private = ("/home/", "/root/", "/tmp/", "/var/tmp/", "/dev/shm/", "/mnt/", "/media/", "/srv/", "/run/", "/opt/")
        self.violations = 0
        self.armed = False

    def _readable(self, path: str) -> bool:
        if path == self.bot_file or path == self.scratch:
            return True
        if path.startswith(os.path.join(os.path.dirname(self.bot_file), "__pycache__", "")):
            return True  # the import system probing for the bot's own bytecode cache
        if path.startswith("/proc/"):
            return path.startswith(("/proc/self/", "/proc/thread-self/")) or path in ("/proc/self", "/proc/meminfo", "/proc/cpuinfo")
        if path.startswith(self.readable):
            return True
        return not path.startswith(self.private)

    def __call__(self, event: str, args) -> None:
        if not self.armed:
            return
        why = None
        if event in self.BLOCKED:
            why = event
        elif event in ("open", "os.listdir", "os.scandir") and args and isinstance(args[0], (str, bytes, os.PathLike)):
            path = os.fsdecode(args[0])
            path = os.path.realpath(path if os.path.isabs(path) else os.path.join(self.scratch, path))
            writing = event == "open" and (
                (isinstance(args[1], str) and any(c in args[1] for c in "wax+"))
                or (isinstance(args[2], int) and args[2] & (os.O_WRONLY | os.O_RDWR | os.O_CREAT)))
            if writing and not (path + os.sep).startswith(self.scratch + os.sep):
                why = f"write {path}"
            elif not writing and not self._readable(path):
                why = f"read {path}"
        elif event in ("os.remove", "os.rename", "os.rmdir", "os.mkdir", "shutil.rmtree", "os.chmod"):
            path = os.path.realpath(os.fsdecode(args[0])) if args and isinstance(args[0], (str, bytes, os.PathLike)) else ""
            if not (path + os.sep).startswith(self.scratch + os.sep):
                why = f"{event} {path}"
        if why:
            self.violations += 1
            raise PermissionError(f"botwriter policy: {why} is not allowed")


def load_bot(path: str):
    spec = importlib.util.spec_from_file_location("submitted_bot", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["submitted_bot"] = module
    spec.loader.exec_module(module)
    cls = getattr(module, "Bot", None)
    if cls is None:
        raise TypeError("bot file must define a class named Bot")
    bot = cls()
    char = getattr(bot, "character", melee.Character.FOX)
    char = melee.Character[char] if isinstance(char, str) else melee.Character(char)
    return bot, char


def main() -> None:
    bot_file, scratch = sys.argv[1], sys.argv[2]
    proto_out = os.fdopen(os.dup(1), "wb")
    os.dup2(2, 1)
    sys.stdout = sys.stderr
    proto_in = sys.stdin.buffer
    os.chdir(scratch)
    guard = Guard(bot_file, scratch)
    sys.addaudithook(guard)
    guard.armed = True

    def reply(obj):
        obj["viol"] = guard.violations
        write_frame(proto_out, json.dumps(obj).encode())

    try:
        bot, char = load_bot(bot_file)
    except BaseException:
        reply({"type": "error", "error": traceback.format_exc(limit=5)})
        return
    reply({"type": "ready", "character": char.name, "name": getattr(bot, "name", type(bot).__name__)})

    ctrl, port, opp, errors_logged = FakeController(), 1, 2, 0
    while (raw := read_frame(proto_in)) is not None:
        msg = pickle.loads(raw)
        kind = msg[0]
        if kind == "setup":
            _, port, opp = msg
            ctrl = FakeController(port)
            continue
        if kind == "end":
            hook = getattr(bot, "on_game_end", None)
            if hook:
                try:
                    hook(msg[1])
                except Exception:
                    traceback.print_exc()
            ctrl.release_all()
            continue
        if kind == "close":
            break
        _, seq, gs = msg
        t0, err = time.perf_counter(), None
        try:
            bot.step(gs, ctrl, port, opp)
        except Exception as e:
            err = f"{type(e).__name__}: {e}"
            if errors_logged < 20:
                errors_logged += 1
                traceback.print_exc()
        ctrl.flush()
        reply({"type": "act", "seq": seq, "state": controller_state(ctrl.current), "err": err,
               "ms": (time.perf_counter() - t0) * 1000})


if __name__ == "__main__":
    main()
