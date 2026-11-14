"""Slippi replay events from melee-sim-light frames, so learned bots can read the simulator like Dolphin.

Learned bots parse the raw Slippi event stream with their own libmelee build (melee_llm/bots/server.py). This
writes that stream (spec: github.com/project-slippi/slippi-wiki/blob/master/SPEC.md, version 3.19.0, what our
Dolphin writes) from the simulator's observations and the raw inputs that produced them: one byte string per
frame (Frame Start, Pre-Frame per player, Item Updates, Post-Frame per player, stage events, Frame Bookend),
after Event Payloads + Game Start for the first frame.

Fields the simulator does not report are written as 0: last hitting attack, combo count, last hit by, most
state bit flags (hitlag, hitstun, shield and dead are derived), last ground id, L-cancel status, animation index,
instance ids, the processed-button stick direction bits, and hitstun outside hitstun. Action frames are whole
numbers (Dolphin has fractions for some actions), and pre-frame position/action are the previous post-frame's. `decode` reads events back by the same tables; `round_trip` (and
`python -m melee_llm.sim.slippi REPLAY.slp`) compares every field with a Dolphin replay.
"""
from __future__ import annotations

import math
import struct
import sys
from collections import Counter
from pathlib import Path

import melee
import numpy as np

VERSION = (3, 19, 0)
GAME_START, PRE, POST, GAME_END, FRAME_START, ITEM, BOOKEND, FOD, WHISPY = 0x36, 0x37, 0x38, 0x39, 0x3A, 0x3B, 0x3C, 0x3F, 0x40
SIZES = {GAME_START: 0x2F8, PRE: 0x42, POST: 0x54, GAME_END: 0x6, FRAME_START: 0xC, ITEM: 0x2C, BOOKEND: 0x8,
         FOD: 0x9, WHISPY: 0x5}  # payload bytes after the command byte, as our Dolphin's Event Payloads lists them

# (offset, struct code, name) per event, from the spec
PRE_FIELDS = ((0x1, "i", "frame"), (0x5, "B", "port"), (0x6, "B", "follower"), (0x7, "I", "seed"),
              (0xB, "H", "action"), (0xD, "f", "x"), (0x11, "f", "y"), (0x15, "f", "facing"),
              (0x19, "f", "main_x"), (0x1D, "f", "main_y"), (0x21, "f", "c_x"), (0x25, "f", "c_y"),
              (0x29, "f", "trigger"), (0x2D, "I", "processed_buttons"), (0x31, "H", "buttons"),
              (0x33, "f", "l"), (0x37, "f", "r"), (0x3B, "b", "raw_x"), (0x3C, "f", "percent"),
              (0x40, "b", "raw_y"), (0x41, "b", "raw_cx"), (0x42, "b", "raw_cy"))
POST_FIELDS = ((0x1, "i", "frame"), (0x5, "B", "port"), (0x6, "B", "follower"), (0x7, "B", "character"),
               (0x8, "H", "action"), (0xA, "f", "x"), (0xE, "f", "y"), (0x12, "f", "facing"), (0x16, "f", "percent"),
               (0x1A, "f", "shield"), (0x1E, "B", "last_attack"), (0x1F, "B", "combo"), (0x20, "B", "last_hit_by"),
               (0x21, "B", "stocks"), (0x22, "f", "action_frame"), (0x26, "B", "flags1"), (0x27, "B", "flags2"),
               (0x28, "B", "flags3"), (0x29, "B", "flags4"), (0x2A, "B", "flags5"), (0x2B, "f", "misc_as"),
               (0x2F, "B", "airborne"), (0x30, "H", "ground"), (0x32, "B", "jumps"), (0x33, "B", "l_cancel"),
               (0x34, "B", "hurtbox"), (0x35, "f", "speed_air_x"), (0x39, "f", "speed_y"), (0x3D, "f", "speed_attack_x"),
               (0x41, "f", "speed_attack_y"), (0x45, "f", "speed_ground_x"), (0x49, "f", "hitlag"),
               (0x4D, "I", "animation"), (0x51, "H", "instance_hit_by"), (0x53, "H", "instance"))
ITEM_FIELDS = ((0x1, "i", "frame"), (0x5, "H", "type"), (0x7, "B", "state"), (0x8, "f", "facing"), (0xC, "f", "vel_x"),
               (0x10, "f", "vel_y"), (0x14, "f", "x"), (0x18, "f", "y"), (0x1C, "H", "damage"), (0x1E, "f", "timer"),
               (0x22, "I", "spawn_id"), (0x26, "B", "misc0"), (0x27, "B", "misc1"), (0x28, "B", "misc2"),
               (0x29, "B", "misc3"), (0x2A, "b", "owner"), (0x2B, "H", "instance"))
TABLES = {PRE: PRE_FIELDS, POST: POST_FIELDS, ITEM: ITEM_FIELDS}

# Slippi's external character ids (Game Start); libmelee's Character enum holds the internal ones
EXTERNAL = tuple(melee.Character[n] for n in (
    "CPTFALCON", "DK", "FOX", "GAMEANDWATCH", "KIRBY", "BOWSER", "LINK", "LUIGI", "MARIO", "MARTH", "MEWTWO", "NESS",
    "PEACH", "PIKACHU", "POPO", "JIGGLYPUFF", "SAMUS", "YOSHI", "ZELDA", "SHEIK", "FALCO", "YLINK", "DOC", "ROY",
    "PICHU", "GANONDORF"))
_STICK_SCALE, _DEADZONE = 80, 22  # Melee zeroes an axis at |raw| <= 22 (0.2875 = 23/80 is the first live value)
_LR, _Z, _A, _ANY_TRIGGER = 0x0060, 0x0010, 0x0100, 0x80000000
_DEAD = {a.value for a in melee.Action if a.name.startswith("DEAD_")}
_SHIELD = {a.value for a in (melee.Action.SHIELD_START, melee.Action.SHIELD, melee.Action.SHIELD_RELEASE,
                             melee.Action.SHIELD_STUN, melee.Action.SHIELD_REFLECT)}


def _pack(code: int, fields, values: dict) -> bytes:
    buf = bytearray(SIZES[code] + 1)
    buf[0] = code
    for off, fmt, name in fields:
        struct.pack_into(">" + fmt, buf, off, values.get(name, 0))
    return bytes(buf)


def processed_stick(raw_x: int, raw_y: int) -> tuple[float, float]:
    """The stick Melee reads from a raw input: clamped to the unit circle (HSD_PadClampCheck3, truncating), then
    each axis zeroed inside the deadzone. This is what Slippi records as the processed joystick."""
    x, y = int(raw_x), int(raw_y)
    r = np.float32(math.sqrt(float(np.float32(x * x + y * y))))
    if r > _STICK_SCALE:
        x, y = int(np.float32(x) * np.float32(_STICK_SCALE) / r), int(np.float32(y) * np.float32(_STICK_SCALE) / r)
    axis = lambda v: 0.0 if abs(v) <= _DEADZONE else float(np.float32(v) / np.float32(_STICK_SCALE))
    return axis(x), axis(y)


def _pre_inputs(row) -> dict:
    """Pre-frame input fields from one raw input row (melee_sim layout), None for the countdown's first frame."""
    if row is None:
        return {}
    buttons = int(row["buttons"])
    mx, my, cx, cy = (int(row[k]) for k in ("main_x", "main_y", "c_x", "c_y"))
    left, right = int(row["l"]) / 140, int(row["r"]) / 140
    main, c = processed_stick(mx, my), processed_stick(cx, cy)
    trigger = max(left, right)
    if trigger <= 0.3:  # below the analog shield threshold (ftCommonData) the game reads no trigger
        trigger = 0.0
    if buttons & _LR:
        trigger = 1.0
    elif buttons & _Z:
        trigger = 0.35
    # Z also counts as A; the stick direction bits (0x000F0000, 0x00F00000) follow no rule we could fit and nothing
    # we feed reads them (libmelee parses the low 16 bits, HAL the physical buttons), so they stay 0
    processed = buttons | (_A if buttons & _Z else 0) | (_ANY_TRIGGER if trigger else 0)
    return {"main_x": main[0], "main_y": main[1], "c_x": c[0], "c_y": c[1], "trigger": trigger,
            "processed_buttons": processed, "buttons": buttons, "l": left, "r": right,
            "raw_x": mx, "raw_y": my, "raw_cx": cx, "raw_cy": cy}


class Encoder:
    """Slippi events for one game. `ports[i]` is the libmelee port of melee_sim source player i."""

    def __init__(self, stage: melee.Stage, ports: list[int], costumes: dict[int, int] | None = None,
                 stocks: int = 4, timer_s: int = 480):
        from melee_llm.sim.state import SIM_STAGE
        self.stage, self.ports, self.stocks, self.timer_s = stage, ports, stocks, timer_s
        self.stage_id = SIM_STAGE[stage]
        self.costumes = costumes or {}
        self.prev: dict[tuple[int, int], dict] = {}  # (port, follower) -> last post values, for the next pre-frame
        self.fod: list[float | None] = [None, None]
        self.whispy = None
        self.started = False

    def game_start(self, obs, seed: int) -> bytes:
        sizes = b"".join(struct.pack(">BH", c, s) for c, s in SIZES.items())
        payloads = bytes([0x35, len(sizes) + 1]) + sizes
        buf = bytearray(SIZES[GAME_START] + 1)
        buf[0] = GAME_START
        buf[1:4] = bytes(VERSION)
        struct.pack_into(">BB", buf, 0x5, 0x32, 0x01)  # stock mode, countdown timer (bitfields 1-2)
        struct.pack_into(">bb", buf, 0x5 + 0xB, -1, -1)  # items off, self-destruct score -1 (is teams at 0x8 stays 0)
        struct.pack_into(">H", buf, 0x5 + 0xE, self.stage_id)
        struct.pack_into(">I", buf, 0x5 + 0x10, self.timer_s)
        struct.pack_into(">f", buf, 0x5 + 0x30, 1.0)
        chars = {self.ports[int(s["source_player"])]: int(s["char_id"]) for s in obs["slots"]
                 if int(s["source_player"]) < len(self.ports)}
        for i in range(4):
            base = 0x5 + 0x60 + 0x24 * i
            port = i + 1
            if port in chars:
                ext = EXTERNAL.index(melee.Character(chars[port]))
                struct.pack_into(">BBBB", buf, base, ext, 0, self.stocks, self.costumes.get(port, 0))
                struct.pack_into(">B", buf, base + 0x8, 9)  # handicap
                struct.pack_into(">fff", buf, base + 0x18, 1.0, 1.0, 1.0)  # offense, defense, model scale
            else:
                struct.pack_into(">BB", buf, base, 26, 3)  # empty slot
        struct.pack_into(">I", buf, 0x13D, seed)
        for i in range(4):
            struct.pack_into(">II", buf, 0x141 + 8 * i, 1, 1)  # UCF dashback and shield drop
        buf[0x1A2] = 1  # frozen Pokemon Stadium
        buf[0x1A3], buf[0x1A4] = 2, 2  # VS mode scene
        buf[0x2BD] = 1
        return payloads + bytes(buf)

    def frame(self, obs, inputs=None, seed: int | None = None) -> bytes:
        """All events of one frame. `inputs`: the raw input row that produced `obs` (None at reset)."""
        f = int(obs["frame_id"])
        seed = int(obs["frame_pre_random_seed"]) if seed is None else seed
        out = [] if self.started else [self.game_start(obs, seed)]
        self.started = True
        out.append(struct.pack(">BiII", FRAME_START, f, seed, f + 123))
        players = []
        for slot, follower in ([(s, 0) for s in obs["slots"]] + [(s, 1) for s in obs["followers"]]):
            source = int(slot["source_player"])
            if source >= len(self.ports) or (follower and not slot["present"]):
                continue
            players.append((self.ports[source], follower, slot, source))
        players.sort(key=lambda p: (p[0], p[1]))
        posts = {}
        for port, follower, slot, source in players:
            post = self._post(f, port, follower, slot)
            posts[(port, follower)] = post
            before = self.prev.get((port, follower), post)
            pre = {"frame": f, "port": port - 1, "follower": follower, "seed": seed, "action": before["action"],
                   "x": before["x"], "y": before["y"], "facing": before["facing"], "percent": before["percent"],
                   **(_pre_inputs(inputs["players"][source]) if inputs is not None and not follower else {})}
            out.append(_pack(PRE, PRE_FIELDS, pre))
        for item in obs["items"]:
            if item["exists"]:
                owner = int(item["owner"])
                out.append(_pack(ITEM, ITEM_FIELDS, {
                    "frame": f, "type": int(item["type"]), "state": int(item["state"]), "facing": float(item["direction"]),
                    "vel_x": float(item["vel_x"]), "vel_y": float(item["vel_y"]), "x": float(item["pos_x"]),
                    "y": float(item["pos_y"]), "damage": int(item["damage"]), "timer": float(item["timer"]),
                    "spawn_id": int(item["spawn_id"]), "misc0": int(item["misc0"]), "misc1": int(item["misc1"]),
                    "misc2": int(item["misc2"]), "misc3": int(item["misc3"]),
                    "owner": self.ports[owner] - 1 if 0 <= owner < len(self.ports) else -1}))
        for post in posts.values():
            out.append(_pack(POST, POST_FIELDS, post))
        self.prev = posts
        out += self._stage_events(f, obs["stage"])
        out.append(struct.pack(">Bii", BOOKEND, f, f))
        return b"".join(out)

    def game_end(self, method: int = 2, placements: dict[int, int] | None = None) -> bytes:
        places = [(placements or {}).get(p, -1) for p in range(1, 5)]
        return struct.pack(">BBb4b", GAME_END, method, -1, *places)

    def _post(self, f: int, port: int, follower: int, s) -> dict:
        action = int(s["action_id"])
        hitlag, hitstun = int(s["hitlag"]), int(s["hitstun"])
        flags2 = 0x20 if hitlag else 0
        flags3 = 0x80 if action in _SHIELD else 0
        flags4 = 0x02 if hitstun else 0
        flags5 = (0x08 if follower else 0) | (0x40 if action in _DEAD else 0)
        return {"frame": f, "port": port - 1, "follower": follower, "character": int(s["char_id"]), "action": action,
                "x": float(s["pos_x"]), "y": float(s["pos_y"]), "facing": 1.0 if s["facing"] else -1.0,
                "percent": float(s["percent"]), "shield": float(s["shield_hp"]), "stocks": int(s["stocks"]),
                "action_frame": float(s["action_frame"]), "flags2": flags2, "flags3": flags3, "flags4": flags4,
                "flags5": flags5, "misc_as": float(hitstun), "airborne": 0 if s["on_ground"] else 1,
                "jumps": int(s["jumps_left"]), "hurtbox": int(s["hurtbox_state"]),
                "speed_air_x": float(s["speed_air_x_self"]), "speed_y": float(s["speed_y_self"]),
                "speed_attack_x": float(s["speed_x_attack"]), "speed_attack_y": float(s["speed_y_attack"]),
                "speed_ground_x": float(s["speed_ground_x_self"]), "hitlag": float(hitlag)}

    def _stage_events(self, f: int, stage) -> list[bytes]:
        out = []
        if self.stage is melee.Stage.FOUNTAIN_OF_DREAMS:
            for i, h in ((0, float(stage["fod_platforms"]["right"])), (1, float(stage["fod_platforms"]["left"]))):
                if self.fod[i] != h:
                    self.fod[i] = h
                    out.append(struct.pack(">BiBf", FOD, f, i, h))
        elif self.stage is melee.Stage.DREAMLAND and self.whispy != int(stage["whispy"]):
            self.whispy = int(stage["whispy"])
            out.append(struct.pack(">BiB", WHISPY, f, self.whispy))
        return out


def decode(raw: bytes, sizes: dict | None = None) -> tuple[dict, list[tuple[int, dict]]]:
    """Event sizes and (code, fields) for every pre/post/item event of a raw Slippi byte stream. Pass `sizes` to
    read a stream that does not start with Event Payloads (one frame after the first)."""
    pos = 0
    if sizes is None:
        sizes = {raw[k]: struct.unpack(">H", raw[k + 1:k + 3])[0] for k in range(2, raw[1] + 1, 3)}
        pos = raw[1] + 1
    events = []
    while pos < len(raw):
        code = raw[pos]
        if code in TABLES:
            ev = raw[pos:pos + sizes[code] + 1]
            events.append((code, {name: struct.unpack_from(">" + fmt, ev, off)[0] for off, fmt, name in TABLES[code]
                                  if off + struct.calcsize(fmt) <= len(ev)}))
        pos += sizes[code] + 1
    return sizes, events


def _replay_raw(slp: Path) -> bytes:
    b = slp.read_bytes()
    i = b.index(b"raw[$U#l") + 8
    return b[i + 4:i + 4 + struct.unpack(">I", b[i:i + 4])[0]]


def round_trip(slp: Path) -> dict:
    """Replay a Dolphin .slp's inputs through the simulator, encode each frame, and compare every event field with
    the replay's own events until the games diverge (melee_sim's RNG is not Dolphin's)."""
    from melee_llm.sim import parity

    _, truth_events = decode(_replay_raw(slp))
    truth: dict[tuple, dict] = {}
    for code, ev in truth_events:
        key = (code, ev["frame"], ev["spawn_id"]) if code == ITEM else (code, ev["frame"], ev["port"], ev["follower"])
        truth[key] = ev
    mismatches, examples, compared = Counter(), {}, 0
    enc, sizes = None, None
    for obs, row, frame, ports, stage in parity.sim_frames(slp):
        if enc is None:
            enc = Encoder(stage, ports)
            sizes, ours = decode(enc.frame(obs, row))
        else:
            _, ours = decode(enc.frame(obs, row), sizes)
        key = lambda code, ev: (code, ev["frame"], ev["spawn_id"]) if code == ITEM else (code, ev["frame"], ev["port"], ev["follower"])
        if any(code == POST and (w := truth.get(key(code, ev))) is not None
               and (ev["action"] != w["action"] or abs(ev["x"] - w["x"]) > 1e-4) for code, ev in ours):
            break  # the games diverged (a random choice came out differently): stop before this frame
        for code, ev in ours:
            want = truth.get(key(code, ev))
            if want is None:
                mismatches[f"{code:#x}.missing"] += 1
                continue
            if code == PRE:  # the stick direction bits are left 0 (see the module docstring)
                want = {**want, "processed_buttons": want["processed_buttons"] & ~0x00FF0000}
            for name, v in ev.items():
                w = want.get(name)
                if w is not None and not (v == w or (isinstance(v, float) and abs(v - w) < 1e-5)):
                    mismatches[f"{code:#x}.{name}"] += 1
                    examples.setdefault(f"{code:#x}.{name}", (frame, ev.get("port"), v, w))
        compared += 1
    return {"replay": str(slp), "compared": compared, "mismatches": dict(mismatches), "examples": examples}


if __name__ == "__main__":
    for path in sys.argv[1:]:
        r = round_trip(Path(path))
        print(f"{Path(path).name}: {r['compared']} frames compared")
        for f, k in sorted(r["mismatches"].items(), key=lambda kv: -kv[1]):
            print(f"  {f}: {k}  e.g. frame/port/ours/dolphin = {r['examples'].get(f)}")
