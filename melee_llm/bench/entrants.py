"""Who is on the bench: one registry of every kind of player, with its track, run spec and a one-line description.

Ids are what the board shows and what results store. `spec` is what the game runner builds (melee_llm/players.py specs). `aliases` are the spellings older result files used, for imports.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

from melee_llm.paths import BOTWRITER, ROOT

CATEGORIES = {
    "cpu": "CPU", "learned": "Learned bot", "scripted": "Scripted bot", "written": "LLM-written bot",
    "llm": "LLM player", "jev": "Jev player", "coach": "Coach → Reyn", "human": "Human",
}
TRACKS = {"realtime": "Real time", "untimed": "Untimed", "both": "Both tracks"}
WALL_CLOCK = {"llm_live", "jev_live", "coach", "coach_jev"}  # decide off-thread: need a 60 fps game
LLM_MODELS = {  # id → (short name, provider)
    "claude-haiku-4-5-20251001": ("Haiku 4.5", "claude"),
    "claude-sonnet-5-5": ("Sonnet 5.5", "claude"),
    "gpt-6-luna": ("GPT-6 Luna", "gpt"),
    "gpt-6.1-sol": ("GPT-6.1 Sol", "gpt"),
}
COACH_INTERVAL = 300  # frames between coach calls (5 s), as in the coach and Jev pilots


@dataclass
class Entrant:
    id: str
    label: str
    category: str
    track: str  # realtime | untimed | both (token-free players whose games count on both boards)
    spec: str | None  # None: cannot be scheduled (imports only, or a human)
    about: str
    provider: str = "none"  # claude | gpt | jev | none: who pays for its decisions
    active: bool = True  # the scheduler may pick it
    gpu: bool = False  # runs a CUDA bot process
    aliases: list[str] = field(default_factory=list)

    @property
    def kind(self) -> str:
        return (self.spec or self.id).partition(":")[0]

    @property
    def wall_clock(self) -> bool:
        return self.kind in WALL_CLOCK

    def view(self) -> dict:
        return {**asdict(self), "category_label": CATEGORIES[self.category], "track_label": TRACKS[self.track],
                "wall_clock": self.wall_clock}


def _written() -> list[Entrant]:
    """Final bots of bot-writer sessions (real runs; the 3-minute smoke sessions are left out)."""
    out = []
    for meta in sorted((BOTWRITER / "sessions").glob("*/meta.json")):
        try:
            m = json.loads(meta.read_text())
        except (OSError, ValueError):
            continue
        bot = meta.parent / "final/bot.py"
        if not bot.exists() or m.get("name", "").startswith("smoke") or (m.get("minutes") or 0) < 10:
            continue
        name = m["name"]
        out.append(Entrant(
            f"written:{name}", f"{name} bot", "written", "both", f"bot:{bot}",
            f"Single-file Python bot written by {m.get('model')} ({m.get('harness')} harness) in {m.get('minutes'):.0f} min "
            f"of wall time; runs with a 16 ms per-frame budget.", aliases=[name, str(bot)]))
    return out


def registry() -> list[Entrant]:
    e: list[Entrant] = []
    for lvl in range(1, 10):
        e.append(Entrant(f"cpu:{lvl}", f"CPU {lvl}", "cpu", "both", f"cpu:{lvl}",
                         f"Melee's built-in level-{lvl} CPU." + (" The anchor: pinned at 1500." if lvl == 9 else ""),
                         active=lvl % 2 == 1, aliases=[f"cpu{lvl}"]))
    tiers = {"silver": "silver", "plat": "platinum", "gm": "grandmaster"}
    for t, name in tiers.items():
        e.append(Entrant(f"phillip:{t}", f"Phillip {t}", "learned", "both", f"phillip:{t}",
                         f"slippi-ai (vladfi1) imitation + RL policy, {name} tier; 18-24 frame built-in reaction delay.",
                         gpu=True, aliases=["agent:melee_llm.bots:Phillip:gm"] if t == "gm" else []))
    e += [
        Entrant("hal:MASTER", "HAL master", "learned", "both", "hal:MASTER",
                "HAL: 250M transformer imitating human replays, conditioned on the master rank.", gpu=True,
                aliases=["agent:melee_llm.bots:HAL:MASTER", "hal"]),
        Entrant("mimic", "MIMIC fox", "learned", "both", "mimic",
                "MIMIC: 20M transformer behaviour clone, Fox checkpoint.", gpu=True,
                aliases=["agent:melee_llm.bots:MIMIC", "mimic:fox"]),
        Entrant("faynt", "Faynt 10M", "learned", "both", "faynt",
                "Faynt 10M-Arena: transformer policy RL-tuned on Fox (runs on the CPU).",
                aliases=["agent:melee_llm.bots:Faynt", "faynt:10M-Arena"]),
        Entrant("reyn", "Reyn", "learned", "both", "reyn",
                "Reyn-26C: language-steerable 33M policy, here with no command. The body every coach steers.", gpu=True),
    ]
    for b, what in (("laser", "short-hop lasers from range"), ("rusher", "runs in and attacks"),
                    ("shine", "approaches and shines")):
        e.append(Entrant(f"baseline:{b}", f"Script {b}", "scripted", "both", f"baseline:{b}",
                         f"Hand-written bot-writer baseline: {what}.",
                         aliases=[f"baseline/{b}", str(ROOT / f"melee_llm/botwriter/baselines/{b}.py")]))
    e += _written()
    for m, (short, prov) in LLM_MODELS.items():
        e.append(Entrant(f"llm_live:{m}", f"{short} live", "llm", "realtime", f"llm_live:{m}",
                         f"{short} picks macro-actions from text state while the game runs at 60 fps; "
                         f"it acts on states about a second old.", provider=prov))
        e.append(Entrant(f"llm_paused:{m}", f"{short} paused", "llm", "untimed", f"llm_paused:{m}",
                         f"{short} picks macro-actions from text state; the game waits for every decision.",
                         provider=prov))
        e.append(Entrant(f"coach:{m}", f"{short} coach", "coach", "realtime", f"coach:{m},interval={COACH_INTERVAL}",
                         f"{short} picks one of Reyn's ~100 commands every 5 s while Reyn plays every frame.",
                         provider=prov, gpu=True))
    e += [
        Entrant("jev_live", "Jev live", "jev", "realtime", "jev_live",
                "TypeSafe Jev (System One) picks macros at 60 fps, ~150 ms per decision.", provider="jev"),
        Entrant("jev_paused", "Jev paused", "jev", "untimed", "jev_paused",
                "TypeSafe Jev picks macros; the game waits for every decision.", provider="jev"),
        Entrant("coach_jev", "Jev coach", "coach", "realtime", f"coach_jev:,interval={COACH_INTERVAL}",
                "Jev picks Reyn's command every 5 s.", provider="jev", gpu=True),
        Entrant("coach:random", "Random coach", "coach", "realtime", f"coach:random,interval={COACH_INTERVAL}",
                "Control: a uniformly random Reyn command every 5 s, no model.", gpu=True),
        Entrant("human:mateo", "Mateo", "human", "realtime", None,
                "Mateo over Slippi netplay (docs/netplay.md). Slot reserved; no games yet.", active=False),
    ]
    e += ablations()
    return e


JEV_TOP6 = "stock_protection|edgeguard_from_the_stage|defensive_play|left_side_move_there|landing_punish|right_side_move_there"


def ablations() -> list[Entrant]:
    """Coach deep-dive variants (docs/coach-deepdive.md). Inactive: run with `bench run --only ...`."""
    i = f"interval={COACH_INTERVAL}"
    rows = [
        ("coach:random,fixed", "Random coach, one command", f"coach:random,{i},p_change=0", "none",
         "One random command, set at the start and held all game."),
        ("coach:random,sticky", "Random coach, sticky", f"coach:random,{i},p_change=0.25", "none",
         "A random command, changed on a quarter of the calls (Jev's effective change rate)."),
        ("coach:random,jev6", "Random coach, Jev's top 6", f"coach:random,{i},menu={JEV_TOP6}", "none",
         "A random pick every 5 s among the six commands Jev holds most (or none)."),
        ("coach_jev,interval=60", "Jev coach, 1 s", "coach_jev:,interval=60", "jev", "Jev picks every second."),
        ("coach_jev,interval=900", "Jev coach, 15 s", "coach_jev:,interval=900", "jev", "Jev picks every 15 s."),
        ("coach_jev,features", "Jev coach + features", f"coach_jev:,{i},features=1", "jev",
         "Jev every 5 s, with named features computed in code (distance, states, percent bands, last window)."),
        ("coach:claude-haiku-4-5-20251001,features", "Haiku coach + features",
         f"coach:claude-haiku-4-5-20251001,{i},features=1", "claude", "Haiku every 5 s, with the same named features."),
    ]
    out = [Entrant(eid, label, "coach", "realtime", spec, about, provider=prov, active=False, gpu=True)
           for eid, label, spec, prov, about in rows]
    out.append(Entrant("reyn:stock_protection", "Reyn, fixed \"Don't die.\"", "learned", "both", "reyn:Don't die.",
                       "Reyn holding Jev's favourite command all game, no coach.", active=False, gpu=True))
    return out


def by_id() -> dict[str, Entrant]:
    return {x.id: x for x in registry()}


def tracks_of(e: Entrant) -> tuple[str, ...]:
    return ("realtime", "untimed") if e.track == "both" else (e.track,)


def game_track(a: Entrant, b: Entrant) -> str | None:
    """realtime | untimed | shared (counts on both boards) | None (the two never meet)."""
    if a.track == "both" and b.track == "both":
        return "shared"
    tracks = set(tracks_of(a)) & set(tracks_of(b))
    return next(iter(tracks)) if tracks else None


def game_mode(a: Entrant, b: Entrant) -> str:
    """realtime (headless, 60 fps cap) when a player decides on the wall clock; else fast (the game waits)."""
    return "realtime" if a.wall_clock or b.wall_clock else "fast"


def resolve(name: str, entrants: dict[str, Entrant] | None = None) -> str | None:
    """Entrant id for a spec or player name found in an older results file (None: not a bench entrant)."""
    entrants = entrants or by_id()
    if name in entrants:
        return name
    for e in entrants.values():
        if name in e.aliases:
            return e.id
    kind, _, arg = name.partition(":")
    head, *opts = arg.split(",")
    if kind in ("coach", "coach_jev"):
        if any(o.startswith(("body=", "body_arg=")) and o not in ("body=reyn",) for o in opts):
            return None
        if f"interval={COACH_INTERVAL}" not in opts or set(opts) - {f"interval={COACH_INTERVAL}", "body=reyn"}:
            return None
        model = {"haiku": "claude-haiku-4-5-20251001", "sonnet": "claude-sonnet-5-5"}.get(head, head)
        return "coach_jev" if kind == "coach_jev" else (f"coach:{model}" if f"coach:{model}" in entrants else None)
    if kind in ("jev_live", "jev_paused") and head in ("", "jev-latest") and not opts:
        return kind
    if kind in ("llm_live", "llm_paused") and not opts and name in entrants:
        return name
    return None

