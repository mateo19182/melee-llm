"""LiveLLM: the LLM thinks on a background thread; step() never blocks and keeps the executor running."""
from __future__ import annotations

import queue
import threading

import melee

from melee_llm.agents.llm_common import LLMAgent, parse_spec
from melee_llm.state import actionable

END_WAIT_S = 5.0  # at game end, how long to wait for an in-flight call so its tokens are counted


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
        self.seen_frame = 0  # latest game frame, read by the worker thread to label screenshots

    def _worker(self) -> None:
        while not self._stop.is_set():
            try:
                job = self._req.get(timeout=.2)
            except queue.Empty:
                continue
            # Screenshot here, off the game thread (a grab costs ~10-25 ms, step() has 16): it shows the game a
            # frame or two after job[0]; each Shot carries the frame step() last saw when it was grabbed.
            shots = self.capture(self.seen_frame) if self.camera else []
            self.next_images = [s.data_uri() for s in shots]
            self._res.put(((*job, shots), self.think(job[2])))

    def _default(self, gs: melee.GameState) -> dict:
        me, op = gs.players[self.port], gs.players[self.opponent_port]
        close = abs(float(op.position.x - me.position.x)) < 30 and abs(float(op.position.y - me.position.y)) < 30
        if close and me.on_ground and not actionable(op):
            return {"action": "shield", "frames": 12}
        return {"action": "dash_dance", "frames": 30} if me.on_ground else {"action": "wait", "frames": 5}

    def step(self, gs: melee.GameState) -> None:
        self.begin_frame(gs)
        self.seen_frame = int(gs.frame)
        if self.camera and self.clip > 1 and not self.camera.ring_running:
            self.camera.start_ring(lambda: self.seen_frame, self.clip_every / 60)
        me = gs.players[self.port]
        try:
            res = (*self._res.get_nowait(), int(gs.frame))
            if self.pending:  # never applied: still count its tokens
                self._drop(self.pending, int(gs.frame), "superseded")
            self.pending, self.inflight = res, False
        except queue.Empty:
            pass
        if self.pending and self.ex.interruptible and self.can_decide(me):
            got, self.pending = self.pending, None
            (asked, obs, user, shots), rep, arrived = got
            stale = int(gs.frame) - asked
            if stale <= self.max_stale:
                self.apply(gs, obs, user, rep, asked, latency_frames=arrived - asked, stale_frames=stale, shots=shots)
            else:
                self._drop(got, int(gs.frame), "stale")
        if not self.inflight and self.can_decide(me) and (
                self.ex.idle or gs.frame - self.last_asked >= self.interval):
            obs, user = self.snapshot(gs)
            self._req.put_nowait((int(gs.frame), obs, user))
            self.inflight, self.last_asked = True, gs.frame
        if self.ex.idle and self.can_decide(me):
            self.ex.start(self._default(gs))
        self.ex.step(gs)

    def _drop(self, pending, frame: int, why: str) -> None:
        """A reply that was never applied. Its tokens were still spent, so the record carries them (bench spend)."""
        (asked, *_), rep, _arrived = pending
        rec = {"type": "dropped", "why": why, "frame": frame, "asked_frame": asked, "stale_frames": frame - asked,
               "decision": rep.args, "latency_s": round(rep.latency_s, 3), "prompt_tokens": rep.prompt_tokens,
               "completion_tokens": rep.completion_tokens, "reply_mode": rep.mode, "error": rep.error}
        self.dropped.append(rec)
        self.log.write(rec)

    def on_game_end(self, gs):
        if self.log is not None:
            frame = int(gs.frame) if gs else -1
            if self.pending:
                self._drop(self.pending, frame, "game_end")
            if self.inflight:  # a call still running: wait briefly so its usage is logged
                try:
                    self._drop((*self._res.get(timeout=END_WAIT_S), frame), frame, "game_end")
                    self.inflight = False
                except queue.Empty:
                    pass
        self.pending = None
        super().on_game_end(gs)

    def close(self) -> None:
        if self.camera:
            self.camera.stop_ring()
        self._stop.set()
        self._thread.join(timeout=2)
