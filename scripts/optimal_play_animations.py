"""Record the simulator traces behind docs/animations/optimal-play.html and embed them in that file.

Every clip is a frame-by-frame recording of two Foxes in melee-sim-light: positions, action, facing, percent,
shield health and the inputs pressed. The attacker's lines in the shield and hop scenes are not scripted: they are
walked out of the solver (`nash.Nash.forced`), then replayed and recorded. Each clip is checked against what
docs/optimal-play.md (section 13) says before it is written; a mismatch stops the script.

    MSL_DATA_DIR=vendor/melee-sim-light/data PYTHONPATH=. uv run python scripts/optimal_play_animations.py
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import melee
import numpy as np

from melee_llm.solver import force, nash
from melee_llm.solver.game import A, B, R, X, Z, Sim
from melee_llm.solver.matrix import solve as solve_matrix

HTML = Path(__file__).resolve().parent.parent / "docs" / "animations" / "optimal-play.html"
N = (0, 0, 0, 0)
USMASH = (A, 0, 80, 0)
BUTTONS = ((A, "A"), (B, "B"), (X, "X"), (Z, "Z"), (R, "R"))
LABELS = {14: "standing", 18: "turning", 20: "dash", 24: "jumpsquat", 25: "short hop", 42: "landing", 44: "jab",
          63: "up smash", 178: "shield", 179: "shield", 182: "shield", 180: "dropping shield", 212: "grab",
          233: "roll in", 234: "roll away", 235: "spotdodge", 360: "shine", 361: "shine (held)", 365: "shine",
          366: "shine (held)"}
EXITS = ("release", "jump_oos", "roll_in", "roll_out", "shield_grab", "spotdodge")


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

    def data(self, key: str, title: str, caption: str, notes: dict[int, str], marks=()) -> dict:
        return {"id": key, "title": title, "caption": caption, "lead": self.lead, "rows": self.rows,
                "notes": sorted(notes.items()), "marks": list(marks)}


def expect(clip: Clip, hits: list[tuple[int, int, float]], what: str) -> None:
    got = clip.hits()
    if got != hits:
        raise SystemExit(f"MISMATCH in {what}: expected hits {hits} (frame, player, percent), simulator gave {got}")
    print(f"ok  {what}: {got or 'nobody hit'}")


def walk(S: nash.Nash, first: tuple[str, str], frames: int, attacking: bool) -> list[tuple[str, str]]:
    """Play `first`, then follow the pure line the solver proves: P1's forced hit (`attacking`), preferring the
    shine as soon as it is forced, or P2's safe defence against a P1 who waits. The other side takes the answer
    that keeps the game going, waiting if he can. Returns the pairs of moves, ending at the hit or the horizon."""
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
        pick = next((m for m in (("shine", "wait") if attacking else ()) if m in picks), picks[0])
        alive = []
        for y in theirs:
            S.joint(*((pick, y) if attacking else (y, pick)))
            if S.leaf() is None:
                alive.append(y)
            S.back(depth)
        ans = "wait" if "wait" in alive or not alive else alive[0]
        pair = (pick, ans) if attacking else (ans, pick)
        S.joint(*pair)
        line.append(pair)
        depth += 1
        frames -= 1
    S.back(0)
    return line


def standoff(sim: Sim) -> list[dict]:
    wait = Clip(sim, force.corner(sim, 14, 12)).start().step(n=30)
    expect(wait, [], "standoff, both wait 30 frames")
    assert wait.gap() == 12.59, wait.gap()

    close = force.corner(sim, 8, 12)
    clank = Clip(sim, close).step(n=6).start().moves("shine", "shine").step(n=16)
    expect(clank, [], "same-frame grounded shines")
    assert [clank.frame(f)[p][7] for f in (1, 4, 5) for p in (0, 1)] == [4, 4, 1, 1, 0, 0], "clank hitlag"

    early = Clip(sim, close).step(n=6).start().moves("shine", "wait").moves("wait", "shine").step(n=16)
    expect(early, [(1, 2, 5.0)], "shine one frame earlier")
    g = clank.gap()
    return [
        wait.data("wait", "Both wait", "Two Foxes 12.59 units apart, orange with his back 12 units from the ledge. "
                  "Solved 8 frames deep, blue's chance of landing a clean first hit is 0, and the best play for "
                  "both is this: nothing.", {1: "Both wait. Whatever either starts, the other sees one frame later."}),
        clank.data("clank", "Same-frame shines", f"Up close ({g} units) both press shine on the same frame. The two "
                   "hitboxes clank: both freeze for 4 frames and nobody takes damage.",
                   {-6: "Standing in each other's shine range.", 1: "Frame 1: both shine. The hitboxes meet.",
                    2: "Clank: 4 frames of freeze, 0% to both.", 5: "Both are left holding the reflector. Nothing happened."}),
        early.data("early", "One frame earlier", "Same spot, but blue presses one frame before orange. The shine "
                   "hits on the frame it is pressed, so orange's shine never comes out: 5%.",
                   {-6: "Standing in each other's shine range.", 1: "Frame 1: blue shines. It hits at once: 5%.",
                    2: "Frame 2: orange presses shine too, but he is already hit."}),
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
        miss.data("miss", "Standing, 12.6 away", "Blue shines at a standing Fox from 12.59 units. It comes out on "
                  "frame 1 and touches nothing.", {-6: "12.59 apart: outside shine range.", 1: "Frame 1: shine. No hit.",
                                                    2: "Blue is now stuck in the shine for a few frames."}, marks),
        hit.data("hit", f"Standing, {hit.gap():.1f} away", f"One step closer, at {hit.gap()} units, the same shine hits "
                 f"for 5%. From {edge.gap()} it still misses: the reach against a standing Fox is about 10.7.",
                 {-6: f"{hit.gap()} apart: inside shine range.", 1: "Frame 1: shine. 5%."}, marks),
        squat.data("squat", "Jumpsquat, 12.6 away", "Back at 12.59. Orange presses jump; for 3 frames he crouches on "
                   "the ground before leaving it. In that crouch the shine reaches him.",
                   {-6: "12.59 apart again.", 1: "Frame 1: orange starts a jump (jumpsquat).",
                    2: "Frame 2: blue shines. It reaches: 5%."}, marks),
        roll.data("roll", "Roll start, 12.6 away", "Orange rolls away out of shield from 12.59. In the first frames "
                  "of the roll the shine reaches him too, before he has moved or become intangible.",
                  {-6: "Orange in shield, 12.59 away.", 1: "Frame 1: orange starts rolling away.",
                   2: "Frame 2: blue shines. It reaches: 5%."}, marks),
    ]


def door(sim: Sim) -> list[dict]:
    lead = 8
    pre = force.corner(sim, 14, 12, 0, 12 - lead)
    root = force.corner(sim, 14, 12, 0, 12)
    S = nash.Nash(root, 10)
    text = {
        "release": ("Let go", "Orange lets go of the shield. Dropping it takes several frames in which he can do "
                    "nothing, and the shine reaches him there. Blue sees it on frame 2 and shines: 5%."),
        "jump_oos": ("Jump", "Orange jumps out of shield. The jump starts with 3 frames of crouch on the ground, "
                     "and blue's shine reaches that crouch from 12.59: 5% before orange leaves the floor."),
        "roll_in": ("Roll in", "Orange rolls toward blue. Blue turns his back first, which is how the solver makes "
                    "the shine reach here, then shines the start of the roll: 5%."),
        "roll_out": ("Roll away", "Orange rolls toward the ledge. The roll takes time to get going; blue shines "
                     "its first frames from where he stands: 5%."),
        "shield_grab": ("Shield grab", "Orange grabs out of shield. The grab cannot reach 12.59 units. Blue waits "
                        "while it comes out and shines on frame 7, the frame the solver finds: 5%."),
    }
    seen = {"release": "he dropped the shield", "jump_oos": "the jumpsquat", "roll_in": "the roll",
            "roll_out": "the roll", "shield_grab": "the grab"}
    clips = []
    for ex in EXITS[:5]:
        line = walk(S, ("wait", ex), 10, True)
        c = Clip(sim, pre).step(N, nash.MOVES["shield"], lead).start()
        for a, d in line:
            c.moves(a, d)
        c.step(n=14)
        f = len(line)
        expect(c, [(f, 2, 5.0)], f"door, {ex}: P1 plays {[a for a, _ in line]}")
        notes = {-lead: "Orange holds shield. Blue waits.", 1: f"Frame 1: orange leaves the shield ({text[ex][0].lower()}).",
                 2: f"Frame 2: blue has now seen {seen[ex]}."}
        if line[1][0] == "out":
            notes[2] = "Frame 2: blue has seen the roll, and turns around."
        if f > 3:
            notes[3] = "Blue waits: the grab cannot reach him."
        notes[f] = f"Frame {f}: blue shines. 5%." if f > 2 else "Frame 2: blue has seen it, and shines. 5%."
        clips.append(c.data(ex, *text[ex], notes, [[12.6, "12.6"]]))
    del S

    hit_on = {}
    for press in range(6, 17):
        c = Clip(sim, pre).step(N, nash.MOVES["shield"], lead).start().moves("wait", "spotdodge")
        c.step(n=press - 2).step(USMASH, N).step(n=26 - press)
        h = c.hits()
        if h:
            assert h[0][1:] == (2, 18.0) and len(h) == 1, h
            hit_on[press] = h[0][0]
            if press == 9:
                dodge = c
    want = {9: 16, 10: 17, 11: 17, 12: 18, 13: 19, 14: 20}
    if {k: v for k, v in hit_on.items() if k in want} != want or min(hit_on) != 9:
        raise SystemExit(f"MISMATCH in spotdodge: up smash pressed on frame -> hit on frame {hit_on}; docs say {want}")
    print(f"ok  door, spotdodge: up smash pressed on frame -> 18% on frame {hit_on}")
    alone = Clip(sim, root).start().moves("wait", "spotdodge").step(n=29)
    length = sum(alone.frame(f)[1][2] == 235 for f in range(1, 31))
    assert length == 22 and dodge.frame(15)[1][8] == 1, f"the spotdodge lasts {length} frames"
    print(f"ok  door, spotdodge: it lasts {length} frames, intangible through frame 15")
    clips.append(dodge.data(
        "spotdodge", "Spotdodge", "Orange sidesteps on the spot and is intangible for most of it. Blue does not "
        "chase: he starts an up smash on frame 9 so that it lands on frame 16, right as the intangibility ends. "
        "18%, the most expensive exit.",
        {-lead: "Orange holds shield. Blue waits.", 1: "Frame 1: orange spotdodges.",
         2: "Orange is intangible (dashed). Blue has seen it and counts.", 9: "Frame 9: blue starts an up smash.",
         16: "Frame 16: the intangibility ends and the up smash is there. 18%."}, [[12.6, "12.6"]]))
    return clips


def coin(sim: Sim) -> tuple[list[dict], bytes]:
    """The four cells of the hop position, and its root for the last scene."""
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
    if value.tolist() != [[0, 1], [1, 0]] or abs(sol.value - 0.5) > 1e-9:
        raise SystemExit(f"MISMATCH in the coin flip: cell values {value.tolist()}, game value {sol.value}")
    print(f"ok  coin flip: cells (rows wait/shine, columns step back/shine) {value.tolist()}, value {sol.value:.2f}, "
          f"P1 mixes {np.round(sol.row, 2).tolist()}, P2 mixes {np.round(sol.col, 2).tolist()}")

    text = {
        ("wait", "out"): ("Blue waits, orange steps back", "Blue keeps falling and orange turns and dashes for "
                          "the ledge. Nobody is hit inside the 8 frames solved: orange guessed right.",
                          [], {1: "Frame 1: blue waits. Orange turns to run.", 3: "Orange dashes away, out of reach.",
                               8: "Frame 8: the solved horizon ends. Nobody hit."}),
        ("wait", "shine"): ("Blue waits, orange shines", "Orange shines, but blue is too high: it misses upward. "
                            "Orange is now stuck in his shine, and blue shines down onto him a frame later: 5%.",
                            [(2, 2, 5.0)], {1: "Frame 1: orange shines. It cannot reach blue. Blue just waited.",
                                            2: "Frame 2: blue shines from above. 5%."}),
        ("shine", "out"): ("Blue shines, orange steps back", "Orange starts to turn and run, but blue's shine from "
                           "above is out on the same frame and catches him before he has moved: 5%.",
                           [(1, 2, 5.0)], {1: "Frame 1: blue shines as orange turns to run. 5%."}),
        ("shine", "shine"): ("Both shine", "Both shine on the same frame. Each is intangible on the first frame of "
                             "his shine, so neither is hit, and orange is safe for the 8 frames solved.",
                             [], {1: "Frame 1: both shine. Both are intangible: no hit.",
                                  2: "Both hold the reflector. Blue drifts down.",
                                  8: "Frame 8: the solved horizon ends. Nobody hit."}),
    }
    clips = []
    for (a, d), line in cells.items():
        c = start()
        for pa, pd in line:
            c.moves(pa, pd)
        c.step(n=10 if text[a, d][2] else 2)
        title, cap, hits, notes = text[a, d]
        expect(c, hits, f"coin flip, P1 {a} / P2 {'step back' if d == 'out' else d}: {line}")
        notes = {-12: "Blue short-hops at the cornered orange.", 0: "Blue is 9 frames into the hop, 7.8 away and 9.2 up. "
                 "Both now choose at once.", **notes}
        clips.append({**c.data(f"{a}-{d}", title, cap, notes), "cell": [a, d], "value": int(value[("wait", "shine").index(a),
                                                                                             ("out", "shine").index(d)])})
    return clips, stand


def checkmate(sim: Sim, stand: bytes) -> list[dict]:
    """Hop, the defender shields at the coin-flip position, the attacker lands, the defender tries to jump out."""
    c = Clip(sim, stand).step(n=3).start().step((X, 40, 0, 0), N).step((0, 40, 0, 0), N, 8)
    air = c.frame(9)[0]
    assert air[:3] == [68.08, 9.15, 25], air
    shield = nash.MOVES["shield"]
    while c.rows[-1][0][2] != 42 or c.rows[-1][0][3] < 9:  # until blue has landed and stopped sliding
        c.step(N, shield)
    landed = next(f for f in range(1, 60) if c.frame(f)[0][2] == 42)
    held = len(c.rows) - 1 - c.lead
    root = sim.save()
    gap = round(c.rows[-1][1][0] - c.rows[-1][0][0], 2)
    S = nash.Nash(root, 10)
    forced = {}
    for ex in EXITS:
        S.rb.checkpoint(0)
        S.joint("wait", ex)
        forced[ex] = S.leaf() == 1.0 or (S.leaf() is None and S.forced(1, 9, True))
        S.back(0)
    print(f"ok  checkmate idea: blue lands on frame {landed}; on frame {held} he stands {gap} from the shield. "
          f"Forced hit within 10 frames against each exit from there: {forced}")
    if not all(forced[e] for e in EXITS[:5]):
        raise SystemExit(f"MISMATCH in the checkmate idea: exits that are not hit after the landing: {forced}")
    line = walk(S, ("wait", "jump_oos"), 10, True)
    del S
    sim.restore(root)
    for a, d in line:
        c.moves(a, d)
    c.step(n=14)
    f = held + len(line)
    expect(c, [(f, 2, 5.0)], f"checkmate idea, jump out of shield on frame {held + 1}: P1 plays {[a for a, _ in line]}")
    return [c.data("idea", "The whole line", "The line from a standing start: the hop, the shield it forces, the landing, "
                   "and orange trying to jump out.", {
        -3: "Orange is cornered, 12 units from the ledge. Blue stands 10.2 away.",
        1: "Frame 1: blue short-hops toward him.",
        4: "Blue rises. Orange has stood still so far: that part is assumed, not solved.",
        9: "Frame 9: the coin-flip position. Without a shield orange loses half the time…",
        10: "…so he shields. That is his only safe move here.",
        landed: f"Frame {landed}: blue lands almost on top of the shield, and the two are pushed apart.",
        landed + 5: f"Blue is free to act, {gap} from a shield. The door is shut.",
        held + 1: f"Frame {held + 1}: orange tries to jump out.",
        f: f"Frame {f}: blue shines the jumpsquat. 5%.",
    })]


def main() -> None:
    sim = Sim()
    coin_clips, stand = coin(sim)
    scenes = [
        {"id": "standoff", "clips": standoff(sim)},
        {"id": "reach", "clips": reach(sim)},
        {"id": "door", "clips": door(sim)},
        {"id": "coin", "clips": coin_clips},
        {"id": "idea", "clips": checkmate(sim, stand)},
    ]
    actions = {a: label(a) for s in scenes for c in s["clips"] for row in c["rows"] for a in (row[0][2], row[1][2])}
    blob = json.dumps({"ledge": 85.57, "actions": actions, "scenes": scenes}, separators=(",", ":")).replace("</", "<\\/")
    page = HTML.read_text()
    new, n = re.subn(r'(<script type="application/json" id="traces">).*?(</script>)',
                     lambda m: m.group(1) + blob + m.group(2), page, flags=re.S)
    assert n == 1, "traces block not found in the page"
    HTML.write_text(new)
    print(f"wrote {sum(len(s['clips']) for s in scenes)} clips, {len(blob) // 1024} KB, into {HTML}")


if __name__ == "__main__":
    main()
