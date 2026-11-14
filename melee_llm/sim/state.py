"""melee_sim observations → libmelee GameState, field for field as libmelee's Console builds them from Slippi.

What libmelee reads from a post-frame event, melee_sim reports in the same units (both come from the same
fighter struct), so most fields copy across. On top of the raw values libmelee's Console adds: action
frames re-indexed to start at 1 for zero-indexed actions, the moonwalk warning (needs the previous frame),
`off_stage`, `distance`, projectiles from item slots, and each player's controller state from its inputs.

melee_sim does not report the ECB or the powershield flag; those keep libmelee's defaults (zeros, False).
"""
from __future__ import annotations

import csv
import math
import os
from collections import defaultdict

import melee
import numpy as np
from melee import enums, stages
from melee.enums import Action
from melee.gamestate import GameState, PlayerState, Projectile, UnknownAnimation, UnknownProjectileType

# melee_sim uses Slippi's external stage ids, libmelee its own enum
SIM_STAGE = {
    enums.Stage.FOUNTAIN_OF_DREAMS: 2, enums.Stage.POKEMON_STADIUM: 3, enums.Stage.YOSHIS_STORY: 8,
    enums.Stage.DREAMLAND: 28, enums.Stage.BATTLEFIELD: 31, enums.Stage.FINAL_DESTINATION: 32,
}
_UNUSED_SLOT = 255

_BUTTON_BITS = {
    enums.Button.BUTTON_A: 0x0100, enums.Button.BUTTON_B: 0x0200, enums.Button.BUTTON_X: 0x0400,
    enums.Button.BUTTON_Y: 0x0800, enums.Button.BUTTON_START: 0x1000, enums.Button.BUTTON_Z: 0x0010,
    enums.Button.BUTTON_R: 0x0020, enums.Button.BUTTON_L: 0x0040, enums.Button.BUTTON_D_LEFT: 0x0001,
    enums.Button.BUTTON_D_RIGHT: 0x0002, enums.Button.BUTTON_D_DOWN: 0x0004, enums.Button.BUTTON_D_UP: 0x0008,
}


def _zero_indices() -> dict[int, set[int]]:
    """Same table libmelee's Console loads: actions whose frame counter starts at 0, per character."""
    out = defaultdict(set)
    with open(os.path.join(os.path.dirname(melee.__file__), "actiondata.csv")) as f:
        for line in csv.DictReader(f):
            if line["zeroindex"] == "True":
                out[int(line["character"])].add(int(line["action"]))
    return out


_ZERO_INDICES = _zero_indices()


def _action(value: int) -> Action | UnknownAnimation:
    try:
        return Action(value)
    except ValueError:
        return UnknownAnimation(value)


def controller_state_from_raw(row) -> melee.ControllerState:
    """A player's ControllerState from the raw input the game read this frame. libmelee fills `main_stick`
    from Slippi's *processed* stick (after the game's deadzone); here it is the raw stick scaled the same
    way, which only differs inside the deadzone. `button` holds the physical buttons, as in libmelee."""
    cs = melee.ControllerState()
    bits = int(row["buttons"])
    for b, bit in _BUTTON_BITS.items():
        cs.button[b] = cs.processed_button[b] = bool(bits & bit)
    mx, my, cx, cy = (int(row[k]) for k in ("main_x", "main_y", "c_x", "c_y"))
    cs.main_stick = (mx / 160 + 0.5, my / 160 + 0.5)
    cs.c_stick = (cx / 160 + 0.5, cy / 160 + 0.5)
    cs.raw_main_stick = (mx, my)
    cs.l_shoulder = cs.r_shoulder = max(int(row["l"]), int(row["r"])) / 140  # the game reads the larger one
    return cs


class StateBuilder:
    """Builds one GameState per frame for a 2+ player match. `ports[i]` is the libmelee port (1-4) of
    melee_sim source player i. Keep one builder per game: the moonwalk warning reads the previous frame."""

    def __init__(self, stage: enums.Stage, ports: list[int], costumes: dict[int, int] | None = None):
        self.stage, self.ports = stage, ports
        self.costumes = costumes or {}
        self.prev: GameState | None = None

    def build(self, obs: np.void, inputs: np.void | None = None) -> GameState:
        """`obs`: one melee_sim gamestate row. `inputs`: the raw input row that produced it (None at reset)."""
        gs = GameState(frame=int(obs["frame_id"]), stage=self.stage, menu_state=enums.Menu.IN_GAME)
        for slot in obs["slots"]:
            source = int(slot["source_player"])
            if source == _UNUSED_SLOT or source >= len(self.ports):
                continue
            port = self.ports[source]
            ps = self._player(slot, port)
            if inputs is not None:
                ps.controller_state = controller_state_from_raw(inputs["players"][source])
            gs.players[port] = ps
        for follower in obs["followers"]:
            source = int(follower["source_player"])
            if follower["present"] and source < len(self.ports) and self.ports[source] in gs.players:
                gs.players[self.ports[source]].nana = self._player(follower, self.ports[source], nana=True)
        gs.projectiles = [self._projectile(item) for item in obs["items"] if item["exists"]]
        if len(gs.players) >= 2:
            a, b = (gs.players[p].position for p in sorted(gs.players)[:2])
            gs.distance = math.sqrt((a.x - b.x) ** 2 + (a.y - b.y) ** 2)
        self.prev = gs
        return gs

    def _player(self, slot: np.void, port: int, nana: bool = False) -> PlayerState:
        ps = PlayerState()
        ps.character = enums.Character(int(slot["char_id"]))
        ps.costume = self.costumes.get(port, 0)
        ps.position.x, ps.position.y = np.float32(slot["pos_x"]), np.float32(slot["pos_y"])
        ps.action = _action(int(slot["action_id"]))
        ps.facing = bool(slot["facing"])
        ps.percent = np.float32(slot["percent"])
        ps.shield_strength = np.float32(slot["shield_hp"])
        ps.stock = int(slot["stocks"])
        ps.action_frame = int(slot["action_frame"])
        if ps.action.value in _ZERO_INDICES[ps.character.value]:
            ps.action_frame += 1
        ps.hitstun_frames_left = int(slot["hitstun"])
        ps.hitlag_left = int(slot["hitlag"])
        ps.on_ground = bool(slot["on_ground"])
        ps.jumps_left = int(slot["jumps_left"])
        ps.invulnerable = bool(slot["invulnerable"])
        ps.speed_air_x_self = np.float32(slot["speed_air_x_self"])
        ps.speed_ground_x_self = np.float32(slot["speed_ground_x_self"])
        ps.speed_y_self = np.float32(slot["speed_y_self"])
        ps.speed_x_attack = np.float32(slot["speed_x_attack"])
        ps.speed_y_attack = np.float32(slot["speed_y_attack"])
        ps.controller_status = enums.ControllerStatus.CONTROLLER_HUMAN
        if not nana and self.prev is not None and port in self.prev.players:
            ps.moonwalkwarning = (ps.action == Action.DASHING
                                  and self.prev.players[port].action not in (Action.DASHING, Action.TURNING))
        edge = stages.EDGE_GROUND_POSITION.get(self.stage)
        ps.off_stage = edge is not None and (abs(ps.position.x) > edge or ps.position.y < -6) and not ps.on_ground
        return ps

    def _projectile(self, item: np.void) -> Projectile:
        p = Projectile()
        p.position.x, p.position.y = np.float32(item["pos_x"]), np.float32(item["pos_y"])
        p.speed.x, p.speed.y = np.float32(item["vel_x"]), np.float32(item["vel_y"])
        raw = int(item["type"])
        try:
            p.type = enums.ProjectileType(raw)
        except ValueError:
            p.type = UnknownProjectileType(np.uint16(raw))
        p.expiration_frames = int(item["timer"])
        p.subtype = int(item["state"])
        p.spawn_id = np.uint32(item["spawn_id"])
        owner = int(item["owner"])
        p.owner = self.ports[owner] if 0 <= owner < len(self.ports) else -1
        return p
