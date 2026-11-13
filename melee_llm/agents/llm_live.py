"""LiveLLM: the LLM thinks on a background thread; step() never blocks and keeps the executor running."""
from __future__ import annotations

import queue
import threading

import melee

from melee_llm.agents.llm_common import LLMAgent, parse_spec
from melee_llm.state import actionable


class LiveLLM(LLMAgent):
    """Real-time play. While a request is in flight the executor keeps running the last macro, or a safe
    default (dash dance when far, shield when an attack is coming close). Logged per decision:
    `latency_frames` (asked → reply) and `stale_frames` (observed state → macro actually started)."""
    kind = "llm_live"

    def __init__(self, spec: str | None = None, max_stale: int = 120, **kw):
        kw = parse_spec(spec) | kw
        self.max_stale = kw.pop("max_stale", max_stale)
        super().__init__(**kw)
        self._req: queue.Queue = queue.Queue(maxsize=1)
        self._res: queue.Queue = queue.Queue()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._worker, daemon=True, name=f"llm-live-{self.model}")
        self._thread.start()
        self.inflight = False
        self.pending = None  # reply waiting for a non-interruptible macro to finish
        self.last_asked = -10**9

    def _worker(self) -> None:
        while not self._stop.is_set():
            try:
                job = self._req.get(timeout=.2)
            except queue.Empty:
                continue
            self._res.put((job, self.think(job[2])))

    def _default(self, gs: melee.GameState) -> dict:
        me, op = gs.players[self.port], gs.players[self.opponent_port]
        close = abs(float(op.position.x - me.position.x)) < 30 and abs(float(op.position.y - me.position.y)) < 30
        if close and me.on_ground and not actionable(op):
            return {"action": "shield", "frames": 12}
        return {"action": "dash_dance", "frames": 30} if me.on_ground else {"action": "wait", "frames": 5}

    def step(self, gs: melee.GameState) -> None:
        self.begin_frame(gs)
        me = gs.players[self.port]
        try:
            self.pending = (*self._res.get_nowait(), int(gs.frame))
            self.inflight = False
        except queue.Empty:
            pass
        if self.pending and self.ex.interruptible and self.can_decide(me):
            (asked, obs, user), rep, arrived = self.pending
            self.pending = None
            stale = int(gs.frame) - asked
            if stale <= self.max_stale:
                self.apply(gs, obs, user, rep, asked, latency_frames=arrived - asked, stale_frames=stale)
            else:
                self.log.write({"type": "dropped", "frame": int(gs.frame), "asked_frame": asked, "stale_frames": stale,
                                "decision": rep.args, "latency_s": round(rep.latency_s, 3)})
        if not self.inflight and self.can_decide(me) and (
                self.ex.idle or gs.frame - self.last_asked >= self.interval):
            obs, user = self.snapshot(gs)
            self._req.put_nowait((int(gs.frame), obs, user))
            self.inflight, self.last_asked = True, gs.frame
        if self.ex.idle and self.can_decide(me):
            self.ex.start(self._default(gs))
        self.ex.step(gs)

    def on_game_end(self, gs):
        self.pending = None
        super().on_game_end(gs)

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2)
