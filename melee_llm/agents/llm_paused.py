"""PausedLLM: the game waits (Dolphin blocking_input) while the LLM picks the next macro."""
from __future__ import annotations

import time

import melee

from melee_llm.agents.llm_common import LLMAgent, parse_spec


class PausedLLM(LLMAgent):
    """Decides whenever the current macro ends, or every `interval` frames while it is interruptible.

    Thinking blocks `step`, which is only safe in `paused` matches; `think_s` per decision is logged.
    """
    kind = "llm_paused"

    def __init__(self, spec: str | None = None, **kw):
        super().__init__(**(parse_spec(spec) | kw))
        self.last_decision = -10**9

    def step(self, gs: melee.GameState) -> None:
        self.begin_frame(gs)
        me = gs.players[self.port]
        due = self.ex.idle or (gs.frame - self.last_decision >= self.interval and self.ex.interruptible)
        if due and self.can_decide(me):
            obs, user = self.snapshot(gs)
            shots = self.capture(int(gs.frame))  # the game is blocked on our input, so this is frame gs.frame
            self.next_images = [s.data_uri() for s in shots]
            t0 = time.perf_counter()
            rep = self.think(user)
            self.apply(gs, obs, user, rep, int(gs.frame), think_s=round(time.perf_counter() - t0, 3),
                       latency_frames=0, stale_frames=0, shots=shots)
            self.last_decision = gs.frame
        elif self.camera and self.clip > 1:
            self.camera.tick(int(gs.frame), self.clip_every)
        self.ex.step(gs)
