"""Shared brain for the LLM players: prompt building, decision history, JSONL decision log, executor wiring."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import melee
from melee import Action as A

from melee_llm.actions import ACTIONS, Executor, action_help, tool_schema
from melee_llm.agents.base import Agent
from melee_llm.llm import LLM, Reply
from melee_llm.paths import REPLAYS
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

# Observation modes (`obs=` in the spec): text = the rendered state (default), image = screenshot + legend only,
# both = text and screenshot. Image modes need a rendered game; see melee_llm/vision.py and docs/perception.md.
OBS_MODES = ("text", "image", "both")
READ_TEXT = """How to read the state: "ACTIVE" = the attack hitbox is out now; "startup"/"endlag" = vulnerable windows to punish;
"busy" = cannot act yet; "hitstun" = combo them; "OFFSTAGE" = edgeguard them (or recover yourself)."""
READ_IMAGE = """You see screenshots of the game, not numbers: judge spacing, who is airborne or offstage, attack animations,
damage % and stocks from the picture. The camera zooms to fit both fighters, so judge distance against character size
(a fighter is about 15 units tall)."""
READ_BOTH = READ_TEXT + "\nYou also get a screenshot of the current frame; the text state is exact, the picture shows the scene."
COSTUMES = {melee.Character.FOX: {0: "default: white jacket, green trousers", 1: "orange"}}  # PlayerState.costume, as seen in screenshots


def parse_spec(arg: str | None) -> dict:
    """Spec text after the colon, "model[,key=value...]" → constructor kwargs."""
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
    """One JSONL per game, next to the .slp: <replay>.p<port>.<suffix>.jsonl.

    If the replay is known up front, write there directly; otherwise write to a temp name in `directory`
    and rename on close to the newest .slp under it (Slippi writes into a dated subfolder).
    """

    def __init__(self, directory: Path, tag: str, replay: Path | None = None, port: int = 0, suffix: str = "llm"):
        directory.mkdir(parents=True, exist_ok=True)
        self.dir, self.t0, self.suffix, self.fixed = directory, time.time(), suffix, replay is not None
        self.path = (replay.with_suffix(f".p{port}.{suffix}.jsonl") if replay
                     else directory / f"{suffix}-{time.strftime('%Y%m%dT%H%M%S')}-{tag}.jsonl")
        self.f = self.path.open("a")

    def write(self, rec: dict) -> None:
        rec = {**rec, "ts": round(time.time(), 3)}  # wall clock: lets the web UI line decisions up with the video
        self.f.write(json.dumps(rec, default=lambda o: o.item() if hasattr(o, "item") else str(o)) + "\n")
        self.f.flush()

    def media_dir(self) -> Path:
        """Images sent with the decisions: <log>.jsonl → <log>.frames/ (moved along when the log is renamed)."""
        return self.path.with_suffix(".frames")

    def close(self, port: int) -> Path:
        self.f.close()
        if self.fixed:
            return self.path
        slps = [p for p in self.dir.rglob("*.slp") if p.stat().st_mtime >= self.t0 - 5]
        if slps:
            target = max(slps, key=lambda p: p.stat().st_mtime).with_suffix(f".p{port}.{self.suffix}.jsonl")
            media = self.media_dir()
            self.path = self.path.rename(target)
            if media.is_dir():
                media.rename(self.media_dir())
        return self.path


class LLMAgent(Agent):
    kind = "llm"

    def __init__(self, model: str = "claude-haiku-4-5-20251001", interval: int = 30, history: int = 6,
                 mode: str = "json", effort: str | None = "none", base_url: str | None = None, timeout: float = 20.0,
                 reflexes: bool = True, obs: str = "text", clip: int = 1, clip_every: int = 5, img_width: int = 512,
                 img_quality: int = 80, log_dir: Path | None = None, system_extra: str = "", **_):
        super().__init__()
        self.model, self.interval, self.history_len = model, interval, history
        self.llm = LLM(model, base_url=base_url, timeout=timeout, mode=mode, effort=effort)
        self.tool = tool_schema()
        self.reflexes, self.system_extra = reflexes, system_extra
        self.log_dir = Path(log_dir) if log_dir else REPLAYS
        self.log: DecisionLog | None = None
        self.history: list[dict] = []
        self.stats: list[dict] = []
        self.dropped: list[dict] = []  # replies never applied (LiveLLM: stale, superseded, game end)
        assert obs in OBS_MODES, f"obs must be one of {OBS_MODES}"
        self.obs_mode, self.clip, self.clip_every = obs, max(1, int(clip)), max(1, int(clip_every))
        self.img_width, self.img_quality = img_width, img_quality
        self.camera = None
        self.next_images: list[str] | None = None  # data URIs for the next think() (keeps think(user) overridable)

    @property
    def name(self) -> str:
        return f"{self.kind}:{self.model}"

    def setup(self, controller, port, opponent_port):
        super().setup(controller, port, opponent_port)
        self.ex = Executor(controller, port, opponent_port, self.reflexes)
        self.tracker = EventTracker(port, opponent_port)
        framedata()  # 0.5 s CSV load; keep it out of the first live frame
        if self.obs_mode != "text":
            from melee_llm.vision import Camera
            self.camera = Camera(os.environ.get("DISPLAY"), self.img_width, self.img_quality)  # Dolphin's display

    # ------------------------------------------------------------ per-frame helpers

    def begin_frame(self, gs: melee.GameState) -> None:
        if self.log is None:
            self._start_game(gs)
        self.tracker.update(gs)

    def _start_game(self, gs: melee.GameState) -> None:
        self.log = DecisionLog(self.log_dir, f"p{self.port}-{self.kind}")
        self.history, self.stats, self.dropped = [], [], []
        me, op = gs.players[self.port], gs.players[self.opponent_port]
        self.system = SYSTEM.format(me=me.character.name, opp=op.character.name, stage=stage_text(gs.stage),
                                    tips=TIPS.get(me.character, "") + self.system_extra, actions=action_help())
        if self.obs_mode != "text":
            self.system = self.system.replace(READ_TEXT, READ_IMAGE if self.obs_mode == "image" else READ_BOTH)
        self.log.write({"type": "game_start", "agent": self.kind, "model": self.model, "port": self.port,
                        "character": me.character.name, "opponent": op.character.name, "stage": gs.stage.name,
                        "interval": self.interval, "mode": self.llm.mode, "effort": self.llm.effort,
                        "obs_mode": self.obs_mode, "clip": self.clip, "system_prompt": self.system})

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
        image_only = self.obs_mode == "image"  # the model's own decisions and macro outcomes, but no game state
        past = [f"f{h['frame']} {h['desc']} → {h.get('outcome', '?')}" +
                (f" | {h['events']}" if h.get("events") and not image_only else "")
                for h in self.history[-self.history_len:-1]]
        if self.history:
            h = self.history[-1]
            past.append(f"f{h['frame']} {h['desc']} → {h.get('outcome', '?')}")
        user = self.legend(gs) if image_only else render(obs, events)
        if past:
            user += "\nRECENT DECISIONS:\n" + "\n".join(past)
        if self.ex.cur:
            user += f"\nNOW RUNNING: {self.ex.cur.name} ({self.ex.cur.frames}f)"
        return obs, user + "\nChoose the next action."

    def legend(self, gs: melee.GameState) -> str:
        """What an image-only player is told besides the picture: who is who, and how many frames it gets."""
        def who(port: int) -> str:
            ps = gs.players[port]
            look = COSTUMES.get(ps.character, {}).get(int(ps.costume))
            return f"P{port} {ps.character.name}" + (f" ({look} costume)" if look else "")
        hud = "left" if self.port < self.opponent_port else "right"
        s = (f"SCREENSHOT LEGEND: you are {who(self.port)}; the opponent is {who(self.opponent_port)}. The bottom HUD shows "
             f"each port's damage % with stock icons above it, P1 leftmost: yours is the {hud} one. The timer is at the top.")
        if self.clip > 1:
            s += (f" The images are the last {self.clip} frames, oldest first, {self.clip_every} frames "
                  f"({self.clip_every * 1000 // 60} ms) apart; the last one is now.")
        return s + f"\nGame frame {int(gs.frame)}."

    def capture(self, frame: int) -> list:
        """Screenshots (vision.Shot, oldest first) for the decision being asked at `frame`; [] in text mode."""
        if not self.camera:
            return []
        return self.camera.clip(frame, self.clip, self.clip_every)

    def think(self, user: str, images: list[str] | None = None) -> Reply:
        images = images if images is not None else self.next_images
        self.next_images = None
        return self.llm.choose(self.system, user, self.tool, images=images or None)

    def _save_shots(self, shots: list, asked_frame: int) -> dict:
        """Write the exact JPEGs sent next to the log: <log stem>.frames/f<asked>_<grabbed>.jpg (docs/perception.md)."""
        if not shots:
            return {"images": [], "image_error": "no screenshot (window not found)"} if self.camera else {}
        media = self.log.media_dir()
        media.mkdir(exist_ok=True)
        out = []
        for s in shots:
            name = f"f{asked_frame}_{s.frame}.jpg"
            (media / name).write_bytes(s.jpeg)
            out.append({"file": name, "frame": s.frame, "w": s.size[0], "h": s.size[1], "bytes": len(s.jpeg)})
        return {"images": out, "image_tokens_est": sum(s.claude_tokens() for s in shots),
                "capture_ms": round(sum(s.grab_ms + s.encode_ms for s in shots), 1)}

    def apply(self, gs: melee.GameState, obs: dict, user: str, rep: Reply, asked_frame: int, **extra) -> None:
        extra.update(self._save_shots(extra.pop("shots", None) or [], asked_frame))
        invalid = not rep.args or rep.args.get("action") not in ACTIONS
        decision = rep.args if rep.args and rep.args.get("action") else {"action": "dash_dance", "frames": 20}
        name = self.ex.start(decision)
        desc = name + "(" + ",".join(f"{v}" for k, v in decision.items() if k not in ("action", "reason")) + ")"
        self.history.append({"frame": int(gs.frame), "desc": desc})
        rec = {"type": "decision", "frame": int(gs.frame), "asked_frame": asked_frame, "model": rep.model,
               "obs_text": user, "obs": obs, "decision": decision, "action": name,
               "reason": (rep.args or {}).get("reason", ""), "latency_s": round(rep.latency_s, 3),
               "prompt_tokens": rep.prompt_tokens, "completion_tokens": rep.completion_tokens,
               "reply_mode": rep.mode, "error": rep.error, "raw": rep.text[:600] if rep.error else "", "invalid": invalid,
               **extra}
        self.stats.append(rec)
        self.log.write(rec)

    def _before_end(self) -> None:
        """Hook: last records before game_end (LiveLLM has logged any reply still in flight by then)."""

    def on_game_end(self, gs):
        if self.log is None:
            return
        self._before_end()
        lat = [s["latency_s"] for s in self.stats]
        summary = {"type": "game_end", "frame": int(gs.frame) if gs else None, "decisions": len(lat),
                   "errors": sum(bool(s["error"]) for s in self.stats),
                   "invalid": sum(bool(s.get("invalid")) for s in self.stats), "obs_mode": self.obs_mode,
                   "mean_latency_s": round(sum(lat) / len(lat), 3) if lat else None,
                   "prompt_tokens": sum(s["prompt_tokens"] for s in self.stats),
                   "completion_tokens": sum(s["completion_tokens"] for s in self.stats)}
        if self.dropped:  # their tokens are spent too; prompt/completion above are the applied replies only
            summary |= {"dropped": len(self.dropped),
                        "dropped_prompt_tokens": sum(d["prompt_tokens"] for d in self.dropped),
                        "dropped_completion_tokens": sum(d["completion_tokens"] for d in self.dropped)}
        for k in ("latency_frames", "stale_frames", "capture_ms", "image_tokens_est"):
            v = [s[k] for s in self.stats if k in s]
            if v:
                summary[f"mean_{k}"] = round(sum(v) / len(v), 1)
        self.log.write(summary)
        self.log.close(self.port)
        self.log = None
