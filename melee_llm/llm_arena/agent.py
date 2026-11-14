"""ArenaLLM: the standard llm_paused player plus the arena's retry rule and game-length cap.

The model sees exactly what `llm_paused` sees (same prompt, macros, reflexes and fallback); only two things
are added around it:

- **Retries.** A transport failure (timeout, HTTP error, rate limit: `Reply.mode == "error"`) is retried up to
  `retries` times with exponential backoff. The game is blocked meanwhile, so retries cost wall time only.
  An unparseable or unknown answer is the model's own fault and is never retried: it plays the fallback
  macro like in any llm_paused game and counts as an invalid output.
- **Cap.** Once `gs.frame >= cap_frames` the player stops asking the model. The port marked `quitter` then
  pauses and quits the game with L+R+A+START, so the game ends cleanly (replay finalised, decision log
  renamed, registry entry "finished"); the runner scores it from the last in-game frame by stocks, then
  percent, like a time-out.
"""
from __future__ import annotations

import threading
import time

import melee
from melee import Button as B

from melee_llm.actions import ACTIONS
from melee_llm.agents.llm_paused import PausedLLM
from melee_llm.llm import Reply


class ArenaLLM(PausedLLM):
    kind = "llm_paused"  # same player; the arena only wraps it

    def __init__(self, spec: str, cap_frames: int = 0, quitter: bool = False, retries: int = 4, backoff_s: float = 3.0):
        super().__init__(spec)
        self.cap_frames, self.quitter, self.retries, self.backoff_s = cap_frames, quitter, retries, backoff_s
        self.api_retries = 0  # failed calls that were retried
        self.api_failed = 0  # decisions whose every attempt failed (fallback macro played)
        self.capped_at: int | None = None
        self._quit_steps = 0
        self._ended = threading.Event()

    def think(self, user: str, *args, **kw) -> Reply:
        for attempt in range(self.retries + 1):
            rep = super().think(user, *args, **kw)
            if rep.mode != "error":
                return rep
            if attempt < self.retries:
                self.api_retries += 1
                time.sleep(self.backoff_s * 2 ** attempt)
        self.api_failed += 1
        return rep

    def step(self, gs: melee.GameState) -> None:
        if not self.cap_frames or gs.frame < self.cap_frames:
            return super().step(gs)
        if self.capped_at is None:
            self.capped_at = int(gs.frame)
            self.controller.release_all()
        if self.quitter:
            self._quit()

    def _quit(self) -> None:
        """Hold L+R+A, then tap START to pause. A paused game emits no frames, so console.step() blocks and no
        agent runs; a thread keeps feeding the pipe (re-pressing START with L+R+A held) until the game quits."""
        n, c = self._quit_steps, self.controller
        self._quit_steps += 1
        if n == 0:
            self._hold_lra()
        elif n == 2:
            c.press_button(B.BUTTON_START)
            threading.Thread(target=self._quit_feeder, daemon=True).start()

    def _hold_lra(self) -> None:
        c = self.controller
        for b in (B.BUTTON_L, B.BUTTON_R, B.BUTTON_A):
            c.press_button(b)
        c.press_shoulder(B.BUTTON_L, 1.0)
        c.press_shoulder(B.BUTTON_R, 1.0)

    def _quit_feeder(self) -> None:
        c = self.controller
        time.sleep(0.5)
        for i in range(400):  # ~40 s at most
            if self._ended.is_set():
                return
            (c.press_button if i % 2 else c.release_button)(B.BUTTON_START)
            c.flush()
            time.sleep(0.1)

    def on_game_end(self, gs):
        self._ended.set()
        super().on_game_end(gs)

    def summary(self) -> dict:
        """Per-game stats for the results file (self.stats survives on_game_end)."""
        s = self.stats
        ok = [r for r in s if r["reply_mode"] != "error"]
        invalid = [r for r in ok if r["error"] or r["decision"].get("action") not in ACTIONS]
        actions: dict[str, int] = {}
        for r in s:
            actions[r["action"]] = actions.get(r["action"], 0) + 1
        return {"decisions": len(s), "invalid": len(invalid), "api_failed": self.api_failed,
                "api_retries": self.api_retries,
                "mean_latency_s": round(sum(r["latency_s"] for r in ok) / len(ok), 3) if ok else None,
                "mean_think_s": round(sum(r.get("think_s", 0) for r in s) / len(s), 3) if s else None,
                "prompt_tokens": sum(r["prompt_tokens"] for r in s),
                "completion_tokens": sum(r["completion_tokens"] for r in s),
                "capped_at": self.capped_at, "actions": dict(sorted(actions.items(), key=lambda kv: -kv[1]))}
