"""Batched 1v1 matches on melee-sim-light, as FRAME records from both players' sides.

Each step takes both players' raw controller inputs for every match and returns the new frame as the
dataset stores it (schema.FRAME, field for field what play.RawFrames reads from Slippi in a live game):
frames[:, 0] is player 0's view (me = player 0), frames[:, 1] player 1's. Finished matches restart on
the next step with a fresh matchup from `matchup(rng)`; frames before 0 are the countdown, where inputs
do nothing and the dataset has no frames.
"""
import os
from pathlib import Path

import melee
import numpy as np

from .. import features as fe
from ..schema import CHARACTERS, FRAME, STAGES

DATA_DIR = Path(os.environ.get("MSL_DATA_DIR", Path.home() / "projects/ai/melee-llm/vendor/melee-sim-light/data"))
TIMER_FRAMES = 8 * 60 * 60
STICK, DEADZONE = 80, 22
PAD_BUTTONS = np.array([0x0100, 0x0200, 0x0010, 0x0400, 0x0040], np.uint16)  # fe.BUTTON_GROUPS bits as pressed
_NAMES = {"CPTFALCON": "FALCON", "GAMEANDWATCH": "GNW", "POPO": "ICS", "JIGGLYPUFF": "PUFF", "GANONDORF": "GANON"}
INTERNAL = np.full(CHARACTERS.__len__(), -1)   # CHARACTERS index -> the simulator's (internal) character id
TO_INDEX = np.full(64, CHARACTERS.index("FOX"))  # internal id -> CHARACTERS index
for c in melee.Character:
    name = _NAMES.get(c.name, c.name)
    if name in CHARACTERS and c.value < 64:
        INTERNAL[CHARACTERS.index(name)], TO_INDEX[c.value] = c.value, CHARACTERS.index(name)
STAGE_IDS = list(STAGES)  # the simulator takes the external stage ids the dataset uses


def processed_stick(x, y):
    """Raw stick ints -> what Melee reads, in -80..80 units: clamped to the unit circle (truncating), then
    each axis zeroed inside the deadzone. Vectorised sim.slippi.processed_stick; Slippi records this."""
    x, y = x.astype(np.int32), y.astype(np.int32)
    r = np.sqrt((x * x + y * y).astype(np.float32))
    over = r > STICK
    rr = np.where(over, r, np.float32(1))
    x = np.where(over, (x.astype(np.float32) * np.float32(STICK) / rr).astype(np.int32), x)
    y = np.where(over, (y.astype(np.float32) * np.float32(STICK) / rr).astype(np.int32), y)
    return np.where(np.abs(x) <= DEADZONE, 0, x), np.where(np.abs(y) <= DEADZONE, 0, y)


def to_inputs(choice, centers, out):
    """Model classes (dict head -> (N,) ints, numpy) -> raw simulator inputs, as play.Policy.to_controller presses
    them: stick centre, c-stick direction, button groups, L digital + full analog or an analog shoulder level."""
    stick = np.rint(centers[choice["stick"]]).astype(np.int8)
    c = choice["cstick"]
    cdir = np.rint(np.concatenate([np.zeros((1, 2)), fe.CSTICK_DIRS]) * STICK).astype(np.int8)[c]
    bits = choice["buttons"]
    buttons = np.zeros(bits.shape, np.uint16)
    for i, b in enumerate(PAD_BUTTONS):
        buttons |= np.where(bits >> i & 1, b, 0).astype(np.uint16)
    out["buttons"] = buttons
    out["main_x"], out["main_y"] = stick[..., 0], stick[..., 1]
    out["c_x"], out["c_y"] = cdir[..., 0], cdir[..., 1]
    out["l"] = np.where(bits >> 4 & 1, 140, fe.SHOULDER_LEVELS[choice["shoulder"]]).astype(np.uint8)
    out["r"] = 0
    return out


def _pad(inp, out):
    out["stick"][..., 0], out["stick"][..., 1] = processed_stick(inp["main_x"], inp["main_y"])
    out["cstick"][..., 0], out["cstick"][..., 1] = processed_stick(inp["c_x"], inp["c_y"])
    out["trigger"][..., 0], out["trigger"][..., 1] = inp["l"], inp["r"]
    out["buttons"] = inp["buttons"]


def _player(s, out):
    out["pos"][..., 0], out["pos"][..., 1] = s["pos_x"], s["pos_y"]
    for i, k in enumerate(("speed_air_x_self", "speed_ground_x_self", "speed_y_self", "speed_x_attack", "speed_y_attack")):
        out["vel"][..., i] = s[k]
    out["percent"], out["shield"], out["state_age"] = s["percent"], s["shield_hp"], s["action_frame"]
    out["hitstun"] = s["hitstun"]
    out["action"], out["hitlag"] = s["action_id"], np.minimum(s["hitlag"], 255)
    out["stocks"], out["jumps"] = s["stocks"], s["jumps_left"]
    out["facing"] = np.where(s["facing"] != 0, 1, -1)
    out["airborne"] = s["on_ground"] == 0
    out["invuln"] = s["hurtbox_state"]


def reward(prev, cur, damage_weight=0.01):
    """Per-frame reward from each side's view (FRAME arrays, same shape): stocks taken minus stocks lost, plus
    damage dealt minus taken times `damage_weight`. Percent drops at a death don't count as healing."""
    def side(p):
        lost = np.maximum(prev[p]["stocks"].astype(np.int16) - cur[p]["stocks"], 0)
        taken = np.maximum(cur[p]["percent"].astype(np.float32) - prev[p]["percent"].astype(np.float32), 0)
        return lost, taken
    my_lost, my_taken = side("me")
    opp_lost, opp_taken = side("opp")
    return (opp_lost - my_lost) + damage_weight * (opp_taken - my_taken)


def random_matchup(rng, chars=("YOSHI",), opp_chars=("YOSHI",)):
    return (rng.choice(STAGE_IDS), CHARACTERS.index(rng.choice(chars)), CHARACTERS.index(rng.choice(opp_chars)))


class SelfPlay:
    """n matches stepped together. matchup(rng) -> (stage id, CHARACTERS index of player 0, of player 1)."""

    def __init__(self, n, matchup=random_matchup, seed=0, max_frame=TIMER_FRAMES, ring=1024):
        import melee_sim as msl

        self.msl, self.n, self.matchup, self.max_frame = msl, n, matchup, max_frame
        self.rng = np.random.default_rng(seed)
        self.env = msl.EnvBatch(batch_size=n, length=ring, action_format="raw", data_dir=str(DATA_DIR))
        self.chars, self.stage = np.zeros((n, 2), np.int64), np.zeros(n, np.int64)
        self._next_chars, self._next_stage = self.chars.copy(), self.stage.copy()  # applied when a match restarts
        self.games = 0
        self.frames = np.zeros((n, 2), FRAME)
        self.frame_id = np.zeros(n, np.int64)
        self._configure(np.arange(n))
        self.env.reset_all()
        self.chars[:], self.stage[:] = self._next_chars, self._next_stage
        self._observe(np.zeros((n, 2), self.env.raw_action_view.dtype["players"].base), np.ones(n, bool))

    def _configure(self, ids):
        cfgs = []
        for i in ids:
            stage, c0, c1 = self.matchup(self.rng)
            self._next_stage[i], self._next_chars[i] = fe.STAGE_INDEX[int(stage)], (c0, c1)
            self.games += 1
            cfgs.append(self.msl.MatchConfig(
                stage=int(stage), seed=int(self.rng.integers(2**32)), max_frame=self.max_frame,
                players=tuple(self.msl.PlayerConfig(int(INTERNAL[c]), controller_port=p) for p, c in enumerate((c0, c1)))))
        self.env.configure_matches(cfgs, env_ids=np.asarray(ids))

    def _observe(self, inputs, fresh):
        obs = self.env.current_frame
        slots = obs["slots"][:, :2]
        self.frame_id[:] = obs["frame_id"]
        f = self.frames
        for me in (0, 1):
            _player(slots[:, me], f[:, me]["me"])
            _player(slots[:, 1 - me], f[:, me]["opp"])
            _pad(inputs[:, me], f[:, me]["me_pad"])
            _pad(inputs[:, 1 - me], f[:, me]["opp_pad"])
        f["me_pad"][fresh], f["opp_pad"][fresh] = 0, 0  # a match's entry frame had no inputs

    def step(self, inputs):
        """inputs: (n, 2) raw input records (see to_inputs). Returns (frames (n,2) FRAME, done (n,), fresh (n,)):
        done marks a match's last frame (it restarts next step), fresh a new match's first (countdown) frame.
        `frames` is reused: copy what you keep. `chars`/`stage` describe the match each row now shows."""
        env = self.env
        if env.t >= env.length:
            env.reset_cursor()
        env.raw_action_view[env.t]["players"][:, :2] = inputs
        fresh, term = env.step_and_reset()
        done = term["done"].astype(bool)
        self._observe(inputs, fresh)
        self.chars[fresh], self.stage[fresh] = self._next_chars[fresh], self._next_stage[fresh]
        if done.any():
            self._configure(np.flatnonzero(done))
        return self.frames, done, fresh

    def winner(self, i):
        """0, 1 or -1 (tie) for match i's current frame: more stocks, then lower percent."""
        me = self.frames[i, 0]
        key = lambda p: (int(p["stocks"]), -float(p["percent"]))
        a, b = key(me["me"]), key(me["opp"])
        return -1 if a == b else int(b > a)

    def close(self):
        self.env.close()
