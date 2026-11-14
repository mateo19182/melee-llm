"""Run a trained policy live: libmelee GameStates in, controller states out.

The model was trained on frames read from .slp files by peppi, and libmelee rounds or reinterprets
several of the same fields (action frame, hitstun, hitlag, hurtbox). So `RawFrames` hooks libmelee's
frame parser and builds schema.FRAME records from the same raw Slippi bytes the dataset used.
"""
import time

import melee
import numpy as np
import torch

from . import features as fe
from .model import HEADS, load
from .schema import CHARACTERS, FRAME, RANKS

_PLAYER = FRAME["me"]
_PAD = FRAME["me_pad"]

# libmelee names its enums after internal ids; the dataset uses the character-select (external) ids.
_CHAR_NAMES = {"CPTFALCON": "FALCON", "GAMEANDWATCH": "GNW", "POPO": "ICS", "JIGGLYPUFF": "PUFF", "GANONDORF": "GANON"}
_STAGES = {"FOUNTAIN_OF_DREAMS": 2, "POKEMON_STADIUM": 3, "YOSHIS_STORY": 8, "DREAMLAND": 28,
           "BATTLEFIELD": 31, "FINAL_DESTINATION": 32}


def character_index(c: melee.Character) -> int:
    name = _CHAR_NAMES.get(c.name, c.name)
    return CHARACTERS.index(name) if name in CHARACTERS else CHARACTERS.index("FOX")


def stage_index(s: melee.Stage) -> int:
    return fe.STAGE_INDEX[_STAGES.get(getattr(s, "name", ""), 31)]


def _f(b, off, fmt=">f"):
    try:
        return np.ndarray((1,), fmt, b, off)[0]
    except (TypeError, ValueError):
        return 0


class RawFrames:
    """Collects FRAME-layout player and controller records per (frame, port), from raw Slippi events.

    Installed once per process by wrapping libmelee's private frame parsers (stable across 0.45-0.47).
    Rollback re-sends overwrite earlier copies, as in build_dataset.
    """

    def __init__(self):
        self.players: dict[tuple[int, int], np.void] = {}
        self.pads: dict[tuple[int, int], np.void] = {}
        pre, post = melee.Console._Console__pre_frame, melee.Console._Console__post_frame
        raw = self

        def pre_frame(console, gamestate, b):
            pre(console, gamestate, b)
            if b[0x6] == 0:
                raw.pads[(int(_f(b, 0x1, ">i")), b[0x5] + 1)] = raw._pad(b)

        def post_frame(console, gamestate, b):
            post(console, gamestate, b)
            if b[0x6] == 0:
                raw.players[(int(_f(b, 0x1, ">i")), b[0x5] + 1)] = raw._player(b)

        melee.Console._Console__pre_frame = pre_frame
        melee.Console._Console__post_frame = post_frame

    @staticmethod
    def _player(b):
        p = np.zeros((), _PLAYER)
        p["pos"] = (_f(b, 0xA), _f(b, 0xE))
        p["vel"] = (_f(b, 0x35), _f(b, 0x45), _f(b, 0x39), _f(b, 0x3D), _f(b, 0x41))
        p["percent"] = _f(b, 0x16)
        p["shield"] = _f(b, 0x1A)
        p["state_age"] = _f(b, 0x22)
        p["hitstun"] = _f(b, 0x2B) if int(_f(b, 0x29, ">B")) & 0x02 else 0
        p["action"] = _f(b, 0x8, ">H")
        p["hitlag"] = _f(b, 0x49)
        p["stocks"] = _f(b, 0x21, ">B")
        p["jumps"] = _f(b, 0x32, ">B")
        p["facing"] = np.sign(_f(b, 0x12))
        p["airborne"] = _f(b, 0x2F, ">B")
        p["invuln"] = _f(b, 0x34, ">B")
        return p

    @staticmethod
    def _pad(b):
        c = np.zeros((), _PAD)
        c["stick"] = (round(_f(b, 0x19) * 80), round(_f(b, 0x1D) * 80))
        c["cstick"] = (round(_f(b, 0x21) * 80), round(_f(b, 0x25) * 80))
        c["trigger"] = (round(_f(b, 0x33) * 140), round(_f(b, 0x37) * 140))
        c["buttons"] = _f(b, 0x31, ">H")
        return c

    def frame(self, frame: int, me: int, opp: int):
        """The FRAME record for one frame from `me`'s perspective, or None if a part is missing."""
        parts = [self.players.get((frame, me)), self.players.get((frame, opp)),
                 self.pads.get((frame, me)), self.pads.get((frame, opp))]
        if any(p is None for p in parts):
            return None
        f = np.zeros((), FRAME)
        f["me"], f["opp"], f["me_pad"], f["opp_pad"] = parts
        return f

    def forget_before(self, frame: int):
        for d in (self.players, self.pads):
            for k in [k for k in d if k[0] < frame]:
                del d[k]


_RAW = None


def raw_frames() -> RawFrames:
    global _RAW
    if _RAW is None:
        _RAW = RawFrames()
    return _RAW


class Policy:
    """One game at a time: feed every GameState to `act`, which returns a libmelee-style controller dict."""

    def __init__(self, checkpoint, port, opponent_port, delay=0, rank="MASTER", win=1, temperature=1.0,
                 device=None, threads=8, seed=0):
        self.raw = raw_frames()
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        torch.set_num_threads(threads)
        self.model, self.ckpt = load(checkpoint, self.device)
        self.port, self.opp = port, opponent_port
        self.steer = {}
        self.set_steer(dict(delay=delay, rank=rank, win=win, temperature=temperature))
        self.centers = self.model.stick_centers.cpu().numpy()
        self.context = self.model.config.context
        torch.manual_seed(seed)
        cap = 4 * self.context
        self.feats = (np.zeros((cap, 2 * fe.PLAYER_NUM), np.float32), np.zeros((cap, fe.PAD_NUM), np.float32),
                      np.zeros((cap, fe.PAD_NUM), np.float32), np.zeros((cap, 2), np.int64))
        self.size = 0
        self.last_frame = None
        # rope models keep a per-layer key/value cache and run one frame per step
        self.cached = self.model.config.pos == "rope"
        self.caches, self.n = None, 0

    def set_steer(self, steer: dict) -> dict:
        new = {**self.steer, **steer}
        if not 0 <= int(new["delay"]) <= fe.MAX_DELAY:
            raise ValueError(f"delay must be 0..{fe.MAX_DELAY}")
        if str(new["rank"]).upper() not in RANKS:
            raise ValueError(f"rank must be one of {RANKS}")
        if new["win"] not in (0, 1, None):
            raise ValueError("win must be 0, 1 or None (unknown)")
        if not float(new["temperature"]) > 0:
            raise ValueError("temperature must be > 0")
        self.steer = dict(delay=int(new["delay"]), rank=str(new["rank"]).upper(), win=new["win"],
                          temperature=float(new["temperature"]))
        return dict(self.steer)

    def _push(self, f):
        """Store one frame's parts of fe.window's inputs, computed once when the frame arrives."""
        if self.size == len(self.feats[0]):  # full: keep the newest frames a window can reach
            keep = self.context + fe.MAX_DELAY
            for x in self.feats:
                x[:keep] = x[self.size - keep:self.size]
            self.size = keep
        state, own, opp_pad, act = self.feats
        i = self.size
        state[i, :fe.PLAYER_NUM], state[i, fe.PLAYER_NUM:] = fe.player_num(f["me"]), fe.player_num(f["opp"])
        own[i], opp_pad[i] = fe.pad_num(f["me_pad"]), fe.pad_num(f["opp_pad"])
        act[i] = f["me"]["action"], f["opp"]["action"]
        self.size += 1

    def _batch(self, gs, last_only=False):
        # Same inputs as fe.window over the game's frames, from the per-frame parts stored by _push.
        n = min(self.size, self.context + fe.MAX_DELAY)
        state, own, opp_pad, act = (x[self.size - n:self.size] for x in self.feats)
        T = 1 if last_only else min(self.context, n)
        start = n - T
        d = self.steer["delay"]
        # Early in a game there may be fewer than `delay` older frames: repeat the first one.
        pad_front = max(0, d - start)
        if pad_front:
            state, own, opp_pad, act = (np.concatenate([np.repeat(x[:1], pad_front, 0), x])
                                        for x in (state, own, opp_pad, act))
            start += pad_front
        t = start + np.arange(T)
        num = np.concatenate([state[t - d], own[t], opp_pad[t - d]], -1)
        actions = np.minimum(act[t - d], fe.N_ACTIONS - 1)
        me, opp = gs.players[self.port], gs.players[self.opp]
        win = {0: 0, 1: 1, None: 2}[self.steer["win"]]
        b = dict(num=num[None], actions=actions[None], delay=[d], me_char=[character_index(me.character)],
                 opp_char=[character_index(opp.character)], stage=[stage_index(gs.stage)],
                 rank=[RANKS.index(self.steer["rank"])], win=[win])
        return {k: torch.as_tensor(np.asarray(v), device=self.device) for k, v in b.items()}

    def to_controller(self, choice: dict) -> dict:
        sx, sy = self.centers[choice["stick"]] / 80
        c = int(choice["cstick"])
        cx, cy = fe.CSTICK_DIRS[c - 1] if c else (0.0, 0.0)
        bits = int(choice["buttons"])
        held = [name for i, name in enumerate(("BUTTON_A", "BUTTON_B", "BUTTON_Z", "BUTTON_X", "BUTTON_L")) if bits >> i & 1]
        shoulder = 1.0 if "BUTTON_L" in held else fe.SHOULDER_LEVELS[int(choice["shoulder"])] / 140
        return {"main": (0.5 + sx / 2, 0.5 + sy / 2), "c": (0.5 + cx / 2, 0.5 + cy / 2),
                "l": float(shoulder), "r": 0.0, "buttons": held}

    @torch.inference_mode()
    def act(self, gs) -> dict | None:
        """Controller for the next frame, or None (leave the controller alone) before the game starts."""
        if self.last_frame is not None and gs.frame < self.last_frame:
            self.size, self.caches, self.n = 0, None, 0
        self.last_frame = gs.frame
        f = self.raw.frame(gs.frame, self.port, self.opp)
        self.raw.forget_before(gs.frame - 2)
        if f is None or gs.frame < 0:   # the dataset starts at frame 0, when players can first move
            return None
        self._push(f)
        with torch.autocast(self.device, torch.bfloat16, enabled=self.device == "cuda"):
            if self.cached:
                if self.caches is None:
                    self.caches, self.n = self.model.new_caches(), 0
                b = self._batch(gs, last_only=True)
                choice = self.model.step(b, self.n, self.caches, self.steer["temperature"])
                self.n += 1
            else:
                choice = self.model.sample(self._batch(gs), self.steer["temperature"])
        return self.to_controller({k: v.item() for k, v in choice.items()})


def replay_check(slp_path, dataset_dir, game_row, port):
    """Read one replay with libmelee + RawFrames and compare every frame with the dataset's copy."""
    from .show import load as load_dataset
    raw = raw_frames()
    console = melee.Console(is_dolphin=False, path=slp_path, allow_old_version=True)
    console.connect()
    while console.step() is not None:
        pass
    games, frames = load_dataset(dataset_dir)
    stored = frames[int(games["offset"][game_row]): int(games["offset"][game_row] + games["length"][game_row])]
    opp = 3 - port
    live = np.stack([raw.frame(i, port, opp) for i in range(len(stored))])
    out = {}
    for side in ("me", "opp"):
        for field in _PLAYER.names:
            out[f"{side}.{field}"] = int((live[side][field] != stored[side][field]).reshape(len(stored), -1).any(1).sum())
    for side in ("me_pad", "opp_pad"):
        for field in _PAD.names:
            out[f"{side}.{field}"] = int((live[side][field] != stored[side][field]).reshape(len(stored), -1).any(1).sum())
    return len(stored), out


def bench_speed(checkpoint, device="cpu", threads=8, n=300):
    """Milliseconds per decision with a full 256-frame window."""
    torch.set_num_threads(threads)
    model, _ = load(checkpoint, device)
    T = model.config.context
    b = dict(num=torch.zeros(1, T, fe.NUM), actions=torch.zeros(1, T, 2, dtype=torch.long),
             **{k: torch.zeros(1, dtype=torch.long) for k in ("delay", "me_char", "opp_char", "stage", "rank", "win")})
    b = {k: v.to(device) for k, v in b.items()}
    one = {**b, "num": b["num"][:, :1], "actions": b["actions"][:, :1]}
    times, caches = [], model.new_caches()
    with torch.inference_mode():
        if model.config.pos == "rope":  # fill the cache first, as in a game past its first 4 seconds
            for i in range(T):
                model.step(one, i, caches)
        for i in range(n):
            t0 = time.perf_counter()
            if model.config.pos == "rope":
                model.step(one, T + i, caches)
            else:
                model.sample(b)
            times.append((time.perf_counter() - t0) * 1000)
    times = sorted(times[20:])
    return {"p50": round(times[len(times) // 2], 2), "p95": round(times[int(len(times) * .95)], 2), "max": round(times[-1], 2)}
