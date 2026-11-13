"""Toy Fox-on-Battlefield physics that reacts to controller input, to check macro timing without the ISO.

Only the mechanics macros depend on: jumpsquat/short vs full hop, gravity + fast-fall, aerials with
L-cancel, airdodge/wavedash landing, shield/roll/spotdodge, grab, shine + jump-cancel, dash, ledge hang.
Numbers are Fox's; this is NOT Melee, just enough to see that inputs land on the intended frames.
"""
from __future__ import annotations

import melee  # noqa: F401
from melee import Action as A, Button as B

from melee_llm.actions import RecordingController
from melee_llm.state import ledge_x

JS, GRAV, TERM, FF, FULL, SHORT, DJ = 3, .23, -2.8, -3.4, 3.68, 2.1, 4.186
AERIAL_LEN = {A.NAIR: 49, A.FAIR: 59, A.BAIR: 39, A.UAIR: 39, A.DAIR: 49}
AERIAL_LAG = {A.NAIR: 15, A.FAIR: 22, A.BAIR: 20, A.UAIR: 18, A.DAIR: 18}
TIMED = {A.NEUTRAL_ATTACK_1: 17, A.FTILT_MID: 26, A.UPTILT: 23, A.DOWNTILT: 25, A.FSMASH_MID: 49,
         A.UPSMASH: 41, A.DOWNSMASH: 49, A.GRAB: 29, A.ROLL_FORWARD: 31, A.ROLL_BACKWARD: 31, A.SPOTDODGE: 22,
         A.LANDING: 4, A.LANDING_SPECIAL: 10, A.DASH_ATTACK: 39, A.EDGE_GETUP_QUICK: 32, A.THROW_FORWARD: 30}


class FakeSim:
    def __init__(self, x=0., y=0., action=A.STANDING, opp_x=30., opp_y=0.):
        self.gs = melee.GameState(stage=melee.Stage.BATTLEFIELD, frame=100)
        me = melee.PlayerState(character=melee.Character.FOX, stock=4, action=action, action_frame=1,
                               on_ground=y == 0 and action != A.EDGE_HANGING, jumps_left=2 if y == 0 else 1)
        me.position.x, me.position.y = x, y
        op = melee.PlayerState(character=melee.Character.FALCO, stock=4, action=A.STANDING, facing=False)
        op.position.x, op.position.y = opp_x, opp_y
        self.gs.players = {1: me, 2: op}
        self.ctrl = RecordingController()
        self.prev = melee.ControllerState()
        self.held_y = False
        self.ff = self.lc = False
        self.trace: list[str] = []

    @property
    def me(self):
        return self.gs.players[1]

    def _set(self, action, **kw):
        self.me.action, self.me.action_frame = action, 1
        for k, v in kw.items():
            setattr(self.me, k, v)

    def advance(self):
        """Apply the controller state recorded this frame and move the toy physics one frame."""
        s, p, me = self.ctrl.state, self.prev, self.me
        new = lambda b: s.button[b] and not p.button[b]
        sx, sy = (s.main_stick[0] - .5) * 2, (s.main_stick[1] - .5) * 2
        psy = (p.main_stick[1] - .5) * 2
        cx, cy = (s.c_stick[0] - .5) * 2, (s.c_stick[1] - .5) * 2
        c_new = (abs(cx) > .5 or abs(cy) > .5) and p.c_stick == (.5, .5)
        a, me.action_frame = me.action, me.action_frame + 1
        free_ground = a in (A.STANDING, A.DASHING, A.TURNING, A.CROUCHING, A.SHIELD, A.RUNNING) or \
            (a in TIMED and me.on_ground and me.action_frame > TIMED[a])
        if me.on_ground and a == A.KNEE_BEND:
            self.held_y = self.held_y and s.button[B.BUTTON_Y]
            if me.action_frame > JS:
                self._set(A.JUMPING_FORWARD, on_ground=False, speed_y_self=FULL if self.held_y else SHORT,
                          jumps_left=1)
                self.ff = False
                if new(B.BUTTON_L):  # airdodge on the first airborne frame = wavedash
                    self._set(A.LANDING_SPECIAL, on_ground=True, speed_y_self=0.)
                    me.position.x += sx * 15
            if new(B.BUTTON_Z):
                self._set(A.GRAB)
        elif me.action == A.EDGE_HANGING:
            if new(B.BUTTON_Y):
                self._set(A.JUMPING_ARIAL_FORWARD, on_ground=False, speed_y_self=DJ)
            elif abs(sx) > .5:
                self._set(A.EDGE_GETUP_QUICK, on_ground=True)
                me.position.x, me.position.y = me.position.x * .9, 0
        elif me.on_ground and (free_ground or a.value in range(0x168, 0x16C)):
            shine = a.value in range(0x168, 0x16C)
            if new(B.BUTTON_Y) and (not shine or me.action_frame >= 4):
                self._set(A.KNEE_BEND)
                self.held_y = True
            elif shine:
                if me.action_frame > 20:
                    self._set(A.STANDING)
            elif new(B.BUTTON_B) and sy < -.5:
                self._set(A(0x168))
            elif s.button[B.BUTTON_R]:
                if abs(sx) > .8:
                    self._set(A.ROLL_FORWARD if (sx > 0) == me.facing else A.ROLL_BACKWARD)
                elif sy < -.8:
                    self._set(A.SPOTDODGE)
                elif a != A.SHIELD:
                    self._set(A.SHIELD)
            elif new(B.BUTTON_Z):
                self._set(A.GRAB)
            elif new(B.BUTTON_A):
                self._set(A.DASH_ATTACK if a == A.DASHING else A.UPTILT if sy > .3 else A.DOWNTILT if sy < -.3
                          else A.FTILT_MID if abs(sx) > .3 else A.NEUTRAL_ATTACK_1)
            elif c_new:
                self._set(A.UPSMASH if cy > .5 else A.DOWNSMASH if cy < -.5 else A.FSMASH_MID)
            elif abs(sx) > .8:
                if a != A.DASHING or me.facing != (sx > 0):
                    self._set(A.DASHING, facing=sx > 0)
                me.position.x += 2.0 * (1 if sx > 0 else -1)
            elif abs(sx) > .25 and (sx > 0) != me.facing:
                self._set(A.TURNING, facing=sx > 0)
            elif sy < -.6:
                if a != A.CROUCHING:
                    self._set(A.CROUCHING)
            elif a not in (A.STANDING,) and (a not in TIMED or me.action_frame > TIMED[a]):
                self._set(A.STANDING)
        elif not me.on_ground:
            in_aerial = a in AERIAL_LEN and me.action_frame <= AERIAL_LEN[a]
            if a in AERIAL_LEN and not in_aerial:
                self._set(A.FALLING)
            if a in AERIAL_LEN and new(B.BUTTON_L):
                self.lc = True
            elif a not in AERIAL_LEN and a != A.AIRDODGE:
                if new(B.BUTTON_L):
                    self._set(A.AIRDODGE, speed_y_self=sy * 2.8, speed_air_x_self=sx * 2.8)
                elif c_new or new(B.BUTTON_A):
                    f = 1 if me.facing else -1
                    self._set(A.UAIR if cy > .5 else A.DAIR if cy < -.5 else
                              (A.FAIR if cx * f > 0 else A.BAIR) if abs(cx) > .5 else A.NAIR)
                    self.lc = False
                elif new(B.BUTTON_Y) and me.jumps_left:
                    self._set(A.JUMPING_ARIAL_FORWARD, speed_y_self=DJ, jumps_left=0)
                    self.ff = False
            if not self.ff and me.speed_y_self < 0 and sy < -.66 and psy > -.3 and me.action != A.AIRDODGE:
                self.ff = True
            me.speed_y_self = FF if self.ff else max(TERM, me.speed_y_self - GRAV)
            me.speed_air_x_self = sx * .83 if me.action != A.AIRDODGE else me.speed_air_x_self
            me.position.x += me.speed_air_x_self
            me.position.y += me.speed_y_self
            if me.position.y <= 0 and abs(me.position.x) <= 68.4:
                lag = me.action in AERIAL_LEN
                act = (A(me.action.value + 5) if lag else A.LANDING_SPECIAL if me.action == A.AIRDODGE else A.LANDING)
                land_lag = AERIAL_LAG.get(me.action, 0) // (2 if self.lc else 1)
                self._set(act, on_ground=True, speed_y_self=0., jumps_left=2)
                me.position.y = 0.
                if lag:
                    TIMED[act] = land_lag
            elif abs(me.position.x) > ledge_x(self.gs.stage) - 3 and -15 < me.position.y < 0 and me.speed_y_self < 0:
                self._set(A.EDGE_HANGING, speed_y_self=0., jumps_left=1)
        me.off_stage = not me.on_ground and (abs(me.position.x) > 68.4 or me.position.y < -6)
        self.prev = melee.ControllerState(button=dict(s.button), main_stick=s.main_stick, c_stick=s.c_stick)
        self.gs.frame += 1

    def run(self, executor, frames: int, start: dict | None = None) -> list[str]:
        if start:
            executor.ctx.gs = self.gs
            executor.start(start)
        for _ in range(frames):
            me = self.me
            before = f"{me.action.name.lower()[:16]:16} f{me.action_frame:<2} y{me.position.y:6.1f}"
            executor.step(self.gs)
            self.ctrl.flush()
            self.trace.append(f"{before} -> {self.ctrl.log[-1]}")
            self.advance()
            if executor.idle:
                break
        return self.trace
