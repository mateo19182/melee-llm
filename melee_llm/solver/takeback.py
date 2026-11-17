"""Checkpoint and rollback of one simulator match, for the Python searches (`force.py`, `nash.py`).

melee-brute write-protects the match's memory and keeps what each page held before its first write, so a rollback
is exact by construction and there are no pages to learn. `verify`, `add` and `restore` are what the searches
called on the older take-back, which learned its pages from random play and had to be checked; they stay as
no-ops so that code keeps one shape.
"""
from __future__ import annotations

import atexit
import ctypes
import weakref

import numpy as np
from melee_brute import engine

_NONE = np.zeros(0, dtype=np.uint32)
_LIVE: weakref.WeakSet = weakref.WeakSet()


@atexit.register
def _close_all() -> None:  # before the interpreter frees the matches in whatever order it likes
    for rb in list(_LIVE):
        rb.close()


def make_env(**kwargs):
    """An `EnvBatch` that lifts its take-back's protection before freeing the memory under it, in whatever order
    the garbage collector drops the two."""
    import melee_sim as msl

    class Env(msl.EnvBatch):
        takeback = None

        def close(self) -> None:
            if self.takeback is not None:
                self.takeback.close()
            super().close()
    return Env(**kwargs)


class Rollback:
    def __init__(self, env, depth: int = 256):
        self.lib, self.brute, self._root = engine.library(), ctypes.c_void_p(), depth
        env.takeback = self  # `make_env`: closing the match closes this first
        engine.ok(self.lib.msl_brute_create(env._handle, 0, depth + 1, ctypes.byref(self.brute)))
        _LIVE.add(self)
        self.rebase()

    def close(self) -> None:
        """Lift the protection. A match left protected would catch the faults of the next one made at the same
        addresses, so every search has to let go of its own."""
        if self.brute:
            self.lib.msl_brute_destroy(self.brute)
            self.brute = ctypes.c_void_p()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

    def rebase(self) -> None:
        """Take the current state as the one `reset()` returns to. Call it after loading a savestate."""
        engine.ok(self.lib.msl_brute_reset(self.brute))
        self.checkpoint(self._root)

    def reset(self) -> None:
        self.rollback(self._root)

    def checkpoint(self, level: int) -> None:
        engine.ok(self.lib.msl_brute_checkpoint(self.brute, level))

    def rollback(self, level: int) -> None:
        engine.ok(self.lib.msl_brute_rollback(self.brute, level))

    def verify(self) -> np.ndarray:
        return _NONE

    def add(self, pages) -> None:
        pass

    def restore(self, pages) -> None:
        pass
