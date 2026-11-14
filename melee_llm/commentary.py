"""Live commentary for the live slot: a play-by-play ticker from game state, plus optional LLM colour lines.

`PlayTracker` turns frames into events (combo strings, stocks, offstage hits, shield breaks). `Commentary`
writes the notable ones to a JSONL the Live page tails (kind "commentary"; matches.MatchPublisher starts one per
game of the live-slot match and lists it in the registry's logs), and, while the `commentator`
setting is on, a background thread turns recent events into a short exchange between two casters (CASTERS):
one LLM call writes both parts. Nothing here
blocks the game loop: update() is a few comparisons per frame and the LLM call runs on its own thread.

While someone on the Live page has the voice on (it sends a heartbeat that touches paths.VOICE_HEARTBEAT), each line
is also spoken with ElevenLabs in its caster's voice and saved as <log>.audio/<n>.mp3; ELEVENLABS_API_KEY comes from the environment or
~/.config/melee-llm/elevenlabs.env. Nobody listening, nothing is synthesized.

Records: {"type": "event", "text", "frame", "big", "ts"} and {"type": "line", "text", "frame", "model",
"speaker", "latency_s", "audio", "audio_s", "ts"} (speaker: the caster's name; audio: path of the MP3, audio_s: its length). `ts` is when the moment happened (a line carries the ts of the newest event it covers),
so the page shows both when the video reaches that moment.
"""
from __future__ import annotations

import json
import os
import queue
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

import melee
from melee import Action as A

from melee_llm.state import DAMAGED, actionable, in_hitstun

FPS = 60
STRING_END = 30  # frames the victim must be actionable (and not hit) before a combo string counts as over
SELF_DESTRUCT = 240  # a stock lost this long after the last hit taken is a self-destruct
DEFAULT_MODEL = "claude-haiku-5-5"
# The booth: name → (ElevenLabs voice id, what the LLM is told about them). The first is the play-by-play caster.
CASTERS = {
    "Charlie": ("IKne3meq5aSn9XLyUdCD", "play-by-play: loud, fast, loses his mind on big moments"),
    "Laura": ("FGY2WhTYpPnrIDTdsKH5", "colour analyst: quick, dry wit, reads momentum and habits, teases Charlie"),
}
TTS_MODEL = "eleven_v4_turbo"  # emotive and fast (~1.3 s for a line); takes [audio tags] such as [shouting]
TAG = re.compile(r"\s*\[[^\]\n]{1,30}\]\s*")  # an audio tag: spoken with, never shown
TTS_KBPS = 64  # mp3_44100_64: duration = bytes * 8 / 64000
VOICE_FRESH_S = 15  # the Live page beats every 5 s while its voice is on
ELEVENLABS_ENV = Path.home() / ".config/melee-llm/elevenlabs.env"


@dataclass
class Event:
    frame: int
    text: str
    big: bool = False  # shown in the ticker (small ones only feed the LLM)
    ts: float = field(default_factory=time.time)


@dataclass
class _String:
    """Hits on one victim without them getting free in between."""
    attacker: int
    start_pct: float
    hits: int = 0
    damage: float = 0.0
    free_frames: int = 0


class PlayTracker:
    def __init__(self, names: dict[int, str]):
        self.names = names  # port → "Faynt (Marth)"
        self.prev: dict[int, tuple] = {}
        self.strings: dict[int, _String] = {}  # victim port → current string
        self.last_hit: dict[int, int] = {}  # victim port → frame of the last hit taken
        self.last_stock_called = False

    def update(self, gs: melee.GameState) -> list[Event]:
        out: list[Event] = []
        f = int(gs.frame)
        ports = [p for p in self.names if p in gs.players]
        for p in ports:
            ps, opp = gs.players[p], next((q for q in ports if q != p), None)
            name = self.names[p]
            cur = (float(ps.percent), int(ps.stock), ps.action, bool(ps.off_stage))
            if p not in self.prev:
                self.prev[p] = cur
                continue
            pct, stock, act, off = self.prev[p]
            s = self.strings.get(p)
            if cur[1] < stock:
                out.append(self._stock_lost(p, opp, f, pct, cur[1], s))
                self.strings.pop(p, None)
            elif cur[0] > pct + 0.5 and opp is not None:
                if s is None:
                    s = self.strings[p] = _String(opp, pct)
                s.hits, s.damage, s.free_frames = s.hits + 1, s.damage + cur[0] - pct, 0
                self.last_hit[p] = f
            elif s is not None:
                s.free_frames = s.free_frames + 1 if actionable(ps) and not in_hitstun(ps) else 0
                if s.free_frames >= STRING_END:
                    if s.hits >= 3 or s.damage >= 35:
                        out.append(Event(f, f"{self.names[s.attacker]}: {s.hits}-hit string, {s.damage:.0f}% on {name}", big=True))
                    elif s.hits:
                        out.append(Event(f, f"{self.names[s.attacker]} hits {name}"))
                    self.strings.pop(p, None)
            if ps.action != act:
                a = ps.action
                if a == A.SHIELD_BREAK_FLY:
                    out.append(Event(f, f"{name}'s shield breaks!", big=True))
                elif a in (A.TECH_MISS_UP, A.TECH_MISS_DOWN):
                    out.append(Event(f, f"{name} misses the tech"))
                elif a == A.EDGE_CATCHING and off:
                    out.append(Event(f, f"{name} grabs the ledge"))
            if cur[3] and not off and ps.action in DAMAGED:
                out.append(Event(f, f"{name} knocked offstage at {cur[0]:.0f}%", big=cur[0] >= 60))
            self.prev[p] = cur
        if (not self.last_stock_called and len(ports) == 2
                and all(int(gs.players[p].stock) == 1 for p in ports) and all(self.prev[p][1] == 1 for p in ports)):
            self.last_stock_called = True
            out.append(Event(f, "Last stock each!", big=True))
        return out

    def _stock_lost(self, p: int, opp: int | None, f: int, pct: float, left: int, s: _String | None) -> Event:
        name, tail = self.names[p], "" if left else " (that's the game)"
        if f - self.last_hit.get(p, -10**9) > SELF_DESTRUCT or opp is None:
            return Event(f, f"{name} self-destructs at {pct:.0f}%{tail}", big=True)
        killer = self.names[opp]
        if s and s.start_pct < 5 and s.hits >= 3:
            return Event(f, f"Zero-to-death! {killer} KOs {name} with a {s.hits}-hit string{tail}", big=True)
        return Event(f, f"{killer} KOs {name} at {pct:.0f}%{tail}", big=True)


def commentator_enabled() -> bool:
    from melee_llm.web import jobs  # the web package's settings table; imported lazily (live slot only)
    try:
        return jobs.setting("commentator", "off") == "on"
    except Exception:
        return False


def commentator_model() -> str:
    from melee_llm.web import jobs
    try:
        return jobs.setting("commentator_model", DEFAULT_MODEL) or DEFAULT_MODEL
    except Exception:
        return DEFAULT_MODEL


def someone_listening() -> bool:
    from melee_llm.paths import VOICE_HEARTBEAT
    try:
        return time.time() - VOICE_HEARTBEAT.stat().st_mtime < VOICE_FRESH_S
    except OSError:
        return False


def elevenlabs_key() -> str | None:
    if os.environ.get("ELEVENLABS_API_KEY"):
        return os.environ["ELEVENLABS_API_KEY"]
    try:
        for line in ELEVENLABS_ENV.read_text().splitlines():
            k, _, v = line.partition("=")
            if k.strip() == "ELEVENLABS_API_KEY":
                return v.strip().strip("'\"")
    except OSError:
        pass
    return None


def speak(text: str, key: str, voice: str, timeout: float = 8.0) -> bytes:
    """One line as MP3 (ElevenLabs text-to-speech). Raises on HTTP errors."""
    import httpx
    r = httpx.post(f"https://api.elevenlabs.io/v1/text-to-speech/{voice}", params={"output_format": "mp3_44100_64"},
                   headers={"xi-api-key": key}, json={"text": text, "model_id": TTS_MODEL}, timeout=timeout)
    r.raise_for_status()
    return r.content


def _clock(frame: int) -> str:
    secs = max(0, frame) // FPS
    return f"{secs // 60}:{secs % 60:02d}"


def head_to_head(spec1: str | None, spec2: str | None) -> str:
    """Their record in earlier learned-bot arena games, for the booth's storylines ("" if they never met there)."""
    from melee_llm.paths import ARENA
    from melee_llm.util import read_jsonl
    if not spec1 or not spec2:
        return ""
    w1 = w2 = 0
    for r in read_jsonl(ARENA / "results.jsonl"):
        if {r.get("p1"), r.get("p2")} == {spec1, spec2} and r.get("winner") in (1, 2):
            won = r["p1"] if r["winner"] == 1 else r["p2"]
            w1, w2 = w1 + (won == spec1), w2 + (won == spec2)
    return f"; in earlier arena games the first player won {w1} and the second {w2}" if w1 + w2 else ""


SYSTEM = """You write the commentary booth for a live exhibition of Super Smash Bros. Melee where AI bots play \
each other. Two casters share the desk:
{casters}

Write what they say next about what just happened: one turn, or two when there is something to react to. Each turn is one short sentence of at most 16 words, the way people talk over a \
fast game. Small moments get one turn from one caster.

Sound like a real tournament broadcast:
- React, don't report. The viewers see the percent and stock counters on screen, so do not read them out. Mention a \
number only when it is the story: a kill at an absurdly low or high percent, a last-stock situation, a comeback.
- Never summarise the score, never list stocks or percent for both players, and do not count the stocks left \
after a KO.
- Use short names: the bot ("Phillip") or the character ("Fox"), not both every time.
- Call the moment (the punish, the edgeguard, the escape, the momentum swing), then let the other caster add a \
reaction, a joke or what it means for the game. They may disagree, and say each other's name only now and then.
- Build storylines across the game: who is adapting, who looks rattled, what the favourite needs to do. In quiet \
stretches one caster fills with the matchup or the players, briefly.
- Stay accurate. In each event the first player named did it to the second: "A KOs B" means B lost the stock. \
Describe only what the events say: never invent moves, techniques, counts ("the third time") or habits, and \
if the events do not say how something happened, do not say how. With nothing new to call, talk about the matchup, \
the two bots or what is at stake, not about play you were not shown.
- Vary the phrasing: never reuse a sentence the booth already said, and do not open twice the same way."""
SPOKEN = """

These turns are read aloud live, so keep each to at most 14 words. Start a turn with one audio tag in square \
brackets when the delivery matters, such as [shouting], [excited], [gasps], [laughs], [groans], [deadpan] or \
[whispers]; save [shouting] for stocks and big punishes. Write no other brackets."""

TOOL = {"type": "function", "function": {
    "name": "say", "description": "The casters' next turns on stream, in order.",
    "parameters": {"type": "object", "required": ["turns"], "properties": {"turns": {
        "type": "array", "minItems": 1, "maxItems": 2, "items": {
            "type": "object", "required": ["speaker", "line"],
            "properties": {"speaker": {"type": "string", "enum": list(CASTERS)}, "line": {"type": "string"}}}}}}}}


def turns_of(args: dict | None) -> list[tuple[str, str]]:
    """(caster, line) pairs from the model's reply; an unknown speaker becomes the play-by-play caster."""
    out = []
    for t in (args or {}).get("turns") or []:
        if isinstance(t, dict) and str(t.get("line") or "").strip():
            who = t.get("speaker") if t.get("speaker") in CASTERS else next(iter(CASTERS))
            out.append((who, str(t["line"]).strip()))
    return out[:2]


def for_match(status: dict, replay) -> "Commentary":
    """A Commentary for the game that just started, from a matches.MatchPublisher status."""
    from melee_llm.paths import DATA
    from melee_llm.web.specs import char_name, kind_of, label, stage_name

    s, elo = status, status.get("elo") or {}
    players = {}
    for p, v in s["players"].items():
        spec = v.get("spec")
        who = label(spec) if spec else f"CPU {v['cpu_level']}" if v.get("cpu_level") else v.get("name") or f"P{p}"
        kind = kind_of(spec) if spec else "cpu" if v.get("cpu_level") else "player"
        players[int(p)] = (who, kind, char_name(v.get("character") or ""))
    names = {p: f"{who} ({char})" for p, (who, _, char) in players.items()}  # unambiguous in "A KOs B"
    vs = " vs ".join(f"{who} ({kind}, {char}{f', {elo[str(p)]} Elo' if str(p) in elo else ''})"
                     for p, (who, kind, char) in sorted(players.items()))
    games = f", game {s['game'] + 1} of {s['games']}" if s.get("games", 1) > 1 else ""
    stage = stage_name(s.get("stage") or "")
    path = (Path(replay).with_suffix(".p0.commentary.jsonl") if replay
            else DATA / "commentary" / f"{time.strftime('%Y%m%dT%H%M%S')}.jsonl")
    specs = [s["players"][p].get("spec") for p in sorted(s["players"])]
    c = Commentary(path, names, f"{vs} on {stage}, {s.get('label') or s.get('source')}{games}{head_to_head(*specs[:2])}")
    c.start(stage)
    return c


class Commentary:
    """One game's commentary: ticker events always, LLM lines while the `commentator` setting is on."""

    def __init__(self, path: Path, names: dict[int, str], context: str, min_gap: float = 4.0, quiet_gap: float = 10.0):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path, self.context = path, context
        self.audio_dir = path.with_suffix(".audio")
        self.f = path.open("a")
        self.lock = threading.Lock()
        self.tracker = PlayTracker(names)
        self.names = names
        self.min_gap, self.quiet_gap = min_gap, quiet_gap
        self.inbox: queue.Queue = queue.Queue()
        self.score = ""
        self.stop_ev = threading.Event()
        self.clips = 0
        self.thread = threading.Thread(target=self._run, daemon=True, name="commentator")
        self.thread.start()

    def write(self, rec: dict) -> None:
        with self.lock:
            if not self.f.closed:
                self.f.write(json.dumps(rec) + "\n")
                self.f.flush()

    def start(self, stage: str) -> None:
        a, b = (self.names[p] for p in sorted(self.names))
        ev = Event(0, f"{a} vs {b} on {stage}. Go!", big=True)
        self.write({"type": "event", "text": ev.text, "frame": 0, "big": True, "ts": round(ev.ts, 3)})
        self.inbox.put(ev)

    def update(self, gs: melee.GameState) -> None:
        for ev in self.tracker.update(gs):
            if ev.big:
                self.write({"type": "event", "text": ev.text, "frame": ev.frame, "big": True, "ts": round(ev.ts, 3)})
            self.inbox.put(ev)
        if gs.frame % 30 == 0:
            parts = [f"{self.names[p]}: {int(ps.stock)} stocks, {float(ps.percent):.0f}%" for p, ps in gs.players.items() if p in self.names]
            secs = max(0, 8 * 60 - max(0, int(gs.frame)) // FPS)
            self.score = "; ".join(parts) + f"; {secs // 60}:{secs % 60:02d} left on the clock"

    def end(self, text: str | None = None) -> None:
        """Game over (or aborted): the thread says one last line about `text`, closes the file and exits."""
        if text and not self.stop_ev.is_set():
            ev = Event(-1, text, big=True)
            self.write({"type": "event", "text": text, "big": True, "ts": round(ev.ts, 3)})
            self.inbox.put(ev)
        self.stop_ev.set()

    def join(self, timeout: float = 12) -> None:
        self.thread.join(timeout)

    def _voice(self, turns: list[tuple[str, str]], key: str) -> list[dict]:
        """Synthesize every turn at once (each in its caster's voice); one dict of audio fields per turn, in order."""
        def one(who: str, line: str) -> dict:
            t0 = time.perf_counter()
            try:
                mp3 = speak(line, key, CASTERS[who][0])
            except Exception as e:  # noqa: BLE001 - the text line still goes out
                return {"tts_error": f"{type(e).__name__}: {e}"[:200]}
            with self.lock:
                self.clips += 1
                out = self.audio_dir / f"{self.clips:03d}.mp3"
            self.audio_dir.mkdir(exist_ok=True)
            out.write_bytes(mp3)
            return {"audio": str(out), "audio_s": round(len(mp3) * 8 / (TTS_KBPS * 1000), 2),
                    "tts_s": round(time.perf_counter() - t0, 2)}
        with ThreadPoolExecutor(len(turns)) as pool:
            return list(pool.map(lambda t: one(*t), turns))

    def _run(self) -> None:
        try:
            self._loop()
        finally:
            with self.lock:
                self.f.close()

    def _loop(self) -> None:
        llm, model, said, pending, earlier = None, "", [], [], []
        last_line, last_check, enabled, voice_key = 0.0, 0.0, False, None
        speaking_until = 0.0
        system = SYSTEM.format(casters="\n".join(f"- {name}, {role}" for name, (_, role) in CASTERS.items()))
        while True:
            try:
                pending.append(self.inbox.get(timeout=0.25))
                continue  # drain everything queued before deciding
            except queue.Empty:
                pass
            now = time.time()
            if now - last_check > 3:
                last_check, enabled = now, commentator_enabled()
                if enabled and llm is None:
                    from melee_llm.llm import LLM
                    model = commentator_model()
                    llm = LLM(model, timeout=10, max_tokens=300)
                voice_key = elevenlabs_key() if enabled and someone_listening() else None
            finishing = self.stop_ev.is_set()
            if not enabled:
                pending.clear()
                if finishing:
                    return
                continue
            due = pending and (any(e.big for e in pending) and now - last_line >= self.min_gap or now - last_line >= self.quiet_gap)
            if voice_key and now < speaking_until:
                due = False  # don't talk over the clip that is still playing
            if finishing and pending:
                due = True
            if not due:
                if finishing:
                    return
                continue
            events, pending = pending, []
            user = (f"Match: {self.context}\n"
                    f"On-screen counters, for your orientation only: {self.score or 'game starting'}\n"
                    + ("Earlier this game (already called, for storylines only):\n" + "\n".join(f"- {t}" for t in earlier[-25:]) + "\n"
                       if earlier else "")
                    + "What just happened (oldest first):\n" + "\n".join(f"- {e.text}" for e in events[-20:])
                    + ("\nWhat the booth has said so far:\n" + "\n".join(f"- {s}" for s in said[-16:]) if said else ""))
            earlier += [f"{_clock(e.frame)} {e.text}" for e in events if e.big and e.frame > 0]
            rep = llm.choose(system + (SPOKEN if voice_key else ""), user, TOOL)
            turns = turns_of(rep.args)
            last_line = time.time()
            if turns:
                frame, ts = max(e.frame for e in events), round(max(e.ts for e in events), 3)
                audio = self._voice(turns, voice_key) if voice_key else [{}] * len(turns)
                for n, ((who, line), clip) in enumerate(zip(turns, audio)):
                    text = TAG.sub(" ", line).strip()
                    said.append(f"{who}: {text}")
                    rec = {"type": "line", "speaker": who, "text": text, "frame": frame, "model": rep.model, "ts": ts}
                    if n == 0:
                        rec |= {"latency_s": round(rep.latency_s, 2), "prompt_tokens": rep.prompt_tokens,
                                "completion_tokens": rep.completion_tokens}
                    self.write(rec | clip)
                speaking_until = time.time() + sum(c.get("audio_s", 0) for c in audio)
            elif rep.error:
                self.write({"type": "error", "text": rep.error[:200], "ts": round(time.time(), 3)})
            if finishing:
                return
