"""Two fighters on Final Destination in melee-sim-light, driven by raw inputs, plus a menu of moves any character can do.

A move is a function of (frame since it started, direction to the opponent, own slot) to one raw controller row
(buttons, main_x, main_y, c_x, c_y, r). The same menu works for every character: A and B moves differ per
character, the inputs don't (Fox's down-B is the shine, Sheik's neutral-B is needles).
"""
from __future__ import annotations

from typing import Callable

import melee

A, B, X, Z, R = 0x0100, 0x0200, 0x0400, 0x0010, 0x0020
Input = tuple[int, int, int, int, int, int]  # buttons, main_x, main_y, c_x, c_y, r
NONE: Input = (0, 0, 0, 0, 0, 0)
Move = Callable[[int, int, dict], Input]

# Grabbed, thrown or held: the hit that matters for a grab (percent does not change on the grab itself).
_CAUGHT = {a.value for a in melee.Action if a.name.startswith(("CAPTURE_", "THROWN_", "GRABBED"))
           or a.name in ("YOSHI_EGG", "KIRBY_STAR")}


def _first(inp: Input) -> Move:
    return lambda f, t, me: inp if f == 0 else NONE


def _hold(stick: int) -> Move:
    return lambda f, t, me: (0, stick * t, 0, 0, 0, 0)


def _tap(buttons: int, mx: int = 0, my: int = 0, cx: int = 0, cy: int = 0) -> Move:
    """Press once on frame 0; `mx` and `cx` are relative to the opponent (positive = toward)."""
    return lambda f, t, me: (buttons, mx * t, my, cx * t, cy, 0) if f == 0 else NONE


def _aerial(cx: int, cy: int) -> Move:
    """Short hop, then the C-stick aerial on every airborne frame until it comes out (extra presses are ignored)."""
    return lambda f, t, me: (X, 0, 0, 0, 0, 0) if f == 0 else (
        (0, 0, 0, cx * t, cy, 0) if not int(me["on_ground"]) and f < 30 else NONE)


def _dash(then: int, after: int) -> Move:
    """Dash toward the opponent and press `then` on frame `after`, stick still held (A in the first frames of a
    dash with the stick released comes out as nothing; measured)."""
    return lambda f, t, me: (0, 80 * t, 0, 0, 0, 0) if f < after else (
        (then, 80 * t, 0, 0, 0, 0) if f == after else NONE)


MOVES: dict[str, Move] = {
    "wait": lambda f, t, me: NONE,
    "crouch": lambda f, t, me: (0, 0, -80, 0, 0, 0),
    "in": _hold(80),
    "away": _hold(-80),
    "shield": lambda f, t, me: (R, 0, 0, 0, 0, 255),
    "spotdodge": lambda f, t, me: (R, 0, -80, 0, 0, 255) if f < 2 else NONE,
    "roll_away": lambda f, t, me: (R, 0, 0, 0, 0, 255) if f == 0 else ((R, -80 * t, 0, 0, 0, 255) if f < 3 else NONE),
    "hop": _first((X, 0, 0, 0, 0, 0)),
    "grab": _tap(Z),
    "jab": _tap(A),
    "ftilt": _tap(A, mx=50),
    "dtilt": _tap(A, my=-50),
    "utilt": _tap(A, my=50),
    "fsmash": _tap(0, cx=80),
    "dsmash": _tap(0, cy=-80),
    "usmash": _tap(0, cy=80),
    "nb": _tap(B),
    "nb_fire": lambda f, t, me: (B, 0, 0, 0, 0, 0) if f in (0, 20) else NONE,  # Samus/Mewtwo: start charging, fire
    "nb_hold": lambda f, t, me: (B, 0, 0, 0, 0, 0) if f < 40 else NONE,  # Link's bow, Din's Fire, PK Flash: hold, let go
    "side_b": _tap(B, mx=80),
    "down_b": _tap(B, my=-80),
    "up_b": _tap(B, my=80),
    "shine_hold": lambda f, t, me: (B, 0, -80 if f == 0 else 0, 0, 0, 0),  # Fox: reflector held up
    "down_b_throw": lambda f, t, me: (B, 0, -80, 0, 0, 0) if f == 0 else (  # Peach/Link/YL: pull, then throw it
        (A, 80 * t, 0, 0, 0, 0) if f == 45 else NONE),
    "dash_attack": _dash(A, 6),
    "dash_grab": _dash(Z, 3),
    "sh_nair": lambda f, t, me: (X, 0, 0, 0, 0, 0) if f == 0 else (
        (A, 0, 0, 0, 0, 0) if not int(me["on_ground"]) and f < 30 and not f % 2 else NONE),
    "sh_fair": _aerial(80, 0),
    "sh_bair": _aerial(-80, 0),
    "sh_dair": _aerial(0, -80),
    "sh_uair": _aerial(0, 80),
}

# Fox's names for his specials, so the ditto solver keeps its vocabulary.
ALIASES = {"shine": "down_b", "laser": "nb"}


def move(name: str) -> Move:
    return MOVES[ALIASES.get(name, name)]


def caught(slot) -> bool:
    return int(slot["action_id"]) in _CAUGHT


class Sim:
    """One raw melee-sim-light match on Final Destination: restore, step with raw inputs, read both players."""

    def __init__(self, p1: melee.Character = melee.Character.FOX, p2: melee.Character = melee.Character.FOX,
                 percents: tuple[int, int] = (0, 0)):
        from melee_llm.sim.world import World
        self.chars = (p1, p2)
        self.world = World({1: p1, 2: p2}, stage=melee.Stage.FINAL_DESTINATION,
                           percents={1: percents[0], 2: percents[1]})
        self.env = self.world.env

    def players(self):
        s = self.env.current_frame[0]["slots"]
        return s[0], s[1]

    def items(self):
        it = self.env.current_frame[0]["items"]
        return it[it["exists"] != 0]

    def step(self, inputs) -> None:
        env = self.env
        if env.t >= env.length:
            env.reset_cursor()
        row = env.raw_action_view[env.t, 0]["players"]
        for i, inp in enumerate(inputs):
            b, mx, my, cx, cy, r = inp if len(inp) == 6 else (inp[0], inp[1], inp[2], 0, 0, inp[3])
            row[i]["buttons"], row[i]["main_x"], row[i]["main_y"] = b, mx, my
            row[i]["c_x"], row[i]["c_y"], row[i]["l"], row[i]["r"] = cx, cy, 0, r
        env.step()

    def idle(self, frames: int) -> None:
        for _ in range(frames):
            self.step([NONE, NONE])

    def save(self) -> bytes:
        return self.env.save(0)

    def restore(self, state: bytes) -> None:
        self.env.restore(0, state)
        self.env.reset_cursor()  # observe() writes at the cursor, which may sit at the ring's end
        self.env.observe()

    def gap(self) -> float:
        a, b = self.players()
        return float(b["pos_x"] - a["pos_x"])

    def start(self) -> bytes:
        """Both standing at their spawns, the countdown over."""
        gs = self.world.reset(0)
        while gs.frame < 0 or gs.players[1].action != melee.Action.STANDING \
                or gs.players[2].action != melee.Action.STANDING:
            gs = self.world.step()
        return self.save()

    def setup(self, gap: float, start: bytes | None = None) -> bytes:
        """Both walk toward each other from their spawns and stop, standing and facing each other, at the closest
        reachable gap at or above `gap` (walking stops in steps of about 1.2)."""
        start = start or self.start()

        def walked(frames: int) -> float:
            self.restore(start)
            for _ in range(frames):
                self.step([(0, 30, 0, 0), (0, -30, 0, 0)])
            self.idle(30)
            return self.gap()

        lo, hi = 0, 400  # gap shrinks as frames grow; find the most frames whose gap is still >= `gap`
        if walked(lo) < gap:
            self.restore(start)
            return start
        while hi - lo > 1:
            mid = (lo + hi) // 2
            lo, hi = (mid, hi) if walked(mid) >= gap else (lo, mid)
        walked(lo)
        return self.save()
