"""Record the simulator traces behind the Brute page (melee_llm/web/static/brute/clips.json).

Every clip is a frame-by-frame recording of two Foxes in melee-brute: positions, action, facing, percent, shield
health and the inputs pressed. The lines are not scripted: they are walked out of the solver (`nash.Nash.forced`,
`fortress.Fortress`), then replayed and recorded. Each clip is checked against what docs/optimal-play.md (sections
13 and 14) says before it is written; a mismatch stops the script. P1 (red) attacks, P2 (blue) defends.

A scene whose position is placed by `force.corner` also gets a `setup` clip: the same inputs replayed from the
match start, so the page can show how the position is reached and which part of that is staging. `--solver`
turns the raw outputs of section 15 (squeeze-8.jsonl and the net-*.txt solves) into brute/road.json.

    MSL_DATA_DIR=vendor/melee-sim-light/data PYTHONPATH=. uv run python scripts/optimal_play_animations.py
    ... scripts/optimal_play_animations.py --only door ledge    # redo some scenes, keep the rest of the file
    ... scripts/optimal_play_animations.py --only setup --solver data/solver   # only the lead-ins and the road

All scenes take about 12 minutes on one core and stay under 2 GB.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import melee
import numpy as np

from melee_llm.solver import force, fortress, nash
from melee_llm.solver.game import A, B, R, Sim, X, Z
from melee_llm.solver.matrix import solve as solve_matrix

OUT = Path(__file__).resolve().parent.parent / "melee_llm" / "web" / "static" / "brute" / "clips.json"
EDGE = 85.57
N = (0, 0, 0, 0)
USMASH = (A, 0, 80, 0)
WALK, FLICK = (0, 30, 0, 0), (0, -80, 0, 0)
BUTTONS = ((A, "A"), (B, "B"), (X, "X"), (Z, "Z"), (R, "R"))
LABELS = {14: "standing", 15: "walking", 16: "walking", 17: "walking", 18: "turning", 20: "dash", 24: "jumpsquat",
          25: "short hop", 42: "landing", 44: "jab", 63: "up smash", 178: "shield", 179: "shield", 181: "shield, hit",
          182: "shield", 180: "dropping shield", 212: "grab", 233: "roll in", 234: "roll away", 235: "spotdodge",
          245: "teetering on the ledge", 246: "teetering on the ledge", 360: "shine", 361: "shine (held)", 365: "shine", 366: "shine (held)"}
EXITS = ("release", "jump_oos", "roll_in", "roll_out", "shield_grab", "spotdodge")
SAY = {"wait": "waits", "out": "steps away", "shine": "shines", "shield": "shields"}
REACH = [10.7, "shine 10.7"]


def label(action: int) -> str:
    if action in LABELS:
        return LABELS[action]
    name = melee.Action(action).name
    return "hit, in knockback" if name.startswith("DAMAGE") else name.lower().replace("_", " ")


def raw(sim: Sim, a: str, d: str):
    """The two controller rows for solver moves `a` (P1) and `d` (P2), as `Nash.joint` builds them."""
    p1, p2 = sim.players()
    toward = 1 if float(p2["pos_x"]) >= float(p1["pos_x"]) else -1
    b, x, y, r = nash.MOVES[a]
    db, dx, dy, dr = nash.MOVES[d]
    return (b, x * toward, y, r), (db, -dx * toward, dy, dr)


class Clip:
    """A recording. Row 0 is the starting position; `lead` rows later is frame 1, the first frame that matters."""

    def __init__(self, sim: Sim, root: bytes):
        self.sim, self.rows, self.lead = sim, [], 0
        sim.restore(root)
        self._row(N, N)

    def _row(self, i1, i2) -> None:
        row = []
        for p, (b, sx, sy, _) in zip(self.sim.players(), (i1, i2)):
            row.append([round(float(p["pos_x"]), 2), round(float(p["pos_y"]), 2), int(p["action_id"]),
                        int(p["action_frame"]), int(p["facing"]), round(float(p["percent"]), 1),
                        round(float(p["shield_hp"]), 1), int(p["hitlag"]), int(p["invulnerable"]),
                        "".join(n for bit, n in BUTTONS if b & bit), sx, sy])
        self.rows.append(row)

    def step(self, i1=N, i2=N, n: int = 1) -> "Clip":
        for _ in range(n):
            self.sim.step([i1, i2])
            self._row(i1, i2)
        return self

    def moves(self, a: str, d: str) -> "Clip":
        return self.step(*raw(self.sim, a, d))

    def start(self) -> "Clip":
        """The next frame recorded is frame 1."""
        self.lead = len(self.rows) - 1
        return self

    def frame(self, f: int):
        return self.rows[self.lead + f]

    def hits(self) -> list[tuple[int, int, float]]:
        """(frame, player hit, percent taken) for every frame on which someone's percent went up."""
        out = []
        for i in range(1, len(self.rows)):
            for p in (0, 1):
                gain = self.rows[i][p][5] - self.rows[i - 1][p][5]
                if gain > 0:
                    out.append((i - self.lead, p + 1, gain))
        return out

    def gap(self, f: int = 0) -> float:
        a, b = self.frame(f)
        return round(b[0] - a[0], 2)

    def at(self, frame: int) -> "Clip":
        """Row 0 is match frame `frame`: frames are then counted from the match start."""
        self.lead = -frame
        return self

    def data(self, key: str, title: str, caption: str, notes: dict[int, str], marks=(), **more) -> dict:
        return {"id": key, "title": title, "caption": caption, "lead": self.lead, "rows": self.rows,
                "notes": sorted(notes.items()), "marks": list(marks), **more}

    def thinned(self, keep: set[int], every: int = 3, tail: int = 12) -> dict:
        """A long recording from the match start, for playing fast: every `every`th frame, the frames in `keep`
        and the last `tail`. `frames` says which match frame each row is."""
        last = len(self.rows) - 1
        frames = [f for f in range(last + 1) if f % every == 0 or f in keep or f > last - tail]
        return {"frames": frames, "rows": [self.rows[f] for f in frames]}


def expect(clip: Clip, hits: list[tuple[int, int, float]], what: str) -> None:
    got = clip.hits()
    if got != hits:
        raise SystemExit(f"MISMATCH in {what}: expected hits {hits} (frame, player, percent), simulator gave {got}")
    print(f"ok  {what}: {got or 'nobody hit'}")


def walk(S: nash.Nash, first: tuple[str, str], frames: int, attacking: bool) -> list[tuple[str, str]]:
    """Play `first`, then follow the pure line the solver proves: P1's forced hit (`attacking`), preferring the
    shine as soon as it is forced, or P2's safe defence against a P1 who waits. The other side takes the answer
    that needs no new input: he waits, or keeps his shield up. Returns the pairs of moves, ending at the hit or
    the horizon."""
    S.rb.checkpoint(0)
    S.joint(*first)
    line, depth = [first], 1
    frames -= 1
    if S.leaf() is None and not S.forced(depth, frames, attacking):
        raise SystemExit(f"MISMATCH: after {first} the solver finds no {'forced hit' if attacking else 'safe defence'}")
    while frames > 0 and S.leaf() is None:
        att, dfn = S.menus()
        mine, theirs = (att, dfn) if attacking else (dfn, att)
        want = 1.0 if attacking else 0.0
        S.rb.checkpoint(depth)
        picks = []
        for x in mine:
            ok = True
            for y in theirs:
                S.joint(*((x, y) if attacking else (y, x)))
                v = S.leaf()
                ok = S.forced(depth + 1, frames - 1, attacking) if v is None else v == want
                S.back(depth)
                if not ok:
                    break
            if ok:
                picks.append(x)
        pick = next((m for m in (("shine", "wait") if attacking else ("wait", "hold_b", "out")) if m in picks), picks[0])
        ans = "wait" if "wait" in theirs else "shield" if "shield" in theirs else theirs[0]
        pair = (pick, ans) if attacking else (ans, pick)
        S.joint(*pair)
        line.append(pair)
        depth += 1
        frames -= 1
    S.back(0)
    return line


def show(clip: Clip, what: str) -> None:
    """The frames that matter, one per line, for writing and checking the captions."""
    print(f"    {what}")
    for i in range(max(0, clip.lead if clip.lead > 0 else len(clip.rows) - 24), len(clip.rows)):
        a, b = clip.rows[i]
        print(f"      f{i - clip.lead:>4} gap {b[0] - a[0]:6.2f}  P1 {label(a[2]):<16}{a[3]:>3} y{a[1]:5.1f} {a[5]:>4}% [{a[9]:<2} {a[10]:>3} {a[11]:>3}]"
              f"   P2 {label(b[2]):<16}{b[3]:>3} x{b[0]:6.2f} y{b[1]:5.1f} {b[5]:>4}% [{b[9]:<2} {b[10]:>3} {b[11]:>3}]")


def grid(att, row, dfn, col, value: float, frames: int, m: np.ndarray, want: dict) -> tuple[dict, list, list]:
    """The mixed strategy of a solved position as the page shows it, checked against `want`: the value and both
    mixes in percent. Returns the grid and the moves each side mixes over."""
    mix1 = {a: round(float(p) * 100) for a, p in zip(att, row) if p > 1e-6}
    mix2 = {d: round(float(p) * 100) for d, p in zip(dfn, col) if p > 1e-6}
    got = {"value": round(value, 4), "p1": mix1, "p2": mix2}
    if got != want:
        raise SystemExit(f"MISMATCH in a mixed strategy: expected {want}, the solver gave {got}")
    print(f"ok  mix to {frames} frames: {got}")
    cells = [[round(float(m[att.index(a), dfn.index(d)]), 3) for d in mix2] for a in mix1]
    return ({"rows": [{"label": f"red {SAY[a]}", "p": p} for a, p in mix1.items()],
             "cols": [{"label": f"blue {SAY[d]}", "p": p} for d, p in mix2.items()],
             "value": got["value"], "frames": frames, "cells": cells}, list(mix1), list(mix2))


def lead_in(sim: Sim, gap: float, ledge: float, hop: int = 0, shield: int = 0, *, caption: str, end: str,
            want: tuple[int, float]) -> dict:
    """How `force.corner` reaches its position, recorded from the match start: the same inputs in the same order,
    checked against its savestate. `want` is the match frame and the gap it must end on."""
    c = Clip(sim, sim.start())
    x2 = lambda: float(sim.players()[1]["pos_x"])
    assert x2() < EDGE - ledge, "corner() walks P2 toward the ledge from his spawn"
    spawn = x2()
    while x2() < EDGE - ledge:
        c.step(N, (0, 30, 0, 0))
    walked = len(c.rows) - 1
    c.step(n=20).step(N, (0, -25, 0, 0), 3).step(n=25)
    faced, room = len(c.rows) - 1, EDGE - x2()
    while sim.gap() > gap + 1.0:
        c.step((0, 30, 0, 0), N)
    released, let_go = len(c.rows) - 1, sim.gap()
    c.step(n=30)
    stood, standing = len(c.rows) - 1, sim.gap()
    for f in range(hop):
        c.step((X, 40, 0, 0) if f == 0 else (0, 40, 0, 0), N)
    c.step(N, (R, 0, 0, 255), shield)
    state, last = sim.save(), len(c.rows) - 1
    seen = (last, round(sim.gap(), 2))
    if state != force.corner(sim, gap, ledge, hop, shield) or seen != want:
        raise SystemExit(f"MISMATCH in the lead-in to corner({gap}, {ledge}, {hop}, {shield}): ends {seen}, wanted {want}")
    expect(c, [], f"lead-in from the match start to corner({gap}, {ledge}, {hop}, {shield}): frame {last}, gap {seen[1]}")
    where = "on the ledge itself" if room < 0.05 else f"{room:.1f} units from the ledge"
    notes = {0: "Match start: both Foxes at their spawns, 120 apart.",
             1: f"Staging, not play: blue walks {x2() - spawn:.1f} units toward the ledge behind him. Nothing makes him.",
             walked + 1: f"Staging: blue stops and turns round to face red. He is {where}.",
             faced + 1: f"Red walks in for {released - faced} frames. Blue stands still and lets him.",
             released + 1: f"Red lets go of the stick {let_go:.2f} away and slides to a stop, {standing:.2f} away.",
             last: end}
    if hop:
        notes[stood + 1] = f"From {standing:.2f} away red short-hops toward blue. Blue still does not move."
    if shield:
        notes[stood + 1] = f"Blue raises his shield. Red is standing {standing:.2f} away, free to act."
    return {"id": "setup", "title": "From the match start", "caption": caption, "lead": 0, "notes": sorted(notes.items()),
            "marks": [], "fps": 60, **c.thinned(set(notes)),
            "facts": {"frames": last, "walked": walked, "faced": faced, "released": released, "stood": stood,
                      "blue_walks": round(x2() - spawn, 2), "room": round(room, 2), "let_go": round(let_go, 2),
                      "standing": round(standing, 2)}}


SETUPS = {  # scene -> corner() arguments, the caption, the last note, and the (frame, gap) the lead-in ends on
    "standoff": ((14, 12), "How the search position is reached from the match start, at three times real speed. "
                 "Blue first walks toward the ledge and turns round: that is staging, so that he has little room "
                 "behind him. Then red walks in and stops, and blue lets him.",
                 "Frame 324: the position searched. 12.59 apart, both standing.", (324, 12.59)),
    "door": ((15.5, 12, 0, 12), "How the search position is reached from the match start, at three times real speed. "
             "Blue walks toward the ledge and turns round (staging). Red walks in and stops 14.39 away. Then blue "
             "raises his shield and holds it for 12 frames. Red has done nothing to make him.",
             "Frame 333: the position searched. Blue has held shield for 12 frames, red stands 14.39 away.", (333, 14.39)),
    "hop5": ((11.5, 12, 5), "How the search position is reached from the match start, at three times real speed. "
             "Blue walks toward the ledge and turns round (staging). Red walks in and stops 10.19 away, already "
             "inside shine range, and blue does nothing. Red then short-hops, and blue still does nothing.",
             "Frame 333: the position searched. Red is 5 frames into the hop, 9.42 away and 4.0 up.", (333, 9.42)),
    "coin": ((11.5, 12, 9), "How the search position is reached from the match start, at three times real speed. "
             "The same staging as the hop five frames in, with blue standing still for four frames more.",
             "Frame 337: the position searched. Red is 9 frames into the hop, 7.76 away and 9.2 up.", (337, 7.76)),
    "ledge": ((10, 1), "How the search position is reached from the match start, at three times real speed. Blue "
              "walks himself to the ledge and turns round: nobody pushed him there. Red then walks in and stops "
              "8.52 away, inside shine range, and blue lets him.",
              "Frame 365: the position searched. Blue on the ledge, red standing 8.52 away.", (365, 8.52)),
}


def road(solver: Path) -> dict:
    """Section 15's raw outputs as the page reads them: every cell of the mid-stage map (the defender's safe first
    inputs for 8 frames against an attacker who sees each one before answering) and the exact net solves."""
    rows = [json.loads(line) for line in (solver / "squeeze-8.jsonl").read_text().splitlines()]
    free = [r for r in rows if r["ask"]["condition"] == "free"]
    hold = {(r["ask"]["kind"], r["ask"]["gap"]): r["safe"] for r in rows if r["ask"]["condition"] == "hold"}
    if len(rows) != 90 or len(free) != 45 or {r["ask"]["frames"] for r in rows} != {8} or {r["at"]["room"] for r in rows} != {61.82}:
        raise SystemExit("MISMATCH in squeeze-8.jsonl: expected the 90 mid-stage jobs of section 15, 8 frames")
    cells = sorted(({"kind": r["ask"]["kind"], "gap": r["at"]["gap"], "safe": r["safe"],
                     "held": hold[r["ask"]["kind"], r["ask"]["gap"]] == r["safe"]} for r in free),
                   key=lambda c: (("stand", "walk", "dash").index(c["kind"]), -c["gap"]))
    net = []
    for path in sorted(solver.glob("net-*.txt")):
        text = path.read_text()
        m = re.match(r"gap ([\d.]+), .*\((\w+) against (\w+)\), (\d+) frames: value ([+-][\d.]+) .*\[([\d,]+) positions", text)
        mix = [json.loads(x.replace("'", '"')) for x in re.findall(r"P[12] plays (\{.*\})", text)]
        net.append({"file": path.name, "gap": float(m[1]), "attacker": m[2].lower(), "defender": m[3].lower(), "frames": int(m[4]),
                    "value": float(m[5]), "p1": mix[0], "p2": mix[1], "positions": int(m[6].replace(",", ""))})
    out = {"frames": 8, "jobs": len(rows), "positions": sum(r["positions"] for r in rows), "room": 61.82,
           "give": max(r["ask"]["give"] for r in rows), "cells": cells, "net": net}
    print(f"ok  road: {len(cells)} cells, {out['positions']:,} positions, {len(net)} net solves "
          f"({', '.join(f'{n['attacker']} {n['gap']}: {n['value']:+g}' for n in net)})")
    return out


def standoff(sim: Sim) -> list[dict]:
    wait = Clip(sim, force.corner(sim, 14, 12)).start().step(n=30)
    expect(wait, [], "standoff, both wait 30 frames")
    assert wait.gap() == 12.59, wait.gap()
    room = round(EDGE - wait.frame(0)[1][0], 1)

    close = force.corner(sim, 8, 12)
    clank = Clip(sim, close).step(n=6).start().moves("shine", "shine").step(n=16)
    expect(clank, [], "same-frame grounded shines")
    assert [clank.frame(f)[p][7] for f in (1, 4, 5) for p in (0, 1)] == [4, 4, 1, 1, 0, 0], "clank hitlag"

    early = Clip(sim, close).step(n=6).start().moves("shine", "wait").moves("wait", "shine").step(n=16)
    expect(early, [(1, 2, 5.0)], "shine one frame earlier")
    g = clank.gap()
    return [
        wait.data("wait", "Both wait", f"Two Foxes 12.59 units apart, blue with his back {room} units from the ledge. "
                  "The tick under the stage is how far red's shine reaches a standing Fox: blue is outside it. "
                  "Searched 8 frames deep, red's chance of a clean first hit is 0, and the best play for both is "
                  "this: nothing.", {1: "Both wait. Whatever either starts, the other sees one frame later."}, [REACH]),
        clank.data("clank", "Same-frame shines", f"Up close ({g} units) both press shine on the same frame. The two "
                   "hitboxes clank: both freeze for 4 frames and nobody takes damage.",
                   {-6: "Standing in each other's shine range.", 1: "Frame 1: both shine. The hitboxes meet.",
                    2: "Clank: 4 frames of freeze, 0% to both.", 5: "Both are left holding the reflector. Nothing happened."},
                   [REACH]),
        early.data("early", "One frame earlier", "Same spot, but red presses one frame before blue. The shine "
                   "hits on the frame it is pressed, so blue's shine never comes out: 5%.",
                   {-6: "Standing in each other's shine range.", 1: "Frame 1: red shines. It hits at once: 5%.",
                    2: "Frame 2: blue presses shine too, but he is already hit."}, [REACH]),
    ]


def reach(sim: Sim) -> list[dict]:
    far, near, miss_at = force.corner(sim, 14, 12), force.corner(sim, 11.5, 12), force.corner(sim, 12, 12)
    marks = [[10.7, "10.7"], [12.6, "12.6"]]
    miss = Clip(sim, far).step(n=6).start().moves("shine", "wait").step(n=14)
    expect(miss, [], "shine at a standing Fox from 12.59")
    edge = Clip(sim, miss_at).start().moves("shine", "wait")
    expect(edge, [], f"shine at a standing Fox from {edge.gap()}")
    hit = Clip(sim, near).step(n=6).start().moves("shine", "wait").step(n=14)
    expect(hit, [(1, 2, 5.0)], f"shine at a standing Fox from {hit.gap()}")
    squat = Clip(sim, far).step(n=6).start().moves("wait", "hop").moves("shine", "wait").step(n=14)
    expect(squat, [(2, 2, 5.0)], "shine at a Fox in jumpsquat from 12.59")
    assert squat.frame(1)[1][2] == 24, "jumpsquat"
    roll = Clip(sim, force.corner(sim, 14, 12, 0, 6)).step(N, nash.MOVES["shield"], 6).start()
    roll.moves("wait", "roll_out").moves("shine", "wait").step(n=14)
    expect(roll, [(2, 2, 5.0)], "shine at a Fox starting a roll away from 12.59")
    return [
        miss.data("miss", "Standing, 12.6 away", "Red shines at a standing Fox from 12.59 units. It comes out on "
                  "frame 1 and touches nothing.", {-6: "12.59 apart: outside shine range.", 1: "Frame 1: shine. No hit.",
                                                    2: "Red is now stuck in the shine for a few frames."}, marks),
        hit.data("hit", f"Standing, {hit.gap():.1f} away", f"One step closer, at {hit.gap()} units, the same shine hits "
                 f"for 5%. From {edge.gap()} it still misses: the reach against a standing Fox is about 10.7.",
                 {-6: f"{hit.gap()} apart: inside shine range.", 1: "Frame 1: shine. 5%."}, marks),
        squat.data("squat", "Jumpsquat, 12.6 away", "Back at 12.59. Blue presses jump; for 3 frames he crouches on "
                   "the ground before leaving it (the jumpsquat). In that crouch the shine reaches him.",
                   {-6: "12.59 apart again.", 1: "Frame 1: blue starts a jump (jumpsquat).",
                    2: "Frame 2: red shines. It reaches: 5%."}, marks),
        roll.data("roll", "Roll start, 12.6 away", "Blue rolls away out of shield from 12.59. In the first frames "
                  "of the roll the shine reaches him too, before he has moved or become intangible.",
                  {-6: "Blue in shield, 12.59 away.", 1: "Frame 1: blue starts rolling away.",
                   2: "Frame 2: red shines. It reaches: 5%."}, marks),
    ]


# Per clip: title, caption, the hits the simulator must give (frame, player, percent), notes by frame[, grid tag].
DOOR_TEXT = {
    "release": ("Let go", "Blue lets go of the shield. Dropping it takes several frames in which he can do nothing. "
                "Red sees it on frame 2, turns around (that is how the search makes the shine reach from here) and "
                "shines on frame 3: 5%.", [(3, 2, 5.0)],
                {1: "Frame 1: blue lets go of the shield.", 2: "Frame 2: red has seen it, and turns around.",
                 3: "Frame 3: red shines. 5%."}),
    "jump_oos": ("Jump", "Blue jumps out of shield. A jump starts with 3 frames of crouch on the ground (the "
                 "jumpsquat). Red sees it and shines on frame 2, and the shine reaches that crouch even from 14.39: "
                 "5% before blue leaves the floor.", [(2, 2, 5.0)],
                 {1: "Frame 1: blue jumps out of shield (jumpsquat).", 2: "Frame 2: red has seen it, and shines. 5%."}),
    "roll_in": ("Roll in", "Blue rolls toward red. The shine would miss this one, so red jabs instead: the jab "
                "comes out a frame later and catches the start of the roll. 4%.", [(3, 2, 4.0)],
                {1: "Frame 1: blue starts rolling in.", 2: "Frame 2: red has seen it, and jabs.",
                 3: "Frame 3: the jab lands. 4%."}),
    "roll_out": ("Roll away", "Blue rolls toward the ledge. The roll takes time to get going. Red turns around "
                 "and shines its first frames from where he stands: 5%.", [(3, 2, 5.0)],
                 {1: "Frame 1: blue starts rolling away.", 2: "Frame 2: red has seen it, and turns around.",
                  3: "Frame 3: red shines. 5%."}),
    "shield_grab": ("Shield grab", "Blue grabs out of shield. The grab cannot reach 14.39 units. Red waits while "
                    "it comes out and shines on frame 7, the frame the search finds: 5%.", [(7, 2, 5.0)],
                    {1: "Frame 1: blue grabs out of shield.", 2: "Red waits: the grab cannot reach him.",
                     7: "Frame 7: red shines the outstretched arm. 5%."}),
}
HOP5_TEXT = {
    "wait": ("Blue waits", "Red shines on the first frame. Blue did nothing, and the shine is already there: 5%.",
             [(1, 2, 5.0)], {1: "Frame 1: red shines. 5%."}),
    "out": ("Blue steps away", "Blue turns to run. The shine is out on the same frame, before he has moved: 5%.",
            [(1, 2, 5.0)], {1: "Frame 1: red shines as blue turns to run. 5%."}),
    "jab": ("Blue jabs", "Blue jabs. A jab needs a frame to come out and the shine does not: 5%.",
            [(1, 2, 5.0)], {1: "Frame 1: red shines before the jab is out. 5%."}),
    "hop": ("Blue jumps", "Blue jumps. He is still crouching on the ground (the jumpsquat) when the shine arrives: 5%.",
            [(1, 2, 5.0)], {1: "Frame 1: red shines blue's jumpsquat. 5%."}),
    "shine": ("Blue shines too", "The one answer that survives the first frame: blue shines as well, and neither "
              "can be hit. But red is in the air, so he can jump out of his shine with his second jump and shine "
              "again from higher up. Blue, on the ground, is still holding his: 5% on frame 10.", [(10, 2, 5.0)],
              {1: "Frame 1: both shine. Neither can be hit on that frame.", 2: "Both hold the reflector.",
               9: "Frame 9: red jumps out of his shine.", 10: "Frame 10: red shines again. 5%."}),
}
TURN_TEXT = {
    ("wait", "wait"): ("Both wait", "Nothing happens on this frame, but blue is not out of it. Red's turn slides "
                       "him closer, and one frame later blue faces another guess: red's chance over the remaining "
                       "7 frames is 0.5. The clip stops there.", [],
                       {185: "Frame 185: 12.39 apart. Blue has to guess again.", 187: "The clip ends here: the "
                        "position is still a guess, not a safe one."}, "guess again (0.5)"),
    ("wait", "out"): ("Red waits, blue steps away", "Blue turns to leave and red does nothing. Blue then plays "
                      "the first input the search proves safe for him here, a jab. Nobody is hit in the 8 frames "
                      "searched.", [],
                      {185: "Frame 185: blue jabs, the input the search proves safe.", 191: "Frame 191: the search "
                       "ends here. Nobody hit."}, "nobody hit"),
    ("wait", "shine"): ("Red waits, blue shines", "Blue shines. Red's turn has slid him to 12.75 and a turning Fox "
                        "is hit from further away than a standing one: blue lands the first hit, 5% to red. "
                        "Blue's own guesses hit too.", [(184, 1, 5.0)],
                        {184: "Frame 184: blue shines. It reaches red in his turn: 5% to red."}, "blue hits: 5%"),
    ("out", "wait"): ("Red steps away, blue waits", "Red dashes out again and blue stays put. Nobody is hit. Red "
                      "can walk back in and ask the same question again.", [],
                      {184: "Frame 184: red dashes away. Blue waits.", 191: "Frame 191: the search ends here. Nobody hit."},
                      "nobody hit"),
    ("out", "out"): ("Both step away", "Both leave. Nobody is hit.", [],
                     {184: "Frame 184: red dashes away, blue turns to leave.", 191: "Frame 191: the search ends "
                      "here. Nobody hit."}, "nobody hit"),
    ("out", "shine"): ("Red steps away, blue shines", "Blue shines, but red has dashed out of reach and the shine "
                       "touches nothing. Blue is stuck holding it. Red turns back and jabs from outside shine "
                       "range: 4%.", [(191, 2, 4.0)],
                       {184: "Frame 184: blue shines. Red has dashed away: no hit.", 187: "Frame 187: red turns back. "
                        "Blue is still in his shine.", 189: "Frame 189: red jabs.", 191: "Frame 191: the jab lands. 4%."},
                       "red hits: 4%"),
    ("shine", "wait"): ("Red shines, blue waits", "Red shines from 12.75. Against a standing Fox that is out of "
                        "reach, and blue stood still: no hit. Blue stays safe for the 8 frames searched.", [],
                        {184: "Frame 184: red shines. Blue is standing, out of reach: no hit.",
                         191: "Frame 191: the search ends here. Nobody hit."}, "nobody hit"),
    ("shine", "out"): ("Red shines, blue steps away", "Blue turns to leave. A turning Fox is hit from further away "
                       "than a standing one, and red's shine is out on the same frame: 5%.", [(184, 2, 5.0)],
                       {184: "Frame 184: red shines as blue turns to leave. 5%."}, "red hits: 5%"),
    ("shine", "shine"): ("Both shine", "Both shine on the same frame. The hitboxes clank: both freeze for 4 frames "
                         "and nobody takes damage.", [],
                         {184: "Frame 184: both shine. Clank: 0% to both.", 191: "Frame 191: the search ends "
                          "here. Nobody hit."}, "clank, nobody hit"),
}
LEDGE_TEXT = {
    ("shine", "wait"): ("Red shines, blue waits", "Blue is inside red's shine range and did nothing: 5%.",
                        [(1, 2, 5.0)], {1: "Frame 1: red shines. 5%."}, "red hits: 5%"),
    ("shine", "shine"): ("Both shine", "Both shine on the same frame. The hitboxes clank: both freeze for 4 frames "
                         "and nobody takes damage.", [],
                         {1: "Frame 1: both shine. Clank: 0% to both.", 8: "Frame 8: the search ends here. Nobody hit."},
                         "clank, nobody hit"),
    ("shield", "wait"): ("Red shields, blue waits", "Red put his shield up for nothing. Nobody is hit.", [],
                         {1: "Frame 1: red shields. Blue waits.", 8: "Frame 8: the search ends here. Nobody hit."},
                         "nobody hit"),
    ("shield", "shine"): ("Red shields, blue shines", "Blue's shine lands on red's shield. Hitting a shield pushes "
                          "the attacker back, and blue has no stage behind him: on frame 5 he slides off the ledge, "
                          "still stuck in his shine. Our rules count leaving the stage as a loss; what happens "
                          "after that was not played out.", [],
                          {1: "Frame 1: blue shines into red's shield. Both freeze for 4 frames.",
                           5: "Frame 5: the pushback slides blue off the stage. Counted as red's point.",
                           10: "Blue starts to fall, still holding his shine."}, "blue slides off"),
}


def door(sim: Sim, verbose: bool) -> list[dict]:
    """The widest gap at which every exit from shield is hit within 10 frames (section 13, Verification A)."""
    lead, marks = 8, [REACH, [14.4, "door 14.4"]]
    pre = force.corner(sim, 15.5, 12, 0, 12 - lead)
    root = force.corner(sim, 15.5, 12, 0, 12)
    assert round(sim.gap(), 2) == 14.39, sim.gap()
    S = nash.Nash(root, 10, dodge=True)
    clips = []
    for ex in EXITS[:5]:
        line = walk(S, ("wait", ex), 10, True)
        c = Clip(sim, pre).step(N, nash.MOVES["shield"], lead).start()
        for a, d in line:
            c.moves(a, d)
        c.step(n=14)
        title, cap, hits, notes = DOOR_TEXT.get(ex, (ex, "", None, {}))
        if verbose or hits is None:
            show(c, f"door, {ex}: {line} hits {c.hits()}")
        if hits is not None:
            expect(c, hits, f"door, {ex}: P1 plays {[a for a, _ in line]}")
        clips.append(c.data(ex, title, cap, {-lead: "Blue holds shield, 14.39 away. Red waits.", **notes}, marks))
    del S

    hit_on = {}
    for press in range(4, 20):
        c = Clip(sim, pre).step(N, nash.MOVES["shield"], lead).start().moves("wait", "spotdodge")
        c.step(n=press - 2).step(USMASH, N).step(n=30 - press)
        h = c.hits()
        if h:
            assert h[0][1:] == (2, 18.0) and len(h) == 1, h
            hit_on[press] = h[0][0]
    print(f"ok  door, spotdodge at 14.39: up smash pressed on frame -> 18% on frame {hit_on}")
    if not hit_on:
        raise SystemExit("MISMATCH in spotdodge: no up smash timing hits it from 14.39")
    press = min(hit_on)
    dodge = Clip(sim, pre).step(N, nash.MOVES["shield"], lead).start().moves("wait", "spotdodge")
    dodge.step(n=press - 2).step(USMASH, N).step(n=30 - press)
    alone = Clip(sim, root).start().moves("wait", "spotdodge").step(n=29)
    length = sum(alone.frame(f)[1][2] == 235 for f in range(1, 31))
    last_safe = max(f for f in range(1, 31) if dodge.frame(f)[1][8] == 1)
    assert length == 22, f"the spotdodge lasts {length} frames"
    print(f"ok  door, spotdodge: it lasts {length} frames, intangible through frame {last_safe}")
    f = hit_on[press]
    clips.append(dodge.data(
        "spotdodge", "Spotdodge", "Blue sidesteps on the spot (a spotdodge) and cannot be hit for most of it. Red "
        f"does not chase: he starts an up smash on frame {press} so that it lands on frame {f}, as the dodge wears "
        "off. 18%, the most expensive exit.",
        {-lead: "Blue holds shield, 14.39 away. Red waits.", 1: "Frame 1: blue spotdodges.",
         2: "Blue cannot be hit (dashed outline). Red has seen it and counts.", press: f"Frame {press}: red starts an up smash.",
         f: f"Frame {f}: the dodge has worn off and the up smash is there. 18%."}, marks))
    return clips


def hop5(sim: Sim, verbose: bool) -> list[dict]:
    """Five frames into the hop the attacker's shine is a forced hit on a defender who does not shield."""
    stand = force.corner(sim, 11.5, 12)
    root = force.corner(sim, 11.5, 12, 5)

    def start() -> Clip:
        return Clip(sim, stand).step(n=3).step((X, 40, 0, 0), N).step((0, 40, 0, 0), N, 4).start()

    c = start()
    assert c.frame(0)[0][:3] == [66.42, 3.97, 25] and c.gap() == 9.42, c.frame(0)
    S = nash.Nash(root, 24, no_shield=True)
    if not S.forced(0, 10, True):
        raise SystemExit("MISMATCH at hop frame 5: the solver finds no forced hit within 10 frames")
    print(f"ok  hop frame 5: forced hit within 10 frames ({S.expansions:,} simulator steps)")
    clips = []
    for d in ("wait", "out", "jab", "hop", "shine"):
        line = walk(S, ("shine", d), 10, True)
        c = start()
        for pa, pd in line:
            c.moves(pa, pd)
        c.step(n=12)
        title, cap, hits, notes = HOP5_TEXT.get(d, (d, "", None, {}))
        if verbose or hits is None:
            show(c, f"hop 5, blue {d}: {line} hits {c.hits()}")
        if hits is not None:
            expect(c, hits, f"hop 5, P2 {d}: P1 plays {[a for a, _ in line]}")
        clips.append(c.data(d, title, cap, {-8: "Red stands 10.19 from blue, who has his back to the ledge.",
                                            -4: "Red short-hops toward blue. Blue stands still.",
                                            0: "Red is 5 frames into the hop, 9.42 away and 4.0 up.", **notes}))
    del S
    return clips


def coin(sim: Sim) -> tuple[list[dict], dict]:
    """The four cells of the hop position, and its mixed strategy."""
    stand = force.corner(sim, 11.5, 12)
    hop_in = (X, 40, 0, 0), (0, 40, 0, 0)

    def start() -> Clip:
        c = Clip(sim, stand).step(n=3).step(hop_in[0], N)
        return c.step(hop_in[1], N, 8).start()

    root = force.corner(sim, 11.5, 12, 9)
    c = start()
    assert c.sim.save() == root or (c.frame(0)[0][:4] == [68.08, 9.15, 25, 5]), c.frame(0)
    S = nash.Nash(root, 8, no_shield=True)
    cells, value = {}, np.zeros((2, 2))
    for i, a in enumerate(("wait", "shine")):
        for j, d in enumerate(("out", "shine")):
            S.rb.checkpoint(0)
            S.joint(a, d)
            v = S.leaf()
            v = S.value(1, 7) if v is None else v
            S.back(0)
            value[i, j] = v
            cells[a, d] = walk(S, (a, d), 8, v == 1.0)
    del S
    sol = solve_matrix(value)
    if value.tolist() != [[0, 1], [1, 0]]:
        raise SystemExit(f"MISMATCH in the coin flip: cell values {value.tolist()}")
    g, _, _ = grid(("wait", "shine"), sol.row, ("out", "shine"), sol.col, float(sol.value), 8, value,
                   {"value": 0.5, "p1": {"wait": 50, "shine": 50}, "p2": {"out": 50, "shine": 50}})

    text = {
        ("wait", "out"): ("Red waits, blue steps away", "Red keeps falling and blue turns and dashes for "
                          "the ledge. Nobody is hit inside the 8 frames searched: blue guessed right. The search "
                          "ends with blue at the very edge of the stage; what comes after is not part of the result.",
                          [], {1: "Frame 1: red waits. Blue turns to run.", 3: "Blue dashes away, out of reach.",
                               8: "Frame 8: the search ends here, blue on the edge of the stage. Nobody hit."}),
        ("wait", "shine"): ("Red waits, blue shines", "Blue shines, but red is too high: it misses upward. "
                            "Blue is now stuck in his shine, and red shines down onto him a frame later: 5%.",
                            [(2, 2, 5.0)], {1: "Frame 1: blue shines. It cannot reach red. Red just waited.",
                                            2: "Frame 2: red shines from above. 5%."}),
        ("shine", "out"): ("Red shines, blue steps away", "Blue starts to turn and run, but red's shine from "
                           "above is out on the same frame and catches him before he has moved: 5%.",
                           [(1, 2, 5.0)], {1: "Frame 1: red shines as blue turns to run. 5%."}),
        ("shine", "shine"): ("Both shine", "Both shine on the same frame. Each is intangible (cannot be hit) on the "
                             "first frame of his shine, so neither is hit, and blue is safe for the 8 frames searched.",
                             [], {1: "Frame 1: both shine. Neither can be hit on that frame.",
                                  2: "Both hold the reflector. Red drifts down.",
                                  8: "Frame 8: the search ends here. Nobody hit."}),
    }
    clips = []
    for (a, d), line in cells.items():
        c = start()
        for pa, pd in line:
            c.moves(pa, pd)
        c.step(n=10 if text[a, d][2] else 0)  # an unhit line stops where the search does
        title, cap, hits, notes = text[a, d]
        expect(c, hits, f"coin flip, P1 {a} / P2 {'step away' if d == 'out' else d}: {line}")
        notes = {-12: "Red stands 10.19 from blue, who has his back to the ledge.",
                 -8: "Red short-hops toward blue. Blue stands still.", 0: "Red is 9 frames into the hop, 7.8 away and 9.2 up. "
                 "Both now choose at once.", **notes}
        v = int(value[("wait", "shine").index(a), ("out", "shine").index(d)])
        clips.append(c.data(f"{a}-{d}", title, cap, notes, value=v, tag="red hits: 5%" if v else "nobody hit"))
    return clips, g


def opening(sim: Sim) -> tuple[list[dict], bytes, bytes]:
    """The walk from the match start that ends in the guess (section 14), and the states 170 and 183 frames in."""
    start = sim.start()
    c = Clip(sim, start).step(WALK, N, 170)
    s170 = sim.save()
    c.step(WALK, N, 12).step(FLICK, N)
    s183 = sim.save()
    expect(c, [], "opening: P1 walks 182 frames and flicks the stick away, P2 waits")
    seen = [c.gap(0), c.gap(182), c.gap(183), c.frame(183)[0][2], c.frame(183)[0][3], c.frame(183)[1][2]]
    if seen != [120.0, 13.71, 13.19, 18, 1, 14]:
        raise SystemExit(f"MISMATCH in the opening line: gaps at frames 0, 182, 183 and the states are {seen}")
    close = next(f for f in range(183) if c.gap(f) <= 16.7)
    return [c.data("walk", "The walk in", "The match starts with the two Foxes 120 units apart. Red walks, never "
                   "dashes, for 182 frames (3 seconds), and blue stands and watches. On frame 183 red flicks his "
                   "stick away. That is the whole line.",
                   {0: "Match start: both at their spawns, 120 apart.", 1: "Red walks in. Blue waits.",
                    60: "Still far apart: nothing either does can reach yet.",
                    close: "Inside 17 units. Blue's list of safe inputs is getting shorter.",
                    182: "Frame 182: 13.71 apart. Stepping away is blue's last safe input here.",
                    183: "Frame 183: red flicks the stick away. 13.19 apart, and blue has no safe input left."},
                   [REACH], fps=60)], s170, s183


def turn(sim: Sim, s170: bytes, s183: bytes, verbose: bool) -> tuple[list[dict], dict]:
    """The guess after the walk in: the mixed strategy to 8 frames and one clip per pair of inputs in it."""
    fz = fortress.Fortress(s183, 12, add1=fortress.WALK, last=(FLICK, N))
    for h in (6, 8):
        if fz.safe_moves(h):
            raise SystemExit(f"MISMATCH after the walk in: the defender has safe inputs at {h} frames: {fz.safe_moves(h)}")
    v6 = fz.mix(6)[4]
    att, row, dfn, col, v = fz.mix(8)
    _, _, m = fz.matrix(0, 8)
    if abs(v6 - 0.25) > 1e-9:
        raise SystemExit(f"MISMATCH after the walk in: value at 6 frames {v6}")
    mix = {"wait": 50, "out": 25, "shine": 25}
    g, rows, cols = grid(att, row, dfn, col, v, 8, m, {"value": 0.25, "p1": mix, "p2": mix})
    clips = []
    for i, a in enumerate(rows):
        for j, d in enumerate(cols):
            val = g["cells"][i][j]
            line = walk(fz, (a, d), 8, val == 1.0) if val in (0.0, 1.0) else [(a, d)]
            c = Clip(sim, s170).at(170).step(WALK, N, 12).step(FLICK, N)
            for pa, pd in line:
                c.moves(pa, pd)
            c.step(n=10)
            title, cap, hits, notes, tag = TURN_TEXT.get((a, d), (f"{a}/{d}", "", None, {}, ""))
            if verbose or hits is None:
                show(c, f"turn, red {a} / blue {d}: value {val}, {line} hits {c.hits()}")
            if hits is not None:
                expect(c, hits, f"turn, P1 {a} / P2 {d} (value {val}): {line}")
            clips.append(c.data(f"{a}-{d}", title, cap, {
                170: "Red walks in. Blue waits.", 183: "Frame 183: red flicks the stick away. 13.19 apart.",
                184: "Frame 184: both choose at once.", **notes}, [REACH], value=val, tag=tag))
    del fz
    return clips, g


def retreat(sim: Sim, s170: bytes) -> list[dict]:
    """What the defender does instead: one dash back at 13.7, which costs him 21.6 units of stage."""
    c = Clip(sim, s170).at(170).step(WALK, N, 12).step(WALK, (0, 80, 0, 0), 2).step(WALK, N, 30)
    expect(c, [], "retreat: P2 dashes back at 13.71 while P1 keeps walking")
    x0, x1 = c.frame(182)[1][0], c.rows[-1][1][0]
    seen = [c.gap(182), round(x1 - x0, 2), round(EDGE - x1, 2)]
    if seen != [13.71, 21.62, 3.95]:
        raise SystemExit(f"MISMATCH in the retreat: gap before it, distance covered and room left are {seen}")
    stop = next(f for f in range(183, 215) if c.frame(f)[1][2] == 14)
    return [c.data("back", "Giving ground", "The same walk, but blue does not wait for the flick. At 13.71 apart he "
                   "dashes back: two frames of stick, and the dash carries him 21.62 units. He is out of danger, "
                   "and 3.95 units from the ledge.",
                   {170: "Red walks in. Blue waits.", 182: "Frame 182: 13.71 apart, the last safe moment.",
                    183: "Frame 183: blue dashes back.", 190: "Red keeps walking. Blue cannot be reached.",
                    stop: "Blue stops 3.95 from the ledge. He has spent 21.62 units of stage.",
                    stop + 6: "Red is still walking in. There is no room for a second dash like that."}, [REACH])]


def ledge(sim: Sim, verbose: bool) -> tuple[list[dict], dict]:
    """A defender standing on the ledge with the attacker 8.52 away: the mixed strategy and its four outcomes."""
    root = force.corner(sim, 10, 1)
    x2 = float(sim.players()[1]["pos_x"])
    assert round(sim.gap(), 2) == 8.52 and round(x2, 2) == 85.57, (sim.gap(), x2)
    fz = fortress.Fortress(root, 12)
    fz.load(root)
    if fz.safe_moves(8):
        raise SystemExit(f"MISMATCH on the ledge: the defender has safe inputs at 8 frames: {fz.safe_moves(8)}")
    att, row, dfn, col, v = fz.mix(8)
    _, _, m = fz.matrix(0, 8)
    g, rows, cols = grid(att, row, dfn, col, v, 8, m, {"value": 0.5, "p1": {"shine": 50, "shield": 50},
                                                       "p2": {"wait": 50, "shine": 50}})
    clips = []
    for i, a in enumerate(rows):
        for j, d in enumerate(cols):
            val = g["cells"][i][j]
            line = walk(fz, (a, d), 8, val == 1.0)
            c = Clip(sim, root).start()
            for pa, pd in line:
                c.moves(pa, pd)
            c.step(nash.MOVES["shield"] if a == "shield" and d == "shine" else N, N, 12)
            title, cap, hits, notes, tag = LEDGE_TEXT.get((a, d), (f"{a}/{d}", "", None, {}, ""))
            if verbose or hits is None:
                show(c, f"ledge, red {a} / blue {d}: value {val}, {line} hits {c.hits()}")
            if hits is not None:
                expect(c, hits, f"ledge, P1 {a} / P2 {d} (value {val}): {line}")
            clips.append(c.data(f"{a}-{d}", title, cap, {0: "Blue stands on the ledge. Red is 8.52 away. Both "
                                                         "choose at once.", **notes}, [REACH], value=val, tag=tag))
    del fz
    return clips, g


SCENES = ("standoff", "reach", "walk", "turn", "door", "hop5", "coin", "retreat", "ledge")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--only", nargs="+", choices=SCENES + ("setup",),
                    help="redo these scenes and keep the others as they are in the file; `setup` redoes only the lead-ins")
    ap.add_argument("--solver", type=Path, help="folder with squeeze-8.jsonl and net-*.txt: write road.json from them")
    ap.add_argument("--show", action="store_true", help="print every new clip frame by frame")
    ap.add_argument("--out", type=Path, default=OUT, help="the file to write (default: the one the page reads)")
    args = ap.parse_args()
    todo = set(args.only or SCENES)
    old = json.loads(args.out.read_text()) if args.only and args.out.exists() else {"scenes": []}
    sim = Sim()
    made: dict[str, dict] = {}
    if "standoff" in todo:
        made["standoff"] = {"clips": standoff(sim)}
    if "reach" in todo:
        made["reach"] = {"clips": reach(sim)}
    if "door" in todo:
        made["door"] = {"clips": door(sim, args.show)}
    if "hop5" in todo:
        made["hop5"] = {"clips": hop5(sim, args.show)}
    if "coin" in todo:
        clips, g = coin(sim)
        made["coin"] = {"clips": clips, "grid": g}
    if todo & {"walk", "turn", "retreat"}:
        clips, s170, s183 = opening(sim)
        if "walk" in todo:
            made["walk"] = {"clips": clips}
        if "turn" in todo:
            clips, g = turn(sim, s170, s183, args.show)
            made["turn"] = {"clips": clips, "grid": g}
        if "retreat" in todo:
            made["retreat"] = {"clips": retreat(sim, s170)}
    if "ledge" in todo:
        clips, g = ledge(sim, args.show)
        made["ledge"] = {"clips": clips, "grid": g}
    kept = {s["id"]: s for s in old["scenes"]}
    scenes = [{"id": k, **made[k]} if k in made else kept[k] for k in SCENES if k in made or k in kept]
    for scene in scenes:  # cheap replays, so always redone
        if scene["id"] in SETUPS:
            args_, caption, end, want = SETUPS[scene["id"]]
            scene["setup"] = lead_in(sim, *args_, caption=caption, end=end, want=want)
    actions = {str(a): label(a) for s in scenes for c in s["clips"] + ([s["setup"]] if "setup" in s else [])
               for row in c["rows"] for a in (row[0][2], row[1][2])}
    data = {"ledge": EDGE, "names": ["Red · attacker", "Blue · defender"], "actions": actions, "scenes": scenes}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(data, separators=(",", ":")) + "\n")
    print(f"wrote {sum(len(s['clips']) for s in scenes)} clips in {len(scenes)} scenes, {args.out.stat().st_size // 1024} KB, "
          f"into {args.out}")
    if args.solver:
        path = args.out.parent / "road.json"
        path.write_text(json.dumps(road(args.solver), separators=(",", ":")) + "\n")
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
