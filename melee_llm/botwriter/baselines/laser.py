"""Baseline: camps with standing lasers at range, shines and backs off when the opponent gets close."""
import melee
from melee import Button

UP_B = {a for a in melee.Action if a.name.startswith("SWORD_DANCE")}


class Bot:
    character = melee.Character.FOX
    name = "laser"

    def step(self, gs, ctrl, port, opp_port):
        me, opp = gs.players[port], gs.players[opp_port]
        if self.recover(me, ctrl):
            return
        dx = opp.position.x - me.position.x
        facing_opp = (dx > 0) == bool(me.facing)
        edge = melee.stages.EDGE_GROUND_POSITION.get(gs.stage, 60)
        if abs(dx) < 10 and me.on_ground:
            ctrl.tilt_analog(Button.BUTTON_MAIN, 0.5, 0.0)
            self.tap(ctrl, Button.BUTTON_B)
        elif abs(dx) < 35 and abs(me.position.x) < edge - 25:
            ctrl.release_button(Button.BUTTON_B)
            ctrl.tilt_analog(Button.BUTTON_MAIN, 0.0 if dx > 0 else 1.0, 0.5)  # retreat
        elif not facing_opp:
            ctrl.release_button(Button.BUTTON_B)
            ctrl.tilt_analog(Button.BUTTON_MAIN, 0.65 if dx > 0 else 0.35, 0.5)  # turn around
        else:
            ctrl.tilt_analog(Button.BUTTON_MAIN, 0.5, 0.5)
            self.tap(ctrl, Button.BUTTON_B)

    def recover(self, me, ctrl):
        if me.on_ground or not me.off_stage:
            return False
        toward = 1.0 if me.position.x < 0 else -1.0
        if me.action in UP_B:
            ctrl.release_button(Button.BUTTON_B)
            ctrl.tilt_analog(Button.BUTTON_MAIN, 0.5 + 0.35 * toward, 0.85)
        elif me.jumps_left > 0 and me.speed_y_self < 0:
            ctrl.release_button(Button.BUTTON_B)
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
