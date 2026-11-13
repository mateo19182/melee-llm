"""Baseline: walks to the opponent and multishines (libmelee techskill) when adjacent."""
import melee
from melee import Button

UP_B = {a for a in melee.Action if a.name.startswith("SWORD_DANCE")}


class Bot:
    character = melee.Character.FOX
    name = "shine"

    def step(self, gs, ctrl, port, opp_port):
        me, opp = gs.players[port], gs.players[opp_port]
        if not me.on_ground and me.off_stage:
            toward = 1.0 if me.position.x < 0 else -1.0
            if me.action in UP_B:
                ctrl.release_button(Button.BUTTON_B)
                ctrl.tilt_analog(Button.BUTTON_MAIN, 0.5 + 0.35 * toward, 0.85)
            elif me.position.y < -10 or me.jumps_left == 0:
                ctrl.release_button(Button.BUTTON_X)
                ctrl.tilt_analog(Button.BUTTON_MAIN, 0.5, 1.0)
                ctrl.release_button(Button.BUTTON_B) if ctrl.prev.button[Button.BUTTON_B] else ctrl.press_button(Button.BUTTON_B)
            else:
                ctrl.tilt_analog(Button.BUTTON_MAIN, 0.5 + 0.5 * toward, 0.5)
            return
        dx = opp.position.x - me.position.x
        if abs(dx) < 10:
            melee.techskill.multishine(ai_state=me, controller=ctrl)
        else:
            ctrl.release_all()
            ctrl.tilt_analog(Button.BUTTON_MAIN, 1.0 if dx > 0 else 0.0, 0.5)
