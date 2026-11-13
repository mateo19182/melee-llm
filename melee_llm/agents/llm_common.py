"""Shared brain for the LLM players: prompt building, decision history, JSONL decision log, executor wiring."""
from __future__ import annotations

import json
import time
from pathlib import Path

import melee
from melee import Action as A

from melee_llm.actions import Executor, action_help, tool_schema
from melee_llm.agents.base import Agent
from melee_llm.llm import LLM, Reply
from melee_llm.runner import ROOT
from melee_llm.state import DEAD, EventTracker, actionable, framedata, observe, render, stage_text

SYSTEM = """You are an AI playing Super Smash Bros. Melee (NTSC 1.02) as {me} against {opp}. {stage}
Units: x grows right, y grows up, floor y=0; 60 frames = 1 second. Distance <20 is melee range, <35 is close.
Win by taking stocks: damage raises percent, higher percent = more knockback; a KO happens past a blast zone.
How to read the state: "ACTIVE" = the attack hitbox is out now; "startup"/"endlag" = vulnerable windows to punish;
"busy" = cannot act yet; "hitstun" = combo them; "OFFSTAGE" = edgeguard them (or recover yourself).
Fundamentals: whiff-punish endlag; shield or retreat when an ACTIVE attack is in range; grab shielding opponents;
don't repeat a failing approach; at high percent go for KO moves (smashes, back air, up air, edgeguards).
{tips}
Low-level execution is automatic: you pick one macro per decision; a controller executes it frame by frame.
Reflexes run without you: DI + tech when hit, mash when grabbed, recovery when you fall below the stage.
Actions (params in brackets; dir is relative to the opponent unless left/right/center):
{actions}
Answer with exactly one `act` choice. Keep `reason` under 12 words."""

TIPS = {
    melee.Character.FOX: "Fox: shine (down-B) is a frame-1 combo starter and escape; nair/dair→shine and up-smash/up-air kill; "
                         "laser to chip; side_b/up_b recover.",
    melee.Character.FALCO: "Falco: short-hop lasers control neutral; dair spikes, shine→combo; bair and up-smash kill; "
                           "recovery is short, use side_b near ledge height.",
}


def parse_spec(arg: str | None) -> dict:
    """match.py spec text after the colon, "model[,key=value...]" → constructor kwargs."""
    if not arg:
        return {}
    model, *rest = arg.split(",")
    kw = {"model": model} if model else {}
    for item in rest:
        k, _, v = item.partition("=")
        try:
            kw[k] = json.loads(v)
        except json.JSONDecodeError:
            kw[k] = v
    return kw


class DecisionLog:
    """One JSONL per game; renamed next to the .slp on game end (<replay>.p<port>.llm.jsonl)."""

    def __init__(self, directory: Path, tag: str):
        directory.mkdir(parents=True, exist_ok=True)
        self.dir, self.t0 = directory, time.time()
        self.path = directory / f"llm-{time.strftime('%Y%m%dT%H%M%S')}-{tag}.jsonl"
        self.f = self.path.open("a")

    def write(self, rec: dict) -> None:
        self.f.write(json.dumps(rec, default=lambda o: o.item() if hasattr(o, "item") else str(o)) + "\n")
        self.f.flush()

    def close(self, port: int) -> Path:
        self.f.close()
        slps = [p for p in self.dir.glob("*.slp") if p.stat().st_mtime >= self.t0 - 5]
        if slps:
            target = max(slps, key=lambda p: p.stat().st_mtime).with_suffix(f".p{port}.llm.jsonl")
            self.path = self.path.rename(target)
        return self.path


class LLMAgent(Agent):
    kind = "llm"

    def __init__(self, model: str = "claude-haiku-4-5-20251001", interval: int = 30, history: int = 6,
                 mode: str = "json", effort: str | None = "none", base_url: str | None = None, timeout: float = 20.0,
                 reflexes: bool = True,
                 log_dir: Path | None = None, system_extra: str = "", **_):
        super().__init__()
        self.model, self.interval, self.history_len = model, interval, history
        self.llm = LLM(model, base_url=base_url, timeout=timeout, mode=mode, effort=effort)
        self.tool = tool_schema()
        self.reflexes, self.system_extra = reflexes, system_extra
        self.log_dir = Path(log_dir) if log_dir else ROOT / "replays"
        self.log: DecisionLog | None = None
        self.history: list[dict] = []
        self.stats: list[dict] = []

    @property
    def name(self) -> str:
        return f"{self.kind}:{self.model}"

    def setup(self, controller, port, opponent_port):
        super().setup(controller, port, opponent_port)
        self.ex = Executor(controller, port, opponent_port, self.reflexes)
        self.tracker = EventTracker(port, opponent_port)
        framedata()  # 0.5 s CSV load; keep it out of the first live frame

    # ------------------------------------------------------------ per-frame helpers

    def begin_frame(self, gs: melee.GameState) -> None:
        if self.log is None:
            self._start_game(gs)
        self.tracker.update(gs)

    def _start_game(self, gs: melee.GameState) -> None:
        self.log = DecisionLog(self.log_dir, f"p{self.port}-{self.kind}")
        self.history, self.stats = [], []
        me, op = gs.players[self.port], gs.players[self.opponent_port]
        self.system = SYSTEM.format(me=me.character.name, opp=op.character.name, stage=stage_text(gs.stage),
                                    tips=TIPS.get(me.character, "") + self.system_extra, actions=action_help())
        self.log.write({"type": "game_start", "agent": self.kind, "model": self.model, "port": self.port,
                        "character": me.character.name, "opponent": op.character.name, "stage": gs.stage.name,
                        "interval": self.interval, "mode": self.llm.mode, "effort": self.llm.effort, "system_prompt": self.system})

    def can_decide(self, me: melee.PlayerState) -> bool:
        return me.action not in DEAD and (actionable(me) or me.action == A.EDGE_HANGING)

    def snapshot(self, gs: melee.GameState) -> tuple[dict, str]:
        """Close out the previous decision's outcome and build the user prompt for the current state."""
        events = self.tracker.drain()
        done = self.ex.drain()
        if self.history:
            last = self.history[-1]
            last["outcome"] = "; ".join(f"{n}: {o}" for n, o, _ in done) or "running"
            last["events"] = events
        obs = observe(gs, self.port, self.opponent_port)
        obs["events"] = events
        past = [f"f{h['frame']} {h['desc']} → {h.get('outcome', '?')}" + (f" | {h['events']}" if h.get("events") else "")
                for h in self.history[-self.history_len:-1]]
        if self.history:
            h = self.history[-1]
            past.append(f"f{h['frame']} {h['desc']} → {h.get('outcome', '?')}")
        user = render(obs, events)
        if past:
            user += "\nRECENT DECISIONS:\n" + "\n".join(past)
        if self.ex.cur:
            user += f"\nNOW RUNNING: {self.ex.cur.name} ({self.ex.cur.frames}f)"
        return obs, user + "\nChoose the next action."

    def think(self, user: str) -> Reply:
        return self.llm.choose(self.system, user, self.tool)

    def apply(self, gs: melee.GameState, obs: dict, user: str, rep: Reply, asked_frame: int, **extra) -> None:
        decision = rep.args if rep.args and rep.args.get("action") else {"action": "dash_dance", "frames": 20}
        name = self.ex.start(decision)
        desc = name + "(" + ",".join(f"{v}" for k, v in decision.items() if k not in ("action", "reason")) + ")"
        self.history.append({"frame": int(gs.frame), "desc": desc})
        rec = {"type": "decision", "frame": int(gs.frame), "asked_frame": asked_frame, "model": rep.model,
               "obs_text": user, "obs": obs, "decision": decision, "action": name,
               "reason": (rep.args or {}).get("reason", ""), "latency_s": round(rep.latency_s, 3),
               "prompt_tokens": rep.prompt_tokens, "completion_tokens": rep.completion_tokens,
               "reply_mode": rep.mode, "error": rep.error, "raw": rep.text[:600] if rep.error else "", **extra}
        self.stats.append(rec)
        self.log.write(rec)

    def on_game_end(self, gs):
        if self.log is None:
            return
        lat = [s["latency_s"] for s in self.stats]
        summary = {"type": "game_end", "frame": int(gs.frame) if gs else None, "decisions": len(lat),
                   "errors": sum(bool(s["error"]) for s in self.stats),
                   "mean_latency_s": round(sum(lat) / len(lat), 3) if lat else None,
                   "prompt_tokens": sum(s["prompt_tokens"] for s in self.stats),
                   "completion_tokens": sum(s["completion_tokens"] for s in self.stats)}
        for k in ("latency_frames", "stale_frames"):
            v = [s[k] for s in self.stats if k in s]
            if v:
                summary[f"mean_{k}"] = round(sum(v) / len(v), 1)
        self.log.write(summary)
        self.log.close(self.port)
        self.log = None
