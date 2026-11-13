"""Baseline: dash in, shine when adjacent, up-smash when slightly further, recover with jump + firefox."""
import melee
from melee import Action, Button

UP_B = {a for a in melee.Action if a.name.startswith("SWORD_DANCE")}
ACTIONABLE = {Action.STANDING, Action.WALK_SLOW, Action.WALK_MIDDLE, Action.WALK_FAST, Action.DASHING,
              Action.RUNNING, Action.TURNING, Action.CROUCHING, Action.LANDING}


class Bot:
    character = melee.Character.FOX
    name = "rusher"

    def step(self, gs, ctrl, port, opp_port):
        me, opp = gs.players[port], gs.players[opp_port]
        if self.recover(me, ctrl):
            return
        dx, dy = opp.position.x - me.position.x, opp.position.y - me.position.y
        ctrl.release_button(Button.BUTTON_A)
        ctrl.tilt_analog(Button.BUTTON_C, 0.5, 0.5)
        if me.action == Action.DOWN_B_GROUND:  # jump out of shine
            ctrl.release_button(Button.BUTTON_B)
            self.tap(ctrl, Button.BUTTON_Y)
            return
        if me.on_ground and me.action in ACTIONABLE and abs(dy) < 12:
            if abs(dx) < 9:
                ctrl.tilt_analog(Button.BUTTON_MAIN, 0.5, 0.0)
                self.tap(ctrl, Button.BUTTON_B)
                return
            if abs(dx) < 18:
                ctrl.tilt_analog(Button.BUTTON_MAIN, 0.5, 0.5)
                ctrl.tilt_analog(Button.BUTTON_C, 0.5, 1.0)
                return
        ctrl.release_button(Button.BUTTON_B)
        ctrl.release_button(Button.BUTTON_Y)
        ctrl.tilt_analog(Button.BUTTON_MAIN, 1.0 if dx > 0 else 0.0, 0.5)

    def recover(self, me, ctrl):
        if me.on_ground or not me.off_stage:
            return False
        toward = 1.0 if me.position.x < 0 else -1.0
        ctrl.release_button(Button.BUTTON_A)
        ctrl.tilt_analog(Button.BUTTON_C, 0.5, 0.5)
        if me.action in UP_B:
            ctrl.release_button(Button.BUTTON_B)
            ctrl.tilt_analog(Button.BUTTON_MAIN, 0.5 + 0.35 * toward, 0.85)
        elif me.jumps_left > 0 and me.speed_y_self < 0:
            ctrl.tilt_analog(Button.BUTTON_MAIN, 0.5 + 0.5 * toward, 0.5)
            self.tap(ctrl, Button.BUTTON_Y)
        elif me.position.y < -10 or me.jumps_left == 0:
            ctrl.release_button(Button.BUTTON_Y)
            ctrl.tilt_analog(Button.BUTTON_MAIN, 0.5, 1.0)
            self.tap(ctrl, Button.BUTTON_B)
        else:
            ctrl.tilt_analog(Button.BUTTON_MAIN, 0.5 + 0.5 * toward, 0.5)
        return True

    @staticmethod
    def tap(ctrl, button):
        if ctrl.prev.button[button]:
            ctrl.release_button(button)
        else:
            ctrl.press_button(button)
