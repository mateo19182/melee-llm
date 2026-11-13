"""Starter bot: recovers to the stage, walks at the opponent and jabs. Replace it with something good.

Contract (see README.md): a class named Bot with a `character` attribute and
`step(gamestate, controller, port, opp_port)`, called once per frame (60 fps, 16 ms budget).
Controller state persists between frames, so release what you no longer want held.
"""
import melee
from melee import Button

UP_B = {a for a in melee.Action if a.name.startswith("SWORD_DANCE")}  # Fox/Falco firefox actions


class Bot:
    character = melee.Character.FOX
    name = "starter"

    def step(self, gs: melee.GameState, ctrl: melee.Controller, port: int, opp_port: int) -> None:
        me, opp = gs.players[port], gs.players[opp_port]
        if self.recover(gs, me, ctrl):
            return
        dx = opp.position.x - me.position.x
        ctrl.release_button(Button.BUTTON_B)
        if abs(dx) < 12 and abs(opp.position.y - me.position.y) < 10 and me.on_ground:
            ctrl.tilt_analog(Button.BUTTON_MAIN, 0.5, 0.5)
            self.tap(ctrl, Button.BUTTON_A)
        else:
            ctrl.release_button(Button.BUTTON_A)
            ctrl.tilt_analog(Button.BUTTON_MAIN, 1.0 if dx > 0 else 0.0, 0.5)

    def recover(self, gs, me, ctrl) -> bool:
        """Jump, then firefox toward the stage when off it. Returns True while recovering."""
        if me.on_ground or not me.off_stage:
            return False
        toward = 1.0 if me.position.x < 0 else -1.0
        ctrl.release_button(Button.BUTTON_A)
        if me.action in UP_B:  # hold an angle toward the ledge while firefox charges
            ctrl.release_button(Button.BUTTON_B)
            ctrl.tilt_analog(Button.BUTTON_MAIN, 0.5 + 0.35 * toward, 0.85)
            return True
        if me.jumps_left > 0 and me.speed_y_self < 0:
            ctrl.tilt_analog(Button.BUTTON_MAIN, 0.5 + 0.5 * toward, 0.5)
            self.tap(ctrl, Button.BUTTON_Y)
        elif me.position.y < -10 or (me.jumps_left == 0 and me.speed_y_self < 0):
            ctrl.release_button(Button.BUTTON_Y)
            ctrl.tilt_analog(Button.BUTTON_MAIN, 0.5, 1.0)
            self.tap(ctrl, Button.BUTTON_B)
        else:
            ctrl.release_button(Button.BUTTON_Y)
            ctrl.tilt_analog(Button.BUTTON_MAIN, 0.5 + 0.5 * toward, 0.5)
        return True

    @staticmethod
    def tap(ctrl, button) -> None:
        """Press on one frame, release on the next: holding a button does not repeat it."""
        if ctrl.prev.button[button]:
            ctrl.release_button(button)
        else:
            ctrl.press_button(button)
