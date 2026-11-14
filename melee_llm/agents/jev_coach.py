"""JevCoach: CoachedBot (Reyn body) whose command choice comes from Jev instead of an LLM. See docs/jev.md.

One Choice per call over Reyn's command ids plus `keep` and `none` (108 options for Fox on Battlefield, under
Jev's 255 limit). Same prompt state, interval, history and .coach.jsonl log as `coach:`; each decision record
also carries the top-k probabilities and the answer's confidence.

match.py spec: coach_jev[:<model>][,interval=60,command=<id>,top_k=5,shuffle=1,timeout=3,history=4]
"""
from __future__ import annotations

import random

from melee_llm import jev as J
from melee_llm.agents.coach import CoachedBot
from melee_llm.agents.llm_common import parse_spec
from melee_llm.llm import Reply
from melee_llm.state import stage_text

KEEP = "keep the current command because it is working"
NONE = "clear the command: the bot plays its own strong unsteered game"


class JevCoach(CoachedBot):
    def __init__(self, spec: str | None = None, *, top_k: int = 5, shuffle: bool = True, timeout: float = 3.0,
                 retries: int = 2, seed: int | None = None, **kw):
        opts = parse_spec(spec)
        model = opts.pop("model", "") or "jev-latest"
        self.top_k = int(opts.pop("top_k", top_k))
        self.shuffle = bool(int(opts.pop("shuffle", shuffle)))
        timeout, retries = float(opts.pop("timeout", timeout)), int(opts.pop("retries", retries))
        if opts.get("body", "reyn") != "reyn":
            raise ValueError("coach_jev steers Reyn only (HAL's knobs are numeric)")
        rest = ",".join(f"{k}={v}" for k, v in opts.items())
        super().__init__(f"random,{rest}" if rest else "random", seed=seed, **kw)  # random: no LLM client is built
        self.random, self.model, self.llm = False, model, None
        self.jev = J.Jev(model, timeout=timeout, retries=retries, deadline=timeout * (retries + 1))
        self.qrng = random.Random(seed)
        self._extra: dict = {}

    @property
    def name(self) -> str:
        return f"coach_jev:{self.model}/{self.body.name}"

    def on_game_start(self, gs, replay):
        super().on_game_start(gs, replay)
        me, op = gs.players[self.port], gs.players[self.opponent_port]
        self.brief = (f"You coach a neural-network Melee bot ({me.character.name}, marked YOU) against "
                      f"{op.character.name}. {stage_text(gs.stage)} The bot plays every frame on its own; every "
                      f"{self.interval / 60:.1f} s you may set one persistent strategy command, which stays active "
                      f"until changed. Changing too often makes the bot erratic. Win by taking stocks.")
        write = self.log.write
        self.log.write = lambda rec: write({**rec, **self._extra} if rec.get("type") == "decision" else rec)

    def _decide(self, user: str) -> tuple[dict, Reply | None]:
        crit = {cid: c.name for cid, c in self.commands.items()} | {"keep": KEEP, "none": NONE}
        items = list(crit.items())
        if self.shuffle:
            self.qrng.shuffle(items)
        q = {"command": J.choice(dict(items), "Which strategy command should the bot (YOU) follow for the next "
                                              "few seconds to win?")}
        rep = self.jev.ask({"role": self.brief, "situation": user.removesuffix("\nChoose.")}, q)
        out = Reply(None, model=rep.model, latency_s=rep.latency_s, prompt_tokens=rep.input_tokens,
                    completion_tokens=rep.output_tokens, mode="jev", error=rep.error, text=rep.error[:400])
        if not rep.ok:
            return {}, out
        top = rep.top("command", self.top_k)
        cmd = rep.pick("command")
        out.args = {"command": cmd, "why": f"p={dict(top).get(cmd, 0):.2f} conf={rep.confidence('command') or 0:.2f}; "
                                           "next " + ", ".join(f"{c} {p:.2f}" for c, p in top[1:3])}
        out.extra = {"probabilities": top, "confidence": rep.confidence("command"), "model": rep.model,
                     "usd": round(rep.usd, 8), "attempts": rep.attempts}
        return out.args, out

    def _apply(self, decision, frame, rep, user, asked=None):
        self._extra = rep.extra if rep else {}
        super()._apply(decision, frame, rep, user, asked=asked)

    def on_game_end(self, gs):
        if self.log is not None:
            self.log.write({"type": "jev_stats", **self.jev.stats()})
        super().on_game_end(gs)

    def close(self):
        super().close()
        self.jev.close()
