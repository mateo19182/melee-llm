"""In-place checkpoint and rollback of one simulator match, for tree search (make a move, look, take it back).

Needs our patch to melee-sim-light (`scripts/patch_sim.sh`), which adds four calls to its C library. A frame
changes about 3 KB of the match's 3.2 MB of memory, spread over a few dozen 4 KiB pages, always the same ones. So a
checkpoint copies only the pages known to change ("dirty" pages), and a rollback copies them back: about 9 µs
against 300 µs for the library's own lane copy, which moves everything and re-links every pointer.

The dirty pages are learned by playing random inputs. Exactness is checked, not assumed: `verify()` compares every
other page with a full copy taken at the start. A rollback never restores those pages, so a page that changed
behind our back stays changed and the next `verify()` finds it. A search whose final `verify()` passes was exact.
"""
from __future__ import annotations

import ctypes

import numpy as np

PAGE = 4096
_U32P = ctypes.POINTER(ctypes.c_uint32)


def available() -> bool:
    from melee_sim import _native
    return hasattr(_native.library(), "msl_batch_rollback")


class Rollback:
    def __init__(self, env, lane: int = 0, depth: int = 64):
        from melee_sim import _native
        self.lib, self.h, self.lane = _native.library(), env._handle, lane
        if not hasattr(self.lib, "msl_batch_rollback"):
            raise RuntimeError("melee-sim-light lacks checkpoint/rollback: run scripts/patch_sim.sh")
        for name in ("checkpoint_size", "checkpoint", "rollback", "diff_pages"):
            getattr(self.lib, f"msl_batch_{name}").restype = ctypes.c_int
        size = ctypes.c_size_t()
        self._ok(self.lib.msl_batch_checkpoint_size(self.h, lane, ctypes.byref(size)))
        self.size, self.npages = size.value, size.value // PAGE + 1
        self.base = (ctypes.c_uint8 * self.size)()  # full copy of the starting state
        self._ok(self.lib.msl_batch_checkpoint(self.h, lane, self.base, self.size, None, 0))
        self.stack = [(ctypes.c_uint8 * self.size)() for _ in range(depth)]  # only dirty pages get touched
        self.pages = np.zeros(0, dtype=np.uint32)

    @staticmethod
    def _ok(code: int) -> None:
        if code != 0:
            raise RuntimeError(f"simulator checkpoint call failed ({code})")

    def changed(self) -> np.ndarray:
        """Pages that differ from the starting state right now."""
        flags = (ctypes.c_uint8 * self.npages)()
        self._ok(self.lib.msl_batch_diff_pages(self.h, self.lane, self.base, self.size, flags, self.npages))
        return np.flatnonzero(np.frombuffer(flags, dtype=np.uint8)).astype(np.uint32)

    def add(self, pages: np.ndarray) -> None:
        self.pages = np.union1d(self.pages, pages).astype(np.uint32)
        self._ptr = self.pages.ctypes.data_as(_U32P)

    def reset(self) -> None:
        """Back to the starting state, every page."""
        self._ok(self.lib.msl_batch_rollback(self.h, self.lane, self.base, self.size, None, 0))

    def checkpoint(self, level: int) -> None:
        self._ok(self.lib.msl_batch_checkpoint(self.h, self.lane, self.stack[level], self.size, self._ptr,
                                               len(self.pages)))

    def rollback(self, level: int) -> None:
        self._ok(self.lib.msl_batch_rollback(self.h, self.lane, self.stack[level], self.size, self._ptr,
                                             len(self.pages)))

    def verify(self) -> np.ndarray:
        """Pages outside the dirty set that no longer match the starting state: empty when every rollback so
        far was exact."""
        return np.setdiff1d(self.changed(), self.pages)
