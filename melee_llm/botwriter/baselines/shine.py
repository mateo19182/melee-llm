"""Baseline: walks to the opponent and multishines (libmelee techskill) when adjacent."""
import math

import melee
from melee import Action, Button


class Bot:
    character = melee.Character.FOX
    name = "shine"

    def step(self, gs, ctrl, port, opp_port):
        me, opp = gs.players[port], gs.players[opp_port]
        if recover(gs, me, ctrl):
            return
        dx = opp.position.x - me.position.x
        if abs(dx) < 10 and abs(opp.position.y - me.position.y) < 12:
            melee.techskill.multishine(ai_state=me, controller=ctrl)
        else:
            ctrl.release_all()
            walk_toward(gs, me, ctrl, opp.position.x)

# libmelee's names for Fox's up-B: 353/354 startup (ground/air, the stick picks the angle), 355/356 travel, 358 helpless
FIREFOX_AIM = {Action.SWORD_DANCE_3_MID, Action.SWORD_DANCE_3_LOW}
FIREFOX = FIREFOX_AIM | {Action.SWORD_DANCE_4_HIGH, Action.SWORD_DANCE_4_MID, Action.SWORD_DANCE_1_AIR}


def recover(gs, me, ctrl):
    """Double jump toward the stage, then firefox aimed at the ledge. True while recovering."""
    if me.on_ground or (not me.off_stage and me.action not in FIREFOX):
        return False
    edge = melee.stages.EDGE_GROUND_POSITION.get(gs.stage, 70)
    x, y, side = me.position.x, me.position.y, (1 if me.position.x > 0 else -1)
    ctrl.release_button(Button.BUTTON_A)
    ctrl.tilt_analog(Button.BUTTON_C, 0.5, 0.5)
    if me.action in FIREFOX_AIM:
        tx, ty = (side * edge, -3) if y < -5 else (side * (edge - 15), 5)
        dx, dy = tx - x, ty - y
        n = math.hypot(dx, dy) or 1
        ctrl.release_button(Button.BUTTON_B)
        ctrl.tilt_analog(Button.BUTTON_MAIN, 0.5 + 0.5 * dx / n, 0.5 + 0.5 * dy / n)
    elif me.action in FIREFOX:
        ctrl.release_button(Button.BUTTON_B)
        ctrl.tilt_analog(Button.BUTTON_MAIN, 0.5 - 0.5 * side, 0.5)
    elif me.jumps_left > 0 and me.speed_y_self <= 0 and (y < 0 or abs(x) > edge + 30):
        ctrl.release_button(Button.BUTTON_B)
        ctrl.tilt_analog(Button.BUTTON_MAIN, 0.5 - 0.5 * side, 0.5)
        tap(ctrl, Button.BUTTON_Y)
    elif y < -15 or (me.jumps_left == 0 and me.speed_y_self < 0):
        ctrl.release_button(Button.BUTTON_Y)
        ctrl.tilt_analog(Button.BUTTON_MAIN, 0.5, 1.0)
        tap(ctrl, Button.BUTTON_B)
    else:
        ctrl.release_button(Button.BUTTON_Y)
        ctrl.tilt_analog(Button.BUTTON_MAIN, 0.5 - 0.5 * side, 0.5)
    return True


def walk_toward(gs, me, ctrl, x):
    """Run toward x, but never past the edge of the stage."""
    edge = melee.stages.EDGE_GROUND_POSITION.get(gs.stage, 70) - 12
    dx = max(-edge, min(edge, x)) - me.position.x
    ctrl.tilt_analog(Button.BUTTON_MAIN, 0.5 if abs(dx) < 3 else 1.0 if dx > 0 else 0.0, 0.5)


def tap(ctrl, button):
    if ctrl.prev.button[button]:
        ctrl.release_button(button)
    else:
        ctrl.press_button(button)
