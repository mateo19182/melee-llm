"""Named macro-actions executed frame by frame on a libmelee Controller.

A macro is a generator: each `yield` is the full controller `Input` for the next frame, and it reads the
fresh state from the shared `Ctx` after every yield. Returning ends it (the return string is its outcome).
`Executor` owns the controller: it runs the current macro, writes only input diffs, enforces timeouts and
fires reflexes (DI + auto-tech when hit, mashing when grabbed, recovery when below the stage).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable, Generator, Iterator

import melee
from melee import Action as A, Button as B, Character as C

from melee_llm.state import (AERIALS, DAMAGED, DEAD, GRABBED, LEDGE, SHIELDING, SHINE_IDS, SIDEB_IDS,
                             SPACIES, UPB_IDS, actionable, edge_x, ground_below, in_hitstun, ledge_x)

# Jumpsquat frames (NTSC 1.02); unknown characters default to 4.
JUMPSQUAT = {C.FOX: 3, C.FALCO: 5, C.MARTH: 4, C.SHEIK: 3, C.PEACH: 5, C.CPTFALCON: 4, C.JIGGLYPUFF: 5,
             C.POPO: 3, C.NANA: 3, C.PIKACHU: 3, C.SAMUS: 3, C.GANONDORF: 6, C.LUIGI: 4, C.MARIO: 4,
             C.DOC: 4, C.YOSHI: 5, C.DK: 5, C.BOWSER: 8, C.LINK: 6, C.YLINK: 4, C.ZELDA: 6, C.NESS: 4,
             C.KIRBY: 3, C.ROY: 5, C.MEWTWO: 5, C.GAMEANDWATCH: 4, C.PICHU: 3}
# Rough horizontal+vertical reach of up-B (units) used to time recoveries.
UPB_REACH = {C.FOX: 85, C.FALCO: 65, C.SHEIK: 60, C.MARTH: 40, C.CPTFALCON: 45, C.PEACH: 50}


@dataclass(frozen=True)
class Input:
    main: tuple[float, float] = (.5, .5)
    c: tuple[float, float] = (.5, .5)
    buttons: frozenset = frozenset()
    l: float = 0.0  # analog shoulders, 0..1


NEUTRAL = Input()
DIGITAL = (B.BUTTON_A, B.BUTTON_B, B.BUTTON_X, B.BUTTON_Y, B.BUTTON_Z, B.BUTTON_L, B.BUTTON_R)


def stick(x: float, y: float) -> tuple[float, float]:
    """Unit-range (-1..1) → libmelee 0..1 stick coordinates."""
    return (min(1., max(0., .5 + x / 2)), min(1., max(0., .5 + y / 2)))


def press(*buttons: B, main=(0., 0.), c=(0., 0.)) -> Input:
    return Input(stick(*main), stick(*c), frozenset(buttons))


class Pad:
    """Writes Inputs to a libmelee Controller, sending only what changed since the last frame."""

    def __init__(self, ctrl):
        self.ctrl, self.last = ctrl, None

    def apply(self, inp: Input) -> None:
        ctrl, last = self.ctrl, self.last
        if last is None:
            ctrl.release_all()
            last = NEUTRAL
        for b in DIGITAL:
            if (b in inp.buttons) != (b in last.buttons):
                (ctrl.press_button if b in inp.buttons else ctrl.release_button)(b)
        if inp.main != last.main:
            ctrl.tilt_analog(B.BUTTON_MAIN, *inp.main)
        if inp.c != last.c:
            ctrl.tilt_analog(B.BUTTON_C, *inp.c)
        if inp.l != last.l:
            ctrl.press_shoulder(B.BUTTON_L, inp.l)
        self.last = inp


@dataclass
class Ctx:
    """Live view of the game for macros; the executor refreshes it every frame."""
    port: int
    opp_port: int
    gs: melee.GameState | None = None

    @property
    def me(self) -> melee.PlayerState:
        return self.gs.players[self.port]

    @property
    def opp(self) -> melee.PlayerState:
        return self.gs.players[self.opp_port]

    @property
    def stage(self) -> melee.Stage:
        return self.gs.stage

    @property
    def facing(self) -> int:
        return 1 if self.me.facing else -1

    def sign(self, d: str) -> int:
        """Horizontal direction (+1 right, -1 left, 0 none) for a named direction."""
        x, ox = float(self.me.position.x), float(self.opp.position.x)
        toward = (1 if ox > x else -1) if abs(ox - x) > .5 else self.facing
        return {"toward": toward, "away": -toward, "right": 1, "left": -1, "forward": self.facing,
                "back": -self.facing, "center": -1 if x > 0 else 1}.get(d, 0)

    def frames_to_land(self) -> float:
        me = self.me
        g = ground_below(self.stage, float(me.position.x), float(me.position.y))
        vy = float(me.speed_y_self + me.speed_y_attack)
        if g is None or vy >= 0:
            return math.inf
        return (float(me.position.y) - g) / -vy


Macro = Generator[Input, None, str]


# ---------------------------------------------------------------- building blocks

def wait_free(c: Ctx, limit: int = 60, hold: Input = NEUTRAL) -> Iterator[Input]:
    for _ in range(limit):
        if actionable(c.me):
            return
        yield hold


def grounded(c: Ctx, limit: int = 20) -> Generator[Input, None, bool]:
    """Get to a state where tilts/jab/grab work (stop dashing, wait out landing lag)."""
    for _ in range(limit):
        me = c.me
        if not me.on_ground and me.action != A.KNEE_BEND:
            return False
        if me.on_ground and actionable(me) and me.action not in (A.DASHING, A.RUNNING, A.RUN_BRAKE):
            return True
        yield NEUTRAL
    return False


def face(c: Ctx, d: int) -> Iterator[Input]:
    """Turn around on the ground with a soft tilt (no dash)."""
    for _ in range(4):
        if d == 0 or c.facing == d or not c.me.on_ground:
            return
        yield Input(stick(.5 * d, 0))
    for _ in range(2):  # stick back to neutral so the next input is a clean tap
        yield NEUTRAL


def jump(c: Ctx, short: bool = True, d: int = 0) -> Generator[Input, None, bool]:
    """Ground jump (short or full hop) drifting toward d; returns True once airborne."""
    drift = stick(d, 0)
    for i in range(12):
        me = c.me
        if not me.on_ground:
            return True
        if me.action == A.KNEE_BEND:
            yield Input(drift, buttons=frozenset() if short else frozenset({B.BUTTON_Y}))
        else:
            yield Input(drift, buttons=frozenset({B.BUTTON_Y}) if i % 2 == 0 else frozenset())
    return not c.me.on_ground


def air_jump(c: Ctx, d: int = 0) -> Iterator[Input]:
    yield NEUTRAL
    yield Input(stick(d, 0), buttons=frozenset({B.BUTTON_Y}))
    yield Input(stick(d, 0))


def drift_to_land(c: Ctx, d: int, fastfall: bool, limit: int = 90) -> Generator[Input, None, str]:
    ff = False
    for _ in range(limit):
        me = c.me
        if me.on_ground:
            yield from wait_free(c, 30)
            return "landed"
        if c.me.off_stage and actionable(me):
            return "airborne"
        if fastfall and not ff and me.speed_y_self < 0 and actionable(me):
            ff = True
            yield Input(stick(d * .3, -1))
        else:
            yield Input(stick(d, -1 if ff else 0))
    return "timeout"


# ---------------------------------------------------------------- movement

def wait(c: Ctx, frames: int = 10) -> Macro:
    for _ in range(frames):
        yield NEUTRAL
    return "ok"


def approach(c: Ctx, frames: int = 40, until: float = 20) -> Macro:
    for _ in range(frames):
        d, me = c.sign("toward"), c.me
        if abs(float(c.opp.position.x - me.position.x)) <= until:
            return "in range"
        if me.on_ground and d * float(me.position.x) > edge_x(c.stage) - 6 and not c.opp.off_stage:
            return "at edge"
        yield Input(stick(d, 0))
    return "ok"


def retreat(c: Ctx, frames: int = 20) -> Macro:
    for _ in range(frames):
        d, me = c.sign("away"), c.me
        if me.on_ground and d * float(me.position.x) > edge_x(c.stage) - 12:
            return "cornered"
        yield Input(stick(d, 0))
    return "ok"


def dash_dance(c: Ctx, frames: int = 36, width: int = 7) -> Macro:
    d = c.sign("toward")
    for i in range(frames):
        if i and i % width == 0:
            d = -d
        if d * float(c.me.position.x) > edge_x(c.stage) - 10:
            d = -d
        yield Input(stick(d, 0))
    yield NEUTRAL
    return "ok"


def crouch(c: Ctx, frames: int = 20) -> Macro:
    for _ in range(frames):
        yield Input(stick(0, -1))
    return "ok"


def drop_platform(c: Ctx) -> Macro:
    if not c.me.on_ground or c.me.position.y < 5:
        return "invalid: not on a platform"
    yield NEUTRAL
    for _ in range(6):
        if not c.me.on_ground:
            return "ok"
        yield Input(stick(0, -1))
    return "failed"


def hop(c: Ctx, dir: str = "toward", height: str = "short") -> Macro:
    d = c.sign(dir)
    if c.me.on_ground:
        if not (yield from jump(c, height != "full", d)):
            return "failed"
    elif c.me.jumps_left > 0:
        yield from air_jump(c, d)
    else:
        return "invalid: no jumps"
    for _ in range(3):
        yield Input(stick(d, 0))
    return "airborne"


def wavedash(c: Ctx, dir: str = "toward") -> Macro:
    d = c.sign(dir) if dir not in ("in_place", "down") else 0
    if not c.me.on_ground:
        return "invalid: airborne"
    js = JUMPSQUAT.get(c.me.character, 4)
    for i in range(10):
        if c.me.action == A.KNEE_BEND or not c.me.on_ground:
            break
        yield Input(buttons=frozenset({B.BUTTON_Y}) if i % 2 == 0 else frozenset())
    for _ in range(js + 2):
        if c.me.action != A.KNEE_BEND or c.me.action_frame >= js:
            break
        yield NEUTRAL
    angle = stick(.95 * d, -.35) if d else stick(0, -1)
    yield Input(angle, buttons=frozenset({B.BUTTON_L}))
    yield Input(angle)
    yield from wait_free(c, 20)
    return "ok" if c.me.on_ground else "airdodged"


# ---------------------------------------------------------------- attacks

GROUND_ATTACKS = {  # name → (main stick, c stick, button, faces opponent)
    "jab": ((0, 0), (0, 0), B.BUTTON_A, True),
    "ftilt": (("f", 0), (0, 0), B.BUTTON_A, True),
    "utilt": ((0, .5), (0, 0), B.BUTTON_A, False),
    "dtilt": ((0, -.5), (0, 0), B.BUTTON_A, True),
    "fsmash": ((0, 0), ("f", 0), None, True),
    "usmash": ((0, 0), (0, 1), None, False),
    "dsmash": ((0, 0), (0, -1), None, False),
}


def ground_attack(c: Ctx, move: str, dir: str = "toward", count: int = 1) -> Macro:
    main, cst, btn, faces = GROUND_ATTACKS[move]
    if not (yield from grounded(c)):
        return "invalid: not grounded"
    if faces:
        yield from face(c, c.sign(dir))
    f = c.facing
    fx = lambda v: (.6 if btn else 1.) * f if v == "f" else v
    inp = Input(stick(fx(main[0]), main[1]), stick(fx(cst[0]), cst[1]), frozenset({btn}) if btn else frozenset())
    for _ in range(max(1, count)):
        yield inp
        for _ in range(3):
            yield NEUTRAL
    yield from wait_free(c, 70)
    return "ok"


def dash_attack(c: Ctx) -> Macro:
    if not (c.me.on_ground or c.me.action == A.KNEE_BEND):
        return "invalid: airborne"
    for _ in range(12):
        if c.me.action in (A.DASHING, A.RUNNING) and c.facing == c.sign("toward"):
            break
        yield Input(stick(c.sign("toward"), 0))
    yield press(B.BUTTON_A, main=(c.sign("toward"), 0))
    yield NEUTRAL
    yield from wait_free(c, 60)
    return "ok"


def aerial(c: Ctx, move: str = "nair", jump_: str = "short", dir: str = "toward", fastfall: bool = True,
           lcancel: bool = True) -> Macro:
    d = c.sign(dir)
    if c.me.on_ground or c.me.action == A.KNEE_BEND:
        if not (yield from jump(c, jump_ != "full", d)):
            return "failed: no jump"
    elif not actionable(c.me):
        return "invalid: busy"
    elif jump_ == "double" and c.me.jumps_left:
        yield from air_jump(c, d)
    f = c.facing
    cdir = {"nair": None, "fair": (f, 0), "bair": (-f, 0), "uair": (0, 1), "dair": (0, -1)}[move]
    yield Input(stick(d, 0), buttons=frozenset({B.BUTTON_A})) if cdir is None else Input(stick(d, 0), stick(*cdir))
    ff = lc = False
    for _ in range(80):
        me = c.me
        if me.on_ground:
            break
        if me.action not in AERIALS and actionable(me):
            if me.off_stage:
                return "airborne"
        y = -1 if ff else 0
        btns = frozenset()
        if fastfall and not ff and me.speed_y_self < 0 and me.hitlag_left == 0:
            ff, y = True, -1
        if lcancel and not lc and me.action in AERIALS and c.frames_to_land() <= 3:
            lc, btns = True, frozenset({B.BUTTON_L})
        yield Input(stick(d * .8, y), buttons=btns)
    yield from wait_free(c, 40)
    return "landed" + (" (l-cancel pressed)" if lc else "")


def grab(c: Ctx, throw: str = "f", dir: str = "toward", pummel: int = 0) -> Macro:
    me = c.me
    if not (me.on_ground or me.action == A.KNEE_BEND):
        return "invalid: airborne"
    if me.action not in (A.DASHING, A.RUNNING, A.KNEE_BEND):
        if not (yield from grounded(c)):
            return "invalid: busy"
        yield from face(c, c.sign(dir))
    yield press(B.BUTTON_Z)
    yield NEUTRAL
    for _ in range(40):
        a = c.me.action
        if a in (A.GRAB_PULLING, A.GRAB_WAIT, A.GRAB_RUNNING_PULLING):
            break
        if actionable(c.me) and a not in (A.GRAB, A.GRAB_RUNNING):
            return "whiffed"
        yield NEUTRAL
    else:
        return "whiffed"
    for _ in range(12):
        if c.me.action == A.GRAB_WAIT:
            break
        yield NEUTRAL
    for _ in range(pummel):
        yield press(B.BUTTON_A)
        for _ in range(8):
            yield NEUTRAL
    f = c.facing
    vec = {"f": (f, 0), "b": (-f, 0), "u": (0, 1), "d": (0, -1)}.get(throw, (f, 0))
    for _ in range(3):
        yield Input(stick(*vec))
    yield from wait_free(c, 70)
    return f"threw {throw}"


# ---------------------------------------------------------------- specials

def shine(c: Ctx, then: str = "jump", dir: str = "toward") -> Macro:
    """Down-B. Spacies: on the ground, jump-cancel (then='jump') or waveshine (then='wavedash') out of it."""
    yield press(B.BUTTON_B, main=(0, -1))
    if c.me.character not in SPACIES:
        yield NEUTRAL
        yield from wait_free(c, 90)
        return "ok"
    for _ in range(6):
        if c.me.action.value in SHINE_IDS:
            break
        yield NEUTRAL
    if not c.me.on_ground or then == "hold":
        for _ in range(8):
            yield Input(stick(0, -1), buttons=frozenset({B.BUTTON_B}) if then == "hold" else frozenset())
        yield from wait_free(c, 30)
        return "ok"
    for _ in range(6):
        if c.me.action_frame >= 3 or c.me.action.value != 0x168:
            break
        yield NEUTRAL
    if then == "wavedash":
        return (yield from wavedash(c, dir))
    yield press(B.BUTTON_Y)
    return "jump-cancelled"


def neutral_b(c: Ctx, jump_: str = "short", count: int = 1, fastfall: bool = True) -> Macro:
    """Laser for Fox/Falco (short-hop laser by default); plain neutral-B for others."""
    if c.me.character in SPACIES and jump_ != "none" and c.me.on_ground:
        if not (yield from jump(c, jump_ != "full", 0)):
            return "failed: no jump"
    for i in range(max(1, count)):
        yield press(B.BUTTON_B)
        for _ in range(4):
            yield NEUTRAL if not (fastfall and c.me.speed_y_self < 0 and i == count - 1) else Input(stick(0, -1))
    if not c.me.on_ground:
        r = yield from drift_to_land(c, 0, fastfall, 60)
        return f"fired {count}, {r}"
    yield from wait_free(c, 60)
    return f"fired {count}"


def side_b(c: Ctx, dir: str = "toward") -> Macro:
    d = c.sign(dir) or c.facing
    yield press(B.BUTTON_B, main=(d, 0))
    yield Input(stick(d, 0))
    for _ in range(80):
        if actionable(c.me) or c.me.on_ground and c.me.action not in DAMAGED and c.me.action.value not in SIDEB_IDS:
            break
        if c.me.action in (A.DEAD_FALL, A.SPECIAL_FALL_FORWARD, A.SPECIAL_FALL_BACK):
            yield Input(stick(c.sign("center"), 0))
            continue
        yield NEUTRAL
    yield from wait_free(c, 40)
    return "ok"


def _aim(c: Ctx, target: str) -> tuple[float, float]:
    me = c.me
    x, y = float(me.position.x), float(me.position.y)
    if target == "up":
        return stick(0, 1)
    if target == "ledge" and abs(x) > ledge_x(c.stage) - 2:
        tx, ty = math.copysign(ledge_x(c.stage), x), -8.
    else:
        tx, ty = math.copysign(min(abs(x), edge_x(c.stage) - 15), x), 8.
    dx, dy = tx - x, ty - y
    n = math.hypot(dx, dy) or 1
    return stick(dx / n, dy / n)


def up_b(c: Ctx, target: str = "ledge") -> Macro:
    yield press(B.BUTTON_B, main=(0, 1))
    for _ in range(120):
        me = c.me
        if me.action in LEDGE or (me.on_ground and actionable(me)):
            return "ledge" if me.action in LEDGE else "landed"
        if me.action in DEAD:
            return "died"
        if me.action in (A.DEAD_FALL, A.SPECIAL_FALL_FORWARD, A.SPECIAL_FALL_BACK) or (
                me.action.value not in UPB_IDS and me.character in SPACIES and not me.on_ground):
            yield Input(stick(c.sign("center"), 0))
        else:
            yield Input(_aim(c, target))
    yield from wait_free(c, 30)
    return "ok"


def recover(c: Ctx) -> Macro:
    """Get back to the stage: double jump, side-B (spacies, near ledge height) and up-B aimed at the ledge."""
    for _ in range(300):
        me = c.me
        if me.action in DEAD:
            return "died"
        if me.on_ground or me.action in LEDGE:
            return "safe"
        if not actionable(me):
            yield Input(stick(c.sign("center"), .3))
            continue
        x, y = float(me.position.x), float(me.position.y)
        dx = ledge_x(c.stage) - abs(x)  # negative when outside the ledge
        if dx > 5 and y > -5:
            return "over stage"
        dist = math.hypot(dx, y)
        reach = UPB_REACH.get(me.character, 45)
        if me.jumps_left > 0 and (y < -15 or dist > reach * .9):
            yield from air_jump(c, c.sign("center"))
            for _ in range(8):
                yield Input(stick(c.sign("center"), 0))
            continue
        if me.character in SPACIES and 25 < -dx < reach * .8 and -12 < y < 10:
            return f"side-b: {(yield from side_b(c, 'center'))}"
        if dist < reach or y < -25 or me.speed_y_self < 0 and me.jumps_left == 0:
            r = yield from up_b(c, "ledge")
            return f"up-b: {r}"
        yield Input(stick(c.sign("center"), 0))
    return "timeout"


# ---------------------------------------------------------------- defense

def shield(c: Ctx, frames: int = 20) -> Macro:
    for _ in range(frames):
        yield press(B.BUTTON_R)
    yield NEUTRAL
    return "ok"


def _out_of_shield(c: Ctx, vec: tuple[float, float]) -> Macro:
    if not (c.me.on_ground and (actionable(c.me) or c.me.action in SHIELDING)):
        return "invalid: not grounded"
    if c.me.action not in SHIELDING:
        yield press(B.BUTTON_R)
    yield press(B.BUTTON_R, main=vec)
    yield NEUTRAL
    yield from wait_free(c, 45)
    return "ok"


def roll(c: Ctx, dir: str = "away") -> Macro:
    return (yield from _out_of_shield(c, (c.sign(dir) or -c.facing, 0)))


def spot_dodge(c: Ctx) -> Macro:
    return (yield from _out_of_shield(c, (0, -1)))


def ledge(c: Ctx, option: str = "getup") -> Macro:
    for _ in range(40):
        if c.me.action != A.EDGE_CATCHING:
            break
        yield NEUTRAL
    if c.me.action != A.EDGE_HANGING:
        return "invalid: not on ledge"
    d = c.sign("center")
    inp = {"getup": press(main=(d, 0)), "roll": press(B.BUTTON_R), "jump": press(B.BUTTON_Y, main=(d, 0)),
           "attack": press(B.BUTTON_A), "drop": press(main=(0, -1))}.get(option, press(main=(d, 0)))
    yield inp
    yield NEUTRAL if option != "jump" else Input(stick(d, 0))
    if option == "drop":
        return "dropped"
    yield from wait_free(c, 60, Input(stick(d, 0)) if option == "jump" else NEUTRAL)
    return "ok"


def tech(c: Ctx, dir: str = "in_place") -> Macro:
    """Hold survival DI while in hitstun and press L just before landing (in place / toward / away)."""
    pressed = False
    for _ in range(150):
        me = c.me
        if me.on_ground and me.action not in DAMAGED:
            break
        if me.action not in DAMAGED or me.action in DEAD:
            return "free" if actionable(me) else "ok"
        if me.off_stage and not in_hitstun(me) and actionable(me):
            return "free offstage"
        btns = frozenset()
        if not pressed and not me.on_ground and c.frames_to_land() <= 4:
            pressed, btns = True, frozenset({B.BUTTON_L})
        d = 0 if dir == "in_place" else c.sign(dir)
        if pressed:
            yield Input(stick(d, 0), buttons=btns)
        else:  # survival DI: toward stage centre and up
            yield Input(stick(c.sign("center") * .7, .7))
    yield from wait_free(c, 60)
    return "teched" if pressed else "landed"


def mash(c: Ctx) -> Macro:
    i = 0
    while c.me.action in GRABBED and i < 200:
        yield Input(stick((-1) ** i, 0), buttons=frozenset({B.BUTTON_A}) if i % 2 else frozenset())
        i += 1
    return "escaped/thrown"


# ---------------------------------------------------------------- registry + LLM schema

@dataclass(frozen=True)
class Spec:
    fn: Callable[..., Macro]
    desc: str
    params: dict = field(default_factory=dict)  # schema field → macro kwarg
    interruptible: bool = False
    max_frames: int = 120


DIRS = ["toward", "away", "left", "right", "center", "in_place"]

ACTIONS: dict[str, Spec] = {
    "wait": Spec(wait, "Do nothing for `frames`.", {"frames": "frames"}, True),
    "approach": Spec(approach, "Dash/run toward opponent until close (stops at the edge).", {"frames": "frames"}, True),
    "retreat": Spec(retreat, "Run away from opponent (stops near the edge).", {"frames": "frames"}, True),
    "dash_dance": Spec(dash_dance, "Dash back and forth in place to bait and react.", {"frames": "frames"}, True),
    "crouch": Spec(crouch, "Crouch (crouch-cancel absorbs weak hits at low %).", {"frames": "frames"}, True),
    "drop_platform": Spec(drop_platform, "Fall through the platform you stand on.", {}),
    "short_hop": Spec(lambda c, dir="toward": hop(c, dir, "short"), "Short hop drifting `dir`.", {"dir": "dir"}),
    "full_hop": Spec(lambda c, dir="toward": hop(c, dir, "full"), "Full jump (or double jump if airborne).", {"dir": "dir"}),
    "wavedash": Spec(wavedash, "Wavedash `dir` (in_place = waveland down).", {"dir": "dir"}),
    **{m: Spec(lambda c, jump="short", dir="toward", fastfall=True, m=m: aerial(c, m, jump, dir, fastfall),
               "Aerial; from the ground jumps first (`jump` short/full/double), drifts `dir`, fast-falls, L-cancels.",
               {"jump": "jump", "dir": "dir", "fastfall": "fastfall"}, max_frames=150)
       for m in ("nair", "fair", "bair", "uair", "dair")},
    **{m: Spec(lambda c, dir="toward", m=m: ground_attack(c, m, dir), "Grounded attack, turns toward `dir` first.",
               {"dir": "dir"})
       for m in ("jab", "ftilt", "utilt", "dtilt", "fsmash", "usmash", "dsmash")},
    "dash_attack": Spec(dash_attack, "Dash toward opponent and dash attack.", {}),
    "grab": Spec(grab, "Grab (running grab if dashing) then throw `throw` (f/b/u/d).", {"throw": "throw", "dir": "dir"},
                 max_frames=150),
    "shine": Spec(shine, "Down-B. Spacie shine: grounded jump-cancels (`then`=jump) or waveshines (`then`=wavedash, `dir`).",
                  {"then": "then", "dir": "dir"}),
    "laser": Spec(neutral_b, "Neutral-B. Fox/Falco: short-hop laser (`jump` none = grounded), fast-fall.",
                  {"jump": "jump_", "count": "count"}),
    "side_b": Spec(side_b, "Side-B toward `dir` (Fox illusion / Falco phantasm).", {"dir": "dir"}),
    "up_b": Spec(up_b, "Up-B aimed at the ledge (recovery).", {}, max_frames=150),
    "recover": Spec(recover, "Character-aware recovery back to stage (double jump, side-B, up-B to ledge).", {}, max_frames=300),
    "shield": Spec(shield, "Hold shield for `frames`.", {"frames": "frames"}, True),
    "roll": Spec(roll, "Roll `dir` out of shield.", {"dir": "dir"}),
    "spot_dodge": Spec(spot_dodge, "Spot dodge in place.", {}),
    "ledge": Spec(ledge, "Ledge option (`ledge`: getup/roll/jump/attack/drop).", {"ledge": "option"}),
    "tech": Spec(tech, "Tech on landing (`dir` in_place/toward/away). Usually automatic.", {"dir": "dir"}, max_frames=160),
}

SCHEMA_FIELDS = {
    "dir": {"type": "string", "enum": DIRS},
    "jump": {"type": "string", "enum": ["short", "full", "double", "none"]},
    "fastfall": {"type": "boolean"},
    "throw": {"type": "string", "enum": ["f", "b", "u", "d"]},
    "then": {"type": "string", "enum": ["jump", "wavedash", "hold"]},
    "ledge": {"type": "string", "enum": ["getup", "roll", "jump", "attack", "drop"]},
    "frames": {"type": "integer", "minimum": 1, "maximum": 90},
    "count": {"type": "integer", "minimum": 1, "maximum": 3},
}


def tool_schema() -> dict:
    """OpenAI function-tool describing the action set (one `act` call per decision)."""
    return {"type": "function", "function": {
        "name": "act",
        "description": "Choose the next macro-action. Directions are relative to the opponent unless left/right/center.",
        "parameters": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": list(ACTIONS)},
                **SCHEMA_FIELDS,
                "reason": {"type": "string", "description": "≤12 words, why (shown to casters)"},
            },
            "required": ["action"],
            "additionalProperties": False,
        }}}


def action_help() -> str:
    """One line per action; actions sharing a description (aerials, ground attacks) share a line."""
    groups: dict[tuple, list[str]] = {}
    for n, s in ACTIONS.items():
        groups.setdefault((s.desc, tuple(s.params)), []).append(n)
    lines = []
    for (desc, params), names in groups.items():
        lines.append(f"- {'|'.join(names)}" + (f" [{', '.join(params)}]" if params else "") + f": {desc}")
    return "\n".join(lines)


def make(decision: dict, c: Ctx) -> tuple[str, Macro, Spec]:
    """Build a macro from an LLM decision dict; unknown params/values are dropped."""
    name = decision.get("action")
    if name not in ACTIONS:
        name = "wait"
    spec = ACTIONS[name]
    kwargs = {}
    for field_, kw in spec.params.items():
        v = decision.get(field_)
        sch = SCHEMA_FIELDS[field_]
        if v is None or ("enum" in sch and v not in sch["enum"]):
            continue
        if sch["type"] == "integer":
            try:
                v = max(sch["minimum"], min(sch["maximum"], int(v)))
            except (TypeError, ValueError):
                continue
        kwargs[kw] = v
    return name, spec.fn(c, **kwargs), spec


# ---------------------------------------------------------------- executor

MASH = Spec(mash, "Mash out of a grab.", max_frames=200)

@dataclass
class Running:
    name: str
    gen: Macro
    spec: Spec
    start_frame: int
    frames: int = 0
    reflex: bool = False


class Executor:
    """Runs one macro at a time on a controller, with safety reflexes. Call `step(gs)` once per frame."""

    def __init__(self, ctrl, port: int, opp_port: int, reflexes: bool = True):
        self.pad = Pad(ctrl)
        self.ctx = Ctx(port, opp_port)
        self.reflexes = reflexes
        self.cur: Running | None = None
        self.finished: list[tuple[str, str, int]] = []  # (macro, outcome, frames) since last drain

    @property
    def idle(self) -> bool:
        return self.cur is None

    @property
    def interruptible(self) -> bool:
        return self.cur is None or (self.cur.spec.interruptible and not self.cur.reflex)

    def start(self, decision: dict, reflex: bool = False) -> str:
        if self.cur:
            self._finish("interrupted")
        name, gen, spec = make(decision, self.ctx)
        self.cur = Running(name, gen, spec, int(self.ctx.gs.frame) if self.ctx.gs else 0, reflex=reflex)
        return name

    def _finish(self, outcome: str) -> None:
        if self.cur:
            self.finished.append((self.cur.name, outcome, self.cur.frames))
            self.cur.gen.close()
            self.cur = None

    def _reflex(self) -> None:
        me, name = self.ctx.me, self.cur.name if self.cur else None
        if me.action in DEAD:
            if self.cur:
                self._finish("died")
            return
        if in_hitstun(me) and name != "tech":
            self._finish("got hit")
            self._start_reflex("tech", tech(self.ctx), ACTIONS["tech"])
        elif me.action in GRABBED and name != "mash":
            self._finish("got grabbed")
            self._start_reflex("mash", mash(self.ctx), MASH)
        elif (me.off_stage and actionable(me) and name not in ("recover", "up_b", "side_b", "tech")
              and (me.position.y < -15 or abs(me.position.x) > ledge_x(self.ctx.stage) + 50)):
            self._finish("offstage")
            self._start_reflex("recover", recover(self.ctx), ACTIONS["recover"])

    def _start_reflex(self, name, gen, spec):
        self.cur = Running(name, gen, spec, int(self.ctx.gs.frame), reflex=True)

    def step(self, gs: melee.GameState) -> Input:
        self.ctx.gs = gs
        if self.reflexes:
            self._reflex()
        me = gs.players[self.ctx.port]
        inp = Input(stick(self.ctx.sign("center"), 0)) if me.off_stage and not self.cur else NEUTRAL
        if self.cur:
            if self.cur.frames >= self.cur.spec.max_frames:
                self._finish("timeout")
            else:
                try:
                    inp = next(self.cur.gen)
                    self.cur.frames += 1
                except StopIteration as e:
                    self._finish(e.value or "done")
        self.pad.apply(inp)
        return inp

    def drain(self) -> list[tuple[str, str, int]]:
        out, self.finished = self.finished, []
        return out


class RecordingController:
    """Duck-typed libmelee Controller that records state instead of writing to Dolphin (for tests)."""

    def __init__(self):
        self.state = melee.ControllerState()
        self.log: list[str] = []

    def release_all(self):
        self.state = melee.ControllerState()

    def press_button(self, b):
        self.state.button[b] = True

    def release_button(self, b):
        self.state.button[b] = False

    def tilt_analog(self, b, x, y):
        if b == B.BUTTON_MAIN:
            self.state.main_stick = (x, y)
        else:
            self.state.c_stick = (x, y)

    def press_shoulder(self, b, amount):
        self.state.l_shoulder = amount

    def flush(self):
        s = self.state
        btn = "".join(b.value for b in DIGITAL if s.button[b]) or "-"
        fmt = lambda t: f"{t[0]:.2f},{t[1]:.2f}"
        self.log.append(f"{btn:4} main({fmt(s.main_stick)}) c({fmt(s.c_stick)})" + (f" L{s.l_shoulder:.1f}" if s.l_shoulder else ""))
