"""CoachedBot: an LLM coach steers a fast learned body (Reyn by default, or HAL) from a background thread.

The body plays every frame; every `interval` frames the coach sends the LLM a compact state, the events
since its last call and the body's valid commands, and the LLM answers with strict JSON: a command id
(or "keep"/"none") plus a one-line rationale. step() never blocks. Each decision is logged to
<replay>.p<port>.coach.jsonl. See docs/coach.md.

match.py spec: coach:<model>[,body=reyn|hal,interval=60,body_arg=...,command=<id>,timeout=10]
<model> "random" picks a uniformly random valid command at the same interval, without an LLM.
"""
from __future__ import annotations

import csv
import queue
import random
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import melee

from melee_llm.agents.base import Agent
from melee_llm.agents.llm_common import DecisionLog, parse_spec
from melee_llm.bots import HAL, ReynBot
from melee_llm.bots.agent import VENDOR
from melee_llm.llm import LLM, Reply
from melee_llm.runner import ROOT
from melee_llm.state import EventTracker, observe, render, stage_text

MODELS = {"haiku": "claude-haiku-4-5-20251001", "sonnet": "claude-sonnet-5-5"}
REYN_DOCS = VENDOR / "Reyn/docs/commands.md"
REYN_CSV = VENDOR / "Reyn/commands.csv"
SKIP_SECTIONS = {"Character-specific special moves", "Change or clear a command", "Browse commands"}
SPACIE_SECTION = "Fox and Falco techniques"
SWORD = {"Shield Breaker", "Dancing Blade", "Dolphin Slash", "Tipper"}
FIREBALL = {"Fireballs", "Cape", "Jump punch", "Tornado"}
C = melee.Character
SECTION_CHARS = {SPACIE_SECTION: {C.FOX, C.FALCO}}
ROW_CHARS = {**dict.fromkeys(SWORD, {C.MARTH, C.ROY}), **dict.fromkeys(FIREBALL, {C.MARIO, C.LUIGI, C.DOC})}
CSV_CHAR = {C.CPTFALCON: "falcon", C.DK: "donkey_kong", C.DOC: "dr_mario", C.GAMEANDWATCH: "game_and_watch",
            C.POPO: "ice_climbers", C.NANA: "ice_climbers", C.JIGGLYPUFF: "jigglypuff", C.YLINK: "young_link"}
NO_PLATFORMS = {melee.Stage.FINAL_DESTINATION}
END_WAIT_S = 5.0  # at game end, how long to wait for an in-flight call so its tokens are counted


@dataclass(frozen=True)
class Command:
    id: str
    name: str
    phrase: str
    section: str


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def reyn_commands(character: melee.Character, stage: melee.Stage | None = None) -> list[Command]:
    """Reyn's documented command meanings valid for this character/stage, one example phrase each."""
    out, section = [], ""
    for line in REYN_DOCS.read_text().splitlines():
        if line.startswith("## "):
            section = line[3:].strip()
            continue
        m = re.match(r"\| (.+?) \| `(.+?)` \|$", line)
        if not m or section in SKIP_SECTIONS:
            continue
        name, phrase = m.groups()
        allowed = SECTION_CHARS.get(section) or ROW_CHARS.get(name)
        if allowed and character not in allowed:
            continue
        if section == "Platforms" and stage in NO_PLATFORMS:
            continue
        out.append(Command(_slug(name), name, phrase, section))
    key = CSV_CHAR.get(character, character.name.lower())
    with REYN_CSV.open() as f:
        for row in csv.DictReader(f):
            if row["character"] == key:
                cmd = Command(f"special_{row['special_move']}", f"{row['special_move']}: {row['phrase']}",
                              row["phrase"], "Character specials")
                if all(c.phrase.lower() != cmd.phrase.lower() for c in out):
                    out.append(cmd)
    return out


def command_menu(cmds: list[Command]) -> str:
    lines, section = [], None
    for c in cmds:
        if c.section != section:
            section = c.section
            lines.append(f"[{section}]")
        lines.append(f"{c.id}: {c.name}")
    return "\n".join(lines)


SYSTEM = """You coach a neural-network Melee bot ({me}) playing against {opp}. {stage}
The bot plays every frame on its own at 60 fps; you cannot press buttons. Every {secs:.1f} s you may set ONE
persistent strategy command for it, which stays active until you change it. Reply ~1 s later at the earliest,
so choose strategies for the next few seconds, not single reactions. Changing commands too often makes the bot
erratic; keep a command that is working. "none" removes steering (the bot's own unsteered play, which is strong).
Units: x grows right, y up, floor y=0. Win by taking stocks; high percent = easier to KO.
{knobs}"""

REYN_KNOBS = """Valid commands (id: meaning):
{menu}
Use "keep" to leave the current command, "none" to clear it."""
WHY = {"type": "string", "description": "one short line"}
REYN_SCHEMA = {"type": "object", "required": ["command", "why"],
               "properties": {"command": {"type": "string", "description": "a command id, keep or none"}, "why": WHY}}

HAL_KNOBS = """The bot is a transformer conditioned on two numbers:
- return_target: desired discounted reward, in [-20, 140]. ~20 is typical strong play; higher asks for more
  aggressive, riskier, damage-seeking play; lower or negative is passive. null = unconditioned.
- temperature: sampling temperature in [0.8, 1.1]; lower = more deterministic, higher = more varied."""
HAL_SCHEMA = {"type": "object", "required": ["return_target", "temperature", "why"],
              "properties": {"return_target": {"type": ["number", "null"]}, "temperature": {"type": "number"}, "why": WHY}}


class CoachedBot(Agent):
    def __init__(self, spec: str | None = None, *, model: str = "haiku", body: str = "reyn", interval: int = 60,
                 body_arg: str | None = None, command: str | None = None, timeout: float = 10.0,
                 history: int = 4, seed: int | None = None, log_dir: Path | None = None, body_config: dict | None = None):
        kw = parse_spec(spec)
        model = MODELS.get(kw.get("model", model), kw.get("model", model))
        body, interval = kw.get("body", body), int(kw.get("interval", interval))
        body_arg, command = kw.get("body_arg", body_arg), kw.get("command", command)
        timeout, history = float(kw.get("timeout", timeout)), int(kw.get("history", history))
        super().__init__()
        self.model, self.interval, self.history_len, self.initial = model, interval, history, command
        self.kind = body
        if body == "reyn":
            self.body = ReynBot(None, **(body_config or {}))
        elif body == "hal":
            self.body = HAL(body_arg, **(body_config or {}))
        else:
            raise ValueError(f"unknown body {body!r}; use reyn or hal")
        self.random = model == "random"
        self.rng = random.Random(seed)
        self.llm = None if self.random else LLM(model, timeout=timeout, mode="json", max_tokens=200)
        self.log_dir = Path(log_dir) if log_dir else ROOT / "replays"
        self._req: queue.Queue = queue.Queue(maxsize=1)
        self._res: queue.Queue = queue.Queue()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._worker, daemon=True, name=f"coach-{model}")
        self._thread.start()
        self.log: DecisionLog | None = None
        self.records: list[dict] = []

    @property
    def name(self) -> str:
        who = "random" if self.random else self.model
        return f"coach:{who}/{self.body.name}"

    # ------------------------------------------------------------------ lifecycle

    def setup(self, controller, port, opponent_port):
        super().setup(controller, port, opponent_port)
        self.body.character = self.character
        self.body.setup(controller, port, opponent_port)
        self.tracker = EventTracker(port, opponent_port)

    def on_game_start(self, gs, replay):
        self.body.on_game_start(gs, replay)
        self.tracker = EventTracker(self.port, self.opponent_port)
        me, op = gs.players[self.port], gs.players[self.opponent_port]
        self.commands = {c.id: c for c in reyn_commands(me.character, gs.stage)} if self.kind == "reyn" else {}
        if self.kind == "reyn":
            knobs, schema = REYN_KNOBS.format(menu=command_menu(list(self.commands.values()))), REYN_SCHEMA
        else:
            knobs, schema = HAL_KNOBS, HAL_SCHEMA
        self.system = SYSTEM.format(me=me.character.name, opp=op.character.name, stage=stage_text(gs.stage),
                                    secs=self.interval / 60, knobs=knobs)
        self.tool = {"type": "function", "function": {"name": "coach", "parameters": schema}}
        self.current = "none"  # command id (reyn) or knob summary (hal)
        self.history: list[dict] = []
        self.pending_log: dict | None = None
        self.inflight, self.last_asked = False, -10**9
        self.records = []
        self.log = DecisionLog(self.log_dir, f"p{self.port}-coach", replay=replay, port=self.port, suffix="coach")
        self.log.write({"type": "game_start", "coach": "random" if self.random else self.model, "body": self.body.name,
                        "port": self.port, "character": me.character.name, "opponent": op.character.name,
                        "stage": gs.stage.name, "interval": self.interval, "commands": len(self.commands),
                        "system_prompt": self.system})
        if self.initial:
            self._apply({"command": self.initial, "why": "initial"}, int(gs.frame), None, "")

    def on_game_end(self, gs):
        self.body.on_game_end(gs)
        if self.log is None:
            return
        dropped = None
        if self.inflight:  # the last call is still running: wait briefly so its tokens are logged, then drop it
            try:
                (asked, _), (decision, rep) = self._res.get(timeout=END_WAIT_S)
                self.inflight = False
                if rep:
                    dropped = {"type": "dropped", "why": "game_end", "asked_frame": asked, "decision": decision,
                               "latency_s": round(rep.latency_s, 3), "prompt_tokens": rep.prompt_tokens,
                               "completion_tokens": rep.completion_tokens, "error": rep.error}
                    self.log.write(dropped)
            except queue.Empty:
                pass
        self._before_end()
        lat = [r["latency_s"] for r in self.records if r.get("latency_s") is not None]
        replies = [(r.get("router") or {}).get("outcome") for r in self.records]
        self.log.write({"type": "game_end", "frame": int(gs.frame) if gs else None, "decisions": len(self.records),
                        "changes": sum(r["changed"] for r in self.records),
                        "errors": sum(bool(r.get("error")) for r in self.records),
                        "abstained": sum(o == "abstain" for o in replies),
                        "mean_latency_s": round(sum(lat) / len(lat), 3) if lat else None,
                        "prompt_tokens": sum(r.get("prompt_tokens", 0) for r in self.records),
                        "completion_tokens": sum(r.get("completion_tokens", 0) for r in self.records),
                        "dropped": int(dropped is not None), "body_latency": self.body.latency()})
        self.log.close(self.port)
        self.log = None

    def _before_end(self) -> None:
        """Hook: last records before game_end (after any in-flight call was logged)."""

    def close(self):
        self._stop.set()
        self._thread.join(timeout=2)
        self.body.close()

    # ------------------------------------------------------------------ per frame

    def step(self, gs: melee.GameState) -> None:
        self.body.step(gs)  # the body first: it owns the frame budget
        self.tracker.update(gs)
        if self.log is None:
            return
        if self.pending_log is not None:  # the router answered on this frame's step
            self.pending_log["router"] = self.body.applied_steer.get("reply") if self.kind == "reyn" else None
            self.pending_log["active"] = self.body.applied_steer.get("active")
            self.log.write(self.pending_log)
            self.pending_log = None
        try:
            (asked, user), (decision, rep) = self._res.get_nowait()
            self.inflight = False
            self._apply(decision, int(gs.frame), rep, user, asked=asked)
        except queue.Empty:
            pass
        if not self.inflight and gs.frame - self.last_asked >= self.interval:
            user = self._prompt(gs)
            self._req.put_nowait((int(gs.frame), user))
            self.inflight, self.last_asked = True, int(gs.frame)

    def _prompt(self, gs: melee.GameState) -> str:
        events = self.tracker.drain()
        if self.history:
            self.history[-1]["events"] = events or "nothing notable"
        text = render(observe(gs, self.port, self.opponent_port), events)
        past = [f"f{h['frame']} set {h['cmd']} → then: {h.get('events', 'running')}" for h in self.history[-self.history_len:]]
        if past:
            text += "\nYOUR RECENT COMMANDS:\n" + "\n".join(past)
        return text + f"\nCURRENT COMMAND: {self.current}\nChoose."

    # ------------------------------------------------------------------ coach thread

    def _worker(self) -> None:
        while not self._stop.is_set():
            try:
                job = self._req.get(timeout=.2)
            except queue.Empty:
                continue
            self._res.put((job, self._decide(job[1])))

    def _decide(self, user: str) -> tuple[dict, Reply | None]:
        if self.random:
            if self.kind == "reyn":
                return {"command": self.rng.choice([*self.commands, "none"]), "why": "random"}, None
            return {"return_target": round(self.rng.uniform(-20, 140), 1),
                    "temperature": round(self.rng.uniform(.8, 1.1), 2), "why": "random"}, None
        rep = self.llm.choose(self.system, user, self.tool)
        return (rep.args or {}), rep

    def _apply(self, decision: dict, frame: int, rep: Reply | None, user: str, asked: int | None = None) -> None:
        why, error = str(decision.get("why", ""))[:300], rep.error if rep else ""
        if self.kind == "reyn":
            cid = str(decision.get("command", "keep")).strip()
            if cid not in self.commands and cid not in ("keep", "none"):
                error = error or f"invalid command id {cid!r}"
                cid = "keep"
            new = self.current if cid == "keep" else cid
            changed = new != self.current
            if changed:
                self.body.steer["command"] = self.commands[new].phrase if new != "none" else None
            self.current = new
            shown = new
        else:
            knobs = {}
            if "return_target" in decision:
                rt = decision["return_target"]
                knobs["return_target"] = None if rt is None else min(140.0, max(-20.0, float(rt)))
            if "temperature" in decision:
                knobs["temperature"] = min(1.1, max(0.8, float(decision["temperature"])))
            changed = any(self.body.steer.get(k) != v for k, v in knobs.items())
            self.body.steer.update(knobs)
            shown = f"return_target={self.body.steer.get('return_target')} temperature={self.body.steer.get('temperature')}"
            self.current = shown
        self.history.append({"frame": frame, "cmd": shown})
        rec = {"type": "decision", "frame": frame, "asked_frame": asked, "latency_frames": None if asked is None else frame - asked,
               "latency_s": round(rep.latency_s, 3) if rep else None, "state": user, "command": shown,
               "phrase": self.body.steer.get("command") if self.kind == "reyn" else None, "changed": changed,
               "why": why, "error": error, "raw": rep.text[:400] if rep and error else "",
               "prompt_tokens": rep.prompt_tokens if rep else 0, "completion_tokens": rep.completion_tokens if rep else 0}
        self.records.append(rec)
        if changed and self.kind == "reyn":
            self.pending_log = rec  # written next frame, with the router's reply
        else:
            self.log.write(rec)
