"""The fortress: a Fox who is never hit first, as a policy that can be played, and attackers to break it.

Each frame the defender (P2) takes the first input, in order of preference (wait first), such that whatever the
attacker (P1) presses on that frame, the position reached is still safe for a lookahead of `H` frames: P2 has
inputs that avoid a clean first hit even if P1 sees each one (`Nash.forced(..., attacking=False)`). A position
with no such input is a crack: it is saved and the defender falls back to the exact mixed strategy of a shorter
horizon. Because a safe position has a safe input by definition, a hit is always preceded by a crack.

Rules on top of `nash.py`, all against the defender:
- he never starts a shield while P1 is free to act within 15 units, and a shield with a free P1 within 14.4
  counts as hit (the one-way door, section 13 of docs/optimal-play.md);
- an early spotdodge beside a standing or shining P1 counts as hit (`--dodge`);
- leaving the stage counts as hit.

A crack is never a false alarm at its own horizon. A matrix game with payoffs in [0, 1] is worth 0 only if one
column is all zeros, so by induction a position is worth 0 to H frames exactly when P2 has a defence that holds
when read. No safe input therefore means P1 has a positive chance of a clean first hit within H frames. The same
holds when positions already found to be cracks count as lost: that is `learn`, which marks each crack in a file
shared by all games, takes the game back to the last position that still has a safe input, and resumes there.
The marked set is the outside of the fortress as far as the attackers have found it.

One shortcut, measured (`scripts/solver_probes/fortress/reach.py`) and tested: a standing P2 further than
`REACH + SPEED * (frames - 1)` from P1 cannot be hit within `frames` frames by a P1 who is not already rolling, so that position is safe unsearched.

    scripts/fortress.sh NAME -- map@8 hopc@6 chase@6 learn@6   # suites of section 14, resumable
    python -m melee_llm.solver.fortress play --attacker hop:14:in:shine --frames 300
"""
from __future__ import annotations

import argparse
import collections
import json
import multiprocessing as mp
import os
import pickle
import signal
import time

import melee
import numpy as np

from melee_llm.solver import force, nash
from melee_llm.solver.force import N
from melee_llm.solver.matrix import solve as solve_matrix

EDGE = 85.57  # Final Destination's ledges
NEAR = 15.0  # no new shield while a free P1 is this close
DOOR = 14.4  # the one-way door as verified
REACH, SPEED = 23.0, 2.6  # measured 21.9 (a jab out of a turn) and 2.4 a frame outside a roll (reach.py), plus a margin
_ROLLS = (melee.Action.ROLL_FORWARD.value, melee.Action.ROLL_BACKWARD.value)  # 4.8 a frame, but 31 frames long
_STAND = melee.Action.STANDING.value
# what the defender tries first: staying put, then moving, then the moves that commit him
PREF = ("wait", "out", "in", "hop", "jump", "shine", "hold_b", "jab", "nair", "grab", "release", "jump_oos", "upb",
        "usmash", "spotdodge", "shield", "roll_out", "roll_in", "shield_grab")
WALK = {"ground": ("walk_in", "walk_out")}
FULL = {"squat": ("jump",)}


class Fortress(nash.Nash):
    _slots = None

    def __init__(self, root: bytes, frames: int = 12, tt_mb: int = 300, reach: bool = True, add1: dict | None = None,
                 last: tuple = (N, N)):
        super().__init__(root, frames + 6, tt_mb=tt_mb, trap=True, dodge=True, add1=add1)
        self.reach, self.last = reach, last
        self.bad: set[int] = set()  # positions found to have no safe input: reaching one counts as unsafe

    # the simulator's view is rebuilt on every read: keep it until the state changes
    def slots(self):
        if self._slots is None:
            self._slots = super().slots()
        return self._slots

    def step(self, p1, p2) -> None:
        self._slots = None
        super().step(p1, p2)

    def observe(self) -> None:
        self._slots = None
        super().observe()

    def load(self, state: bytes, last: tuple = (N, N)) -> None:
        """Put the match in `state`, reached with `last` as the previous frame's inputs."""
        self.env.restore(0, state)
        self.rb.rebase()
        self.env.reset_cursor()
        self.observe()
        self.last = last
        s = self.slots()
        self.base = (float(s[0]["percent"]), float(s[1]["percent"]), int(s[0]["stocks"]), int(s[1]["stocks"]))

    def menus(self):
        s = self.slots()
        att, dfn = self.m1[nash.kind(s[0])], self.m2[nash.kind(s[1])]
        if "shield" in dfn and nash.kind(s[1]) == "ground" and int(s[0]["action_id"]) in force._FREE \
                and abs(float(s[1]["pos_x"]) - float(s[0]["pos_x"])) <= NEAR:
            dfn = tuple(m for m in dfn if m != "shield")
        return att, dfn

    def shut(self, s) -> bool:
        return (int(s[1]["action_id"]) in (178, 179, 182) and int(s[0]["action_id"]) in force._FREE
                and abs(float(s[1]["pos_x"]) - float(s[0]["pos_x"])) <= DOOR and float(s[0]["pos_y"]) == float(s[1]["pos_y"]))

    def damage(self) -> tuple[float, float]:
        """What each has taken since the root, a grab counting as a hit."""
        s = self.slots()
        return (float(s[0]["percent"]) - self.base[0] + 100 * (self.base[2] - int(s[0]["stocks"]))
                + (int(s[0]["action_id"]) in nash._HELD),
                float(s[1]["percent"]) - self.base[1] + 100 * (self.base[3] - int(s[1]["stocks"]))
                + (int(s[1]["action_id"]) in nash._HELD))

    def leaf(self) -> float | None:
        v = super().leaf()
        if v is None and abs(float(self.slots()[1]["pos_x"])) > EDGE:
            return 1.0
        return v

    def gap(self) -> float:
        s = self.slots()
        return abs(float(s[1]["pos_x"]) - float(s[0]["pos_x"]))

    def far(self, frames: int) -> bool:
        """P2 stands still and P1, not rolling and in no special move but the shine, is too far to hit him within
        `frames` (a roll begun now ends after any horizon used here)."""
        s = self.slots()
        return (int(s[1]["action_id"]) == _STAND and abs(float(s[1]["speed_ground_x_self"])) < 0.01
                and (int(s[0]["action_id"]) < 341 or int(s[0]["action_id"]) in force._SHINE)
                and int(s[0]["action_id"]) not in _ROLLS
                and self.gap() > REACH + SPEED * (frames - 1))

    def forced(self, depth: int, frames: int, attacking: bool) -> bool:
        if not attacking and frames > 0:
            if self.reach and self.far(frames):
                return True
            if self.bad and hash(self.where() + (False,)) in self.bad:
                return False
        return super().forced(depth, frames, attacking)

    def learn(self, path: str) -> None:
        """Take in the positions other games have marked. What was proven safe before may pass through them."""
        if os.path.exists(path):
            with open(path) as f:
                keys = {json.loads(line)["key"] for line in f}
            if not keys <= self.bad:
                self.bad |= keys
                self.no.clear()

    def mark(self, path: str, spec: str, t: int) -> None:
        """The current position has no safe input: by the argument in the module docstring its value is above 0."""
        v = self.view()
        key = hash(self.where() + (False,))
        self.bad.add(key)
        self.no.clear()
        with open(path, "a") as f:
            f.write(json.dumps({"key": key, "t": t, "gap": round(v["gap"], 2), "p1": name(v["a1"]), "f1": v["f1"],
                                "y1": round(v["y1"], 1), "p2": name(v["a2"]), "f2": v["f2"],
                                "ledge": round(v["ledge2"], 1), "spec": spec}) + "\n")

    def holds(self, depth: int, a: str, d: str, H: int) -> bool:
        """After this pair of inputs, is P2 unhit and still safe for H - 1 frames?"""
        self.joint(a, d)
        v = self.leaf()
        ok = self.forced(depth + 1, H - 1, False) if v is None else v == 0.0
        self.back(depth)
        return ok

    def safe_moves(self, H: int, depth: int = 0, first: bool = False) -> list[str]:
        """P2's inputs that keep him safe for H frames whatever P1 presses now, in order of preference."""
        if self.reach and depth == 0 and self.far(H + 1) and "wait" in self.menus()[1] and first:
            return ["wait"]
        att, dfn = self.menus()
        self.rb.checkpoint(depth)
        out = []
        for d in sorted(dfn, key=PREF.index):
            if all(self.holds(depth, a, d, H) for a in att):
                out.append(d)
                if first:
                    break
        return out

    def punish(self, depth: int, frames: int) -> str | None:
        """An input of P2's that lands his own clean first hit within `frames` whatever P1 does, if there is one."""
        att, dfn = self.menus()
        self.rb.checkpoint(depth)
        for d in dfn:
            ok = True
            for a in att:
                self.joint(a, d)
                d1, d2 = self.damage()
                if d1 == 0 and d2 == 0 and self.leaf() is None:
                    ok = frames > 1 and self.punish(depth + 1, frames - 1) is not None
                else:
                    ok = d1 > 0 and d2 == 0
                self.back(depth)
                if not ok:
                    break
            if ok:
                return d
        return None

    def mix(self, frames: int) -> tuple[tuple, np.ndarray, tuple, np.ndarray, float]:
        """The exact matrix game here to `frames`: both menus, both optimal mixes, the value."""
        att, dfn, m = self.matrix(0, frames)
        sol = solve_matrix(m)
        return att, np.asarray(sol.row), dfn, np.asarray(sol.col), float(sol.value)

    def exact(self, run):
        """`run()` with the check that every rollback was exact, repeated with the missed page added if not."""
        while True:
            self.rb.rebase()
            out = run()
            missed = self.rb.verify()
            if not len(missed):
                return out
            self.rb.add(missed)
            self.rb.restore(missed)
            self.observe()
            self.values.clear()
            self.yes.clear()
            self.no.clear()

    def view(self) -> dict:
        s = self.slots()
        x1, x2 = float(s[0]["pos_x"]), float(s[1]["pos_x"])
        return {"gap": abs(x2 - x1), "x1": x1, "x2": x2, "y1": float(s[0]["pos_y"]), "y2": float(s[1]["pos_y"]),
                "k1": nash.kind(s[0]), "k2": nash.kind(s[1]), "a1": int(s[0]["action_id"]),
                "a2": int(s[1]["action_id"]), "f1": int(s[0]["action_frame"]), "f2": int(s[1]["action_frame"]),
                "ledge2": EDGE - abs(x2), "side": 1 if x2 >= x1 else -1}


# ---------------------------------------------------------------------------------------------- attackers

class Attacker:
    """A plan for P1: `pick` returns a move name; one not on his menu this frame becomes a wait."""
    spec = ""
    done = False
    add1: dict | None = None

    def pick(self, fz: Fortress, t: int, H: int, d: str) -> str:
        raise NotImplementedError


class Script(Attacker):
    """Scripted plans. `spec` is kind:arg:arg..., for example hop:14:in:shine or walk:10.

    walk:G      walk in to G, stand 40 frames                      dash:G     dash in, let go at G, stand 40
    through     run through him and on for 12 frames, twice         dd:G       dash-dance at G for 150 frames
    retreat:G   in to G, out to 40, three times                     shield:G   in to G, hold shield 90 frames
    hop:G:DRIFT:ATK[:full]   stand at G, short (or full) hop with the stick in, wait or out; ATK is none, a shine
                or nair on air frame 5, land (a shine on landing), or late (a shine on air frame 9)
    crowd       hold 17 units from him for 300 frames, following, hopping at him every 45
    stalk:G     walk in to G, then flick the stick away every other frame, following when he leaves
    """

    def __init__(self, spec: str):
        self.spec, self.t0, self.phase, self.n, self.air, self.side0 = spec, 0, 0, 0, 0, 0
        p = spec.split(":")
        self.kind, self.args = p[0], p[1:]
        self.g = float(self.args[0]) if self.args and self.kind != "crowd" else 17.0
        if self.kind in ("walk", "hop", "stalk"):
            self.add1 = dict(WALK, **(FULL if spec.endswith(":full") else {}))

    def _next(self, t: int) -> None:
        self.phase, self.t0 = self.phase + 1, t

    def pick(self, fz, t, H, d):
        v = fz.view()
        gap, k, since = v["gap"], v["k1"], t - self.t0
        air = self.air = self.air + 1 if k == "air" else 0
        kind = self.kind
        if kind == "stalk":  # the opening line of section 14, for ever: walk to G, flick the stick away, walk on
            self.done = t >= 650
            return "walk_in" if gap > self.g else "out" if t % 2 else "wait"
        if kind in ("walk", "hop") and self.phase == 0:  # get to G on foot and stand
            if gap > self.g and not (t == 0 and gap < self.g + 1.5):  # walking: a run that brakes slides 25 units
                return "walk_in"
            self._next(t)
            return "wait"
        if kind == "walk":
            self.done = since >= 40
            return "walk_in" if gap > self.g else "wait"
        if kind == "hop":
            drift, atk = self.args[1], self.args[2]
            if self.phase == 1:
                if since >= 10 and k == "ground":
                    self._next(t)
                    return "hop"
                return "wait"
            if self.phase == 2:
                if k == "squat":
                    return "jump" if self.spec.endswith(":full") and since < 3 else drift
                if k == "air":
                    if atk in ("shine", "nair") and air == 5 or atk == "late" and air == 9:
                        return "shine" if atk == "late" else atk
                    return drift
                if k == "ground" and since > 4:
                    self._next(t)
                    return "shine" if atk == "land" else "wait"
                return "wait"
            self.done = since >= 30
            return "wait"
        if kind == "dash":
            if self.phase == 0:
                if gap > self.g:
                    return "in"
                self._next(t)
            self.done = since >= 40
            return "wait"
        if kind == "through":
            if self.phase % 2 == 0:
                self.side0 = self.side0 or v["side"]
                if v["side"] == self.side0:
                    return "in"
                self.side0 = 0
                self._next(t)
            if since < 12:
                return "out"
            self._next(t)
            self.done = self.phase >= 4
            return "wait"
        if kind == "dd":
            if self.phase == 0:
                if gap > self.g + 6:
                    return "in"
                self._next(t)
            self.done = since >= 150
            return "in" if (since // 6) % 2 and gap > self.g - 3 else "out"
        if kind == "retreat":
            if self.phase % 2 == 0:
                if gap > self.g:
                    return "in"
                self._next(t)
            if gap < 40:
                return "out"
            self._next(t)
            self.done = self.phase >= 6
            return "wait"
        if kind == "shield":
            if self.phase == 0:
                if gap > self.g:
                    return "in"
                self._next(t)
            self.done = since >= 90
            return "shield"
        if kind == "crowd":
            self.done = t >= 300
            if k == "ground" and t % 45 == 44 and gap < 24:
                return "hop"
            if k in ("squat", "air"):
                return "in"
            return "in" if gap > self.g + 4 else "wait"
        raise ValueError(self.spec)


class Random(Attacker):
    """Random inputs, each held for 1 to 10 frames; closes in when further than 28 units."""

    def __init__(self, seed: int):
        self.spec, self.rng, self.move, self.left = f"random:{seed}", np.random.default_rng(seed), "wait", 0

    def pick(self, fz, t, H, d):
        menu = fz.menus()[0]
        if fz.gap() > 28 and "in" in menu:
            self.left = 0
            return "in"
        if self.left <= 0 or self.move not in menu:
            self.move, self.left = str(self.rng.choice(menu)), int(self.rng.integers(1, 11))
        self.left -= 1
        return self.move


class Adversary(Attacker):
    """Knows the defender's policy: plays the input after which he has the fewest safe inputs (ties: at random
    among those that do not open the distance). He counts with a lookahead of at most 6: deeper is too slow."""

    def __init__(self, seed: int, h: int = 0):
        self.spec, self.rng, self.h = f"adv:{seed}", np.random.default_rng(seed), h

    def pick(self, fz, t, H, d):
        if fz.gap() > 30:
            return "in"
        att, _ = fz.menus()
        g0 = fz.gap()
        fz.rb.checkpoint(0)
        best = []
        for a in att:
            fz.joint(a, d)
            v = fz.leaf()
            n = (-1 if v == 1.0 else 99) if v is not None else len(fz.safe_moves(min(self.h or H, 6), 1))
            if 0 < n < 99 and fz.punish(1, 2):  # not an input that hands P2 a hit
                n = 98
            closer = fz.gap() <= g0 + 0.01
            fz.back(0)
            best.append((n, not closer, float(self.rng.random()), a))
        return min(best)[3]


class Chase(Adversary):
    """chase:G:SEED: walks in from the opening and stops at G, then plays as the adversary. Walking to 12.4 is
    what makes this defender dash back to the ledge."""
    add1 = WALK

    def __init__(self, g: float, seed: int):
        super().__init__(seed)
        self.spec, self.g, self.walking = f"chase:{g:g}:{seed}", g, True

    def pick(self, fz, t, H, d):
        self.walking = self.walking and fz.gap() > self.g
        return "walk_in" if self.walking else super().pick(fz, t, H, d)


def attacker(spec: str) -> Attacker:
    kind, _, arg = spec.partition(":")
    if kind == "chase":
        return Chase(float(arg.split(":")[0]), int(arg.split(":")[1]))
    return Random(int(arg)) if kind == "random" else Adversary(int(arg)) if kind == "adv" else Script(spec)


# ---------------------------------------------------------------------------------------------- one game

def name(a: int) -> str:
    try:
        return melee.Action(a).name
    except ValueError:
        return str(a)


def play(fz: Fortress, att: Attacker, frames: int, H: int, state: bytes, last: tuple = (N, N), hs: int = 6,
         punish: int = 0, seconds: float = 1e9, seed: int = 0, cracks_dir: str | None = None, tag: str = "",
         crack_cap: int = 4, learn: str | None = None) -> dict:
    """One game from `state`: the fortress policy at lookahead `H` against `att`, until the first hit, the
    attacker's plan ends, `frames` or `seconds`. With `punish`, P2 takes a clean first hit he can force within that
    many frames.

    At a crack, without `learn`: the position is saved and P2 plays the exact mix of horizon `hs` until he is safe
    again. With `learn` (a file shared by all games): the position is marked, the game is taken back frame by
    frame, marking every position that has no safe input once the marked ones count as lost, and resumes from the
    first one that has; the attacker resumes from there too. Returns the result with every crack."""
    fz.load(state, last)
    if learn:
        fz.learn(learn)
    rng = np.random.default_rng(seed)
    ring: collections.deque = collections.deque(maxlen=41)
    inputs: list[tuple[str, str]] = []
    cracks, t0, steps0 = [], time.time(), fz.expansions
    result, in_crack, min_gap, min_ledge, shields = "survived", False, 1e9, 1e9, 0
    t = 0
    while t < frames:
        if time.time() - t0 > seconds or att.done:
            break
        v = fz.view()
        min_gap, min_ledge = min(min_gap, v["gap"]), min(min_ledge, v["ledge2"])
        ring.append((t, fz.env.save(0), fz.last, pickle.dumps(att)))
        d = fz.exact(lambda: fz.punish(0, punish)) if punish and v["gap"] < 22 else None
        row = None
        if d is None:
            safe = fz.exact(lambda: fz.safe_moves(H, first=True))
            if safe:
                d, in_crack = safe[0], False
            elif learn:
                fz.mark(learn, att.spec, t)
                k = 1
                while k < len(ring):
                    fz.load(*ring[-1 - k][1:3])
                    if fz.exact(lambda: fz.safe_moves(H, first=True)):
                        break
                    fz.mark(learn, att.spec, ring[-1 - k][0])
                    k += 1
                cracks.append({"t": t, "H": H, "view": v, "p1": name(v["a1"]), "p2": name(v["a2"]), "back": k,
                               "last30": inputs[-30:]})
                if k == len(ring) or len(cracks) > 400:
                    result = "no safe input in the last 40 frames" if len(ring) == 41 else "no safe input since the start"
                    break
                t, st, lst, saved = ring[-1 - k]
                for _ in range(k + 1):
                    ring.pop()
                fz.load(st, lst)
                att = pickle.loads(saved)
                del inputs[t:]
                continue
            else:
                matt, row, mdfn, col, val = fz.exact(lambda: fz.mix(hs))
                d = str(rng.choice(mdfn, p=col / col.sum()))
                if not in_crack:
                    in_crack = True
                    crack = {"t": t, "H": H, "view": v, "p1": name(v["a1"]), "p2": name(v["a2"]),
                             "value_hs": round(val, 4), "hs": hs, "last30": inputs[-30:]}
                    if cracks_dir and len(cracks) < crack_cap:
                        crack["file"] = os.path.join(cracks_dir, f"{tag}_{t}.pkl")
                        back = {k: ring[-1 - k] for k in (0, 10, 20, 40) if k < len(ring)}
                        with open(crack["file"], "wb") as f:
                            pickle.dump({"spec": att.spec, "H": H, "t": t, "back": back, "add1": att.add1}, f)
                    cracks.append(crack)
        if row is not None and isinstance(att, Adversary):  # at a crack the adversary plays the game's own mix
            a = str(rng.choice(matt, p=row / row.sum()))
        else:
            a = att.pick(fz, t, H, d)
            if a not in fz.menus()[0]:
                a = "wait"
        shields += d == "shield"
        inputs.append((a, d))
        fz.joint(a, d)
        t += 1
        d1, d2 = fz.damage()
        if d1 or d2 or fz.leaf() is not None:
            result = "trade" if d1 and d2 else "P1 hit" if d1 else "P2 hit" if d2 else "P2 trapped"
            break
    return {"spec": att.spec, "H": H, "frames": t, "result": result, "cracks": cracks, "min_gap": round(min_gap, 2),
            "min_ledge": round(min_ledge, 2), "shields": shields, "seconds": round(time.time() - t0, 1),
            "steps": fz.expansions - steps0, "inputs": inputs if result != "survived" or cracks else inputs[-5:],
            "end": fz.view()}


class _Timeout(Exception):
    pass


def _alarm(*_):
    raise _Timeout


def classify(fz: Fortress, state: bytes, last: tuple, horizons=(4, 6, 8, 10), seconds: float = 600) -> dict:
    """The exact value of a crack at growing horizons, as far as `seconds` allow, and the verdict at the deepest:
    false alarm (0), guess, or forced (1)."""
    values, t0 = {}, time.time()
    signal.signal(signal.SIGALRM, _alarm)
    for h in horizons:
        left = seconds - (time.time() - t0)
        if left < 1:
            break
        fz.load(state, last)
        fz.rb.rebase()
        signal.alarm(int(left))
        try:
            values[h] = round(fz.value(0, h), 4)
            signal.alarm(0)
        except _Timeout:
            fz.rb.reset()
            fz.observe()
            for table in (fz.values, fz.yes, fz.no):
                table.clear()
            break
    v = values[max(values)] if values else None
    return {"values": values, "verdict": None if v is None else "false alarm" if v == 0 else "forced" if v == 1 else "guess"}


# ---------------------------------------------------------------------------------------------- suites

def start_state(start: str) -> bytes:
    """`start` is "start" (the match start) or corner:GAP:LEDGE (P2 standing LEDGE from the ledge, P1 GAP away)."""
    sim = force.Sim()
    if start == "start":
        state = sim.start()
    else:
        _, gap, ledge = start.split(":")
        state = force.corner(sim, float(gap), float(ledge))
    sim.world.close()
    return state


_FZ: dict = {}


def _fz(state: bytes, add1: dict | None, tt_mb: int = 300) -> Fortress:
    key = json.dumps(add1, sort_keys=True)
    if key not in _FZ:
        _FZ.clear()
        _FZ[key] = Fortress(state, add1=add1, tt_mb=tt_mb)
    return _FZ[key]


def _game(job: dict) -> dict:
    state = start_state(job.get("start", "start"))
    att = attacker(job["spec"])
    fz = _fz(state, att.add1)
    out = play(fz, att, job["frames"], job["H"], state, punish=job.get("punish", 0), seconds=job.get("seconds", 1e9),
               seed=job.get("seed", 0), cracks_dir=job.get("cracks"), tag=job["id"])
    for c in out["cracks"]:  # solve every crack exactly, then try to avoid the real ones from earlier
        if "file" not in c:
            continue
        with open(c["file"], "rb") as f:
            saved = pickle.load(f)
        _, st, last, _ = saved["back"][0]
        fz.values.clear()
        c.update(classify(fz, st, last, seconds=job.get("classify", 300)))
        if c["verdict"] in ("guess", "forced"):
            c["walkback"] = walkback(fz, saved, job["H"] + 2, seconds=job.get("classify", 300))
    return {"job": job, **out}


def walkback(fz: Fortress, saved: dict, H: int, seconds: float = 300) -> dict:
    """Replay the game from 10, 20 and 40 frames before a crack with a deeper lookahead: does the crack go away?"""
    out = {}
    for k, (t, st, last, att) in saved["back"].items():
        if not k:
            continue
        r = play(fz, pickle.loads(att), k + 20, H, st, last, seconds=seconds / 3)
        out[k] = {"H": H, "frames": r["frames"], "result": r["result"],
                  "cracks": [(c["t"], c["value_hs"]) for c in r["cracks"]]}
    return out


def _back(job: dict) -> dict:
    """One step of the walk back from a saved crack: the position `k` frames before it, solved exactly as deep as
    half of `seconds` allows, then replayed against the same attacker with the lookahead `H`."""
    with open(job["wb"], "rb") as f:
        saved = pickle.load(f)
    t, st, last, att = saved["back"][job["k"]]
    fz = _fz(st, saved["add1"])
    t0 = time.time()
    out = classify(fz, st, last, horizons=(6, 8, 10, 12), seconds=job["seconds"] / 2)
    att = pickle.loads(att)
    if isinstance(att, Adversary):
        att.h = 6  # the adversary keeps the lookahead he found the crack with
    r = play(fz, att, job["k"] + 25, job["H"], st, last, seconds=job["seconds"] / 2)
    v = fz.view()
    return {"job": job, "t": t, **out, "replay": {k: r[k] for k in ("frames", "result", "inputs", "min_gap", "min_ledge")},
            "replay_cracks": [(c["t"], c["value_hs"], round(c["view"]["gap"], 2), c["p1"], c["p2"]) for c in r["cracks"]],
            "seconds": round(time.time() - t0, 1)}


def _learn(job: dict) -> dict:
    """Game after game from the opening (or `start`) against one attacker (a new seed each round), all games sharing the file
    of marked positions, until `seconds` are used."""
    state, t0, rounds = start_state(job.get("start", "start")), time.time(), []
    kind, _, seed = job["spec"].rpartition(":")
    while time.time() - t0 < job["seconds"]:
        scripted = kind.split(":")[0] not in ("chase", "adv", "random")  # a script has no seed: the same plan again
        att = attacker(job["spec"] if scripted else f"{kind}:{int(seed) * 100 + len(rounds)}")
        fz = _fz(state, att.add1)
        r = play(fz, att, job["frames"], job["H"], state, punish=job.get("punish", 0), seed=len(rounds),
                 seconds=min(job["round"], job["seconds"] - (time.time() - t0)), learn=job["learn"])
        rounds.append({"spec": att.spec, "frames": r["frames"], "result": r["result"], "cracks": len(r["cracks"]),
                       "marked": sum(c["back"] for c in r["cracks"]), "deepest": max([c["back"] for c in r["cracks"]] or [0]),
                       "first_crack_t": min([c["t"] for c in r["cracks"]] or [-1]), "min_gap": r["min_gap"],
                       "min_ledge": r["min_ledge"], "seconds": r["seconds"], "tail": r["inputs"][-12:]})
    return {"job": job, "rounds": rounds, "seconds": round(time.time() - t0, 1)}


def _map(job: dict) -> dict:
    """Both standing, P2 `ledge` from the ledge and P1 `gap` away: is P2 safe for H frames, and with which inputs?"""
    state = start_state(f"corner:{job['gap']}:{job['ledge']}")
    fz = _fz(state, None)
    fz.load(state)
    t0 = time.time()
    moves = fz.exact(lambda: fz.safe_moves(job["H"]))
    return {"job": job, "gap": round(fz.gap(), 2), "safe": moves, "seconds": round(time.time() - t0, 1)}


_HOPS = (("in", "shine"), ("in", "late"), ("in", "land"), ("wait", "nair"), ("out", "none"))
def _value(job: dict) -> dict:
    """The exact value of the standing position of `_map`, as deep as `seconds` allow."""
    state = start_state(f"corner:{job['gap']}:{job['ledge']}")
    fz = _fz(state, None)
    fz.load(state)
    t0, gap = time.time(), round(fz.gap(), 2)
    return {"job": job, "gap": gap, **classify(fz, state, (N, N), seconds=job["seconds"]),
            "seconds": round(time.time() - t0, 1)}


LEARN_SECONDS = 2100
WB_GAMES = ("chase-6-start-chase_13_2", "chase-6-start-chase_14_1", "chase-6-start-chase_16_3")
SUITES = {  # name -> the games at lookahead H; every game also stops after its `seconds`
    "scripted": lambda H: [{"spec": s, "H": H, "frames": 700, "punish": 3, "seconds": 240} for s in
                           [f"dash:{g}" for g in (30, 24, 20, 16, 12, 8)] + ["through", "crowd"]
                           + [f"dd:{g}" for g in (22, 16, 12)] + [f"retreat:{g}" for g in (20, 14)]
                           + [f"shield:{g}" for g in (20, 14, 10)]],
    "scripted-few": lambda H: [{"spec": s, "H": H, "frames": 700, "punish": 3, "seconds": 600} for s in
                               ("dash:12", "crowd")],
    "walk": lambda H: [{"spec": f"walk:{g}", "H": H, "frames": 700, "punish": 3, "seconds": 200}
                       for g in range(30, 4, -4)],
    "hop": lambda H: [{"spec": f"hop:{g}:{drift}:{atk}", "H": H, "frames": 500, "punish": 3, "seconds": 200}
                      for i, g in enumerate(range(10, 31, 2)) for drift, atk in (_HOPS[i % 5], _HOPS[(i + 2) % 5])],
    "hop-few": lambda H: [{"spec": f"hop:{g}:{drift}:{atk}", "H": H, "frames": 500, "punish": 3, "seconds": 400}
                          for g in (12, 16, 20) for drift, atk in _HOPS[:3:2]],
    "fullhop": lambda H: [{"spec": f"hop:{g}:{drift}:{atk}:full", "H": H, "frames": 500, "punish": 3, "seconds": 200}
                          for g in range(10, 31, 4) for drift, atk in _HOPS[:3:2]],
    # the hops again from a standing start at each distance, mid-stage, the defender only defending
    "hopc": lambda H: [{"spec": f"hop:{g}:{drift}:{atk}", "H": H, "frames": 200, "seconds": 120 if H < 8 else 300,
                        "start": f"corner:{g}:60"}
                       for i, g in enumerate(range(10, 31, 2) if H < 8 else (12, 16))
                       for drift, atk in (_HOPS[i % 5], _HOPS[(i + 2) % 5])]
    + [{"spec": f"hop:{g}:in:{atk}:full", "H": H, "frames": 200, "seconds": 120, "start": f"corner:{g}:60"}
       for g in (10, 14, 18, 22, 26, 30)[:6 if H < 8 else 0] for atk in ("shine",)],
    "random": lambda H: [{"spec": f"random:{i}", "H": H, "frames": 4000, "seconds": 300 if i < 6 else 60, "seed": i}
                         for i in range(16)],
    "adv": lambda H: [{"spec": f"adv:{i}", "H": H, "frames": 3000, "seconds": 600 if i < 3 else 200, "seed": i}
                      for i in range(11)],
    "mirror": lambda H: [{"spec": f"random:{i}", "H": H, "frames": 4000, "seconds": 300 if i < 23 else 60, "seed": i,
                          "punish": 4} for i in range(20, 29)],
    "chase": lambda H: [{"spec": f"chase:{g}:{i}", "H": H, "frames": 1500, "seconds": 420 if H < 8 else 900, "seed": i, "punish": p}
                        for i, (g, p) in enumerate(((14, 0), (14, 3), (13, 0), (16, 0), (14, 0), (13, 3), (12, 0))[:7 if H < 8 else 3])],
    "ledge-few": lambda H: [{"spec": s, "H": H, "frames": 400, "seconds": 400, "start": f"corner:{g}:{ledge}", "seed": 1}
                            for ledge, g, s in ((6, 16, "adv:7"), (1, 16, "dash:10"), (6, 20, "crowd"))],
    "ledge": lambda H: [{"spec": s, "H": H, "frames": 400, "seconds": 500, "start": f"corner:{g}:{ledge}", "seed": 1}
                        for ledge in (1, 6) for g, s in ((16, "hop:14:in:shine"), (16, "dash:10"), (20, "crowd"),
                                                         (16, "adv:7"), (16, "random:9"))],
}


def run(suites: list[str], H: int, out: str, workers: int) -> None:
    """`suites`: names from SUITES or "map", each optionally NAME@H; run in the order given."""
    cracks = os.path.join(os.path.dirname(out), "cracks")
    jobs = []
    for s in suites:
        s, _, h = s.partition("@")
        h = int(h or H)
        if s == "learn":
            jobs += [{"id": f"learn-{h}-{spec}".replace(":", "_"), "spec": spec, "H": h, "frames": 700, "round": 400,
                      "seconds": LEARN_SECONDS, "learn": os.path.join(os.path.dirname(out), f"bad-{h}.jsonl"), "punish": p}
                     for spec, p in (("chase:14:1", 0), ("chase:13:2", 0), ("chase:16:3", 0), ("chase:12:4", 0),
                                     ("chase:15:5", 3), ("adv:6", 0))]
        elif s == "final":  # the same attackers with new seeds against the fortress as marked so far
            jobs += [{"id": f"final-{h}-{spec}".replace(":", "_"), "spec": spec, "H": h, "frames": 700, "round": 200,
                      "seconds": 420, "learn": os.path.join(os.path.dirname(out), f"bad-{h}.jsonl"), "punish": p}
                     for spec, p in (("chase:14:51", 0), ("chase:13:52", 0), ("chase:16:53", 0), ("chase:12:54", 0),
                                     ("chase:15:55", 3), ("adv:56", 0), ("chase:14:57", 3))]
            jobs += [{"id": f"final-{h}-{start}-{spec}".replace(":", "_"), "spec": spec, "H": h, "frames": 400, "round": 200,
                      "seconds": 420, "learn": os.path.join(os.path.dirname(out), f"bad-{h}.jsonl"), "start": start}
                     for spec, start in (("hop:14:in:land", "corner:14:60"), ("adv:58", "corner:16:6"),
                                         ("adv:59", "corner:16:1"))]
        elif s == "stalk":  # cornering: the opening line repeated, the fortress learning as it goes
            jobs += [{"id": f"stalk-{h}-{spec}-{p}".replace(":", "_"), "spec": spec, "H": h, "frames": 700, "round": 420,
                      "seconds": 840, "learn": os.path.join(os.path.dirname(out), f"bad-{h}.jsonl"), "punish": p}
                     for spec, p in (("stalk:13.7", 0), ("stalk:14.3", 0), ("stalk:13.2", 0), ("stalk:13.7", 3))]
        elif s == "stalk2":  # the same without creeping closer than G
            jobs += [{"id": f"stalk2-{h}-{spec}-{p}".replace(":", "_"), "spec": spec, "H": h, "frames": 900, "round": 400,
                      "seconds": 400, "learn": os.path.join(os.path.dirname(out), f"bad-{h}.jsonl"), "punish": p}
                     for spec, p in (("stalk:13.7", 0), ("stalk:14.3", 0), ("stalk:13.2", 0), ("stalk:13.7", 3))]
        elif s == "wb":  # walk back from every real crack found so far in games from the opening
            with open(out) as f:
                for r in map(json.loads, f):
                    jobs += [{"id": f"wb-{h}-{c['file'].split('/')[-1]}-{k}", "wb": c["file"], "k": k, "H": h, "seconds": 600}
                             for c in r.get("cracks", []) if c.get("verdict") in ("guess", "forced")
                             and r["job"]["id"] in WB_GAMES for k in (10, 20)]
        elif s == "values2":
            jobs += [{"id": f"value-{ledge}-{gap}", "value": 1, "gap": gap, "ledge": ledge, "seconds": 480}
                     for ledge, gap in ((60, 13), (12, 13), (60, 14))]
        elif s == "values":
            jobs += [{"id": f"value-{ledge}-{gap}", "value": 1, "gap": gap, "ledge": ledge, "seconds": 240}
                     for ledge, gap in ((60, 11.5), (60, 12), (1, 11.5), (60, 11), (1, 8.5), (60, 5))]
        elif s == "map":
            jobs += [{"id": f"map-{h}-{ledge}-{gap}", "map": 1, "gap": gap, "ledge": ledge, "H": h}
                     for ledge in (60, 12, 6, 1) for gap in (5, 7, 8.5, 10, 11, 12, 13, 14, 16, 20, 26)]
        else:
            jobs += [dict(j, suite=s, id=f"{s}-{h}-{j.get('start', 'start')}-{j['spec']}".replace(":", "_"),
                          cracks=cracks, classify=120) for j in SUITES[s](h)]
    os.makedirs(cracks, exist_ok=True)
    done = set()
    if os.path.exists(out):
        with open(out) as f:
            done = {json.loads(line)["job"]["id"] for line in f}
    todo = [j for j in jobs if j["id"] not in done]
    print(f"{len(jobs)} jobs, {len(todo)} to run, {workers} processes", flush=True)
    with mp.get_context("spawn").Pool(workers, maxtasksperchild=6) as pool, open(out, "a") as log:
        for r in pool.imap_unordered(_dispatch, todo):
            log.write(json.dumps(r, default=float) + "\n")
            log.flush()
            print(r["job"]["id"], r.get("result", r.get("safe", r.get("values", r.get("error")))), r.get("replay_cracks"),
                  [(x["result"], x["cracks"], x["marked"]) for x in r.get("rounds", [])], r.get("frames"),
                  len(r.get("cracks", [])), r.get("seconds"), flush=True)


def _dispatch(job: dict) -> dict:
    try:
        return (_map(job) if "map" in job else _value(job) if "value" in job else _back(job) if "wb" in job
                else _learn(job) if "learn" in job else _game(job))
    except Exception as e:  # one broken game must not stop the rest; it is in the file as an error
        import traceback
        _FZ.clear()
        return {"job": job, "error": f"{e!r} {traceback.format_exc()[-600:]}"}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("play", help="one game, printed")
    p.add_argument("--attacker", default="random:0")
    p.add_argument("--start", default="start")
    p.add_argument("--frames", type=int, default=300)
    p.add_argument("--H", type=int, default=8)
    p.add_argument("--punish", type=int, default=0)
    s = sub.add_parser("suite", help="named sets of games, in parallel, appended to --out and resumable")
    s.add_argument("names", nargs="+", help="from: map " + " ".join(SUITES) + ", each optionally NAME@H")
    s.add_argument("--H", type=int, default=8)
    s.add_argument("--workers", type=int, default=7)
    s.add_argument("--out", default="data/fortress/games.jsonl")
    args = ap.parse_args()
    if args.cmd == "suite":
        run(args.names, args.H, args.out, min(args.workers, force.fit_workers(args.workers, 300)))
        return
    r = _game({"id": "play", "spec": args.attacker, "H": args.H, "frames": args.frames, "start": args.start,
               "punish": args.punish})
    print(json.dumps({k: v for k, v in r.items() if k != "inputs"}, indent=1, default=float))
    print(" ".join(f"{a}/{d}" for a, d in r["inputs"]))


if __name__ == "__main__":
    main()
