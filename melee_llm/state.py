"""GameState → compact observation dict + short text for LLM prompts, and an event tracker.

Coordinates are Melee units: x grows right, y grows up, the main stage top is y=0. 60 frames = 1 s.
"""
from __future__ import annotations

from functools import cache

import melee
from melee import Action as A, Character as C, stages

FPS = 60
GAME_SECONDS = 8 * 60

SPACIES = (C.FOX, C.FALCO)
# Fox/Falco special action ids; libmelee's enum names for these are aliases shared with other characters.
_SPACIE_SPECIALS = {
    0x155: "laser", 0x156: "laser", 0x157: "laser", 0x158: "laser_air", 0x159: "laser_air", 0x15A: "laser_air",
    0x15B: "sideb", 0x15C: "sideb", 0x15D: "sideb_end", 0x15E: "sideb_air", 0x15F: "sideb_air", 0x160: "sideb_air_end",
    0x161: "upb_charge", 0x162: "upb_charge_air", 0x163: "upb", 0x164: "upb_air", 0x165: "upb_landing",
    0x166: "upb_fall", 0x167: "upb_bounce",
    0x168: "shine", 0x169: "shine", 0x16A: "shine_hit", 0x16B: "shine_end", 0x16C: "shine_turn",
    0x16D: "shine_air", 0x16E: "shine_air", 0x16F: "shine_air_hit", 0x170: "shine_air_end", 0x171: "shine_air_turn",
}
SHINE_IDS = range(0x168, 0x172)
UPB_IDS = range(0x161, 0x168)
SIDEB_IDS = range(0x15B, 0x161)
LASER_IDS = range(0x155, 0x15B)

GROUND_FREE = {A.STANDING, A.WALK_SLOW, A.WALK_MIDDLE, A.WALK_FAST, A.TURNING, A.DASHING, A.RUNNING,
               A.CROUCH_START, A.CROUCHING, A.CROUCH_END, A.EDGE_TEETERING, A.EDGE_TEETERING_START, A.RUN_BRAKE}
AIR_FREE = {A.JUMPING_FORWARD, A.JUMPING_BACKWARD, A.JUMPING_ARIAL_FORWARD, A.JUMPING_ARIAL_BACKWARD,
            A.FALLING, A.FALLING_FORWARD, A.FALLING_BACKWARD, A.FALLING_AERIAL, A.FALLING_AERIAL_FORWARD,
            A.FALLING_AERIAL_BACKWARD, A.PLATFORM_DROP}
SHIELDING = {A.SHIELD_START, A.SHIELD, A.SHIELD_RELEASE, A.SHIELD_STUN, A.SHIELD_REFLECT}
AERIALS = {A.NAIR, A.FAIR, A.BAIR, A.UAIR, A.DAIR}
DAMAGED = {a for a in A if a.name.startswith("DAMAGE_")} | {A.TUMBLING}
LEDGE = {A.EDGE_CATCHING, A.EDGE_HANGING}
GRABBED = {A.GRAB_PULL, A.GRABBED, A.GRAB_PUMMELED, A.GRABBED_WAIT_HIGH, A.PUMMELED_HIGH, A.GRAB_PULLING_HIGH}
DEAD = {a for a in A if a.name.startswith("DEAD_") and a != A.DEAD_FALL} | {A.ON_HALO_DESCENT}
TECHS = {A.NEUTRAL_TECH, A.FORWARD_TECH, A.BACKWARD_TECH, A.WALL_TECH, A.WALL_TECH_JUMP, A.CEILING_TECH}
MISSED_TECH = {A.TECH_MISS_UP, A.TECH_MISS_DOWN}


@cache
def framedata() -> melee.FrameData:
    return melee.FrameData()


def action_name(ps: melee.PlayerState) -> str:
    v = getattr(ps.action, "value", -1)
    if ps.character in SPACIES and v in _SPACIE_SPECIALS:
        return _SPACIE_SPECIALS[v]
    if isinstance(ps.action, A):
        return ps.action.name.lower()
    return f"action_{v}"


def in_hitstun(ps: melee.PlayerState) -> bool:
    # hitstun_frames_left only means hitstun inside damage states (the same slot is reused otherwise)
    return ps.action in DAMAGED and (ps.hitlag_left > 0 or ps.hitstun_frames_left > 0)


def actionable(ps: melee.PlayerState) -> bool:
    """Can a new macro start acting right now (approximate; specials are treated as busy)."""
    a = ps.action
    if a in GROUND_FREE or a in AIR_FREE or a in (A.SHIELD, A.EDGE_HANGING, A.ON_HALO_WAIT):
        return True
    if a == A.LANDING:
        return ps.action_frame >= 4
    if a in DAMAGED:
        return not in_hitstun(ps) and a in (A.TUMBLING, A.DAMAGE_FLY_HIGH, A.DAMAGE_FLY_NEUTRAL, A.DAMAGE_FLY_LOW,
                                            A.DAMAGE_FLY_TOP, A.DAMAGE_FLY_ROLL) and not ps.on_ground
    if isinstance(a, A) and A.NEUTRAL_ATTACK_1.value <= a.value <= A.DAIR.value:
        iasa = framedata().iasa(ps.character, a)
        return 0 < iasa <= ps.action_frame
    return False


def attack_phase(ps: melee.PlayerState) -> str:
    if not isinstance(ps.action, A):
        return ""
    st = framedata().attack_state(ps.character, ps.action, ps.action_frame)
    return {melee.AttackState.WINDUP: "startup", melee.AttackState.ATTACKING: "ACTIVE",
            melee.AttackState.COOLDOWN: "endlag"}.get(st, "")


def edge_x(stage: melee.Stage) -> float:
    return stages.EDGE_GROUND_POSITION.get(stage, 70.0)


def ledge_x(stage: melee.Stage) -> float:
    return stages.EDGE_POSITION.get(stage, 73.0)


def platforms(stage: melee.Stage) -> list[tuple[float, float, float]]:
    """(height, left, right) of each soft platform."""
    out = []
    for f in (stages.left_platform_position, stages.right_platform_position, stages.top_platform_position):
        h, l, r = f(stage)
        if h is not None:
            out.append((h, l, r))
    return out


def ground_below(stage: melee.Stage, x: float, y: float) -> float | None:
    """Height of the highest surface under (x, y), or None over the void."""
    cands = [h for h, l, r in platforms(stage) if l <= x <= r and h <= y + 1]
    if abs(x) <= edge_x(stage) and y >= -1:
        cands.append(0.0)
    return max(cands) if cands else None


def stage_text(stage: melee.Stage) -> str:
    e, bz = edge_x(stage), stages.BLASTZONES.get(stage)
    plats = "; ".join(f"y={h:.0f} x[{l:.0f},{r:.0f}]" for h, l, r in platforms(stage)) or "none"
    s = f"Stage {stage.name.title().replace('_', ' ')}: main floor y=0 from x=-{e:.0f} to {e:.0f} (ledges at ±{ledge_x(stage):.0f}); platforms: {plats}."
    if bz:
        s += f" Blast zones: x=±{bz[1]:.0f}, top y={bz[2]:.0f}, bottom y={bz[3]:.0f}."
    return s


def velocity(ps: melee.PlayerState) -> tuple[float, float]:
    vx = (ps.speed_ground_x_self if ps.on_ground else ps.speed_air_x_self) + ps.speed_x_attack
    return float(vx), float(ps.speed_y_self + ps.speed_y_attack)


def player_obs(ps: melee.PlayerState, stage: melee.Stage) -> dict:
    vx, vy = velocity(ps)
    e = edge_x(stage)
    return {
        "char": ps.character.name, "x": round(float(ps.position.x), 1), "y": round(float(ps.position.y), 1),
        "vx": round(vx, 2), "vy": round(vy, 2), "facing": "R" if ps.facing else "L",
        "pct": round(float(ps.percent)), "stocks": int(ps.stock), "action": action_name(ps),
        "af": int(ps.action_frame), "phase": attack_phase(ps), "ground": bool(ps.on_ground),
        "offstage": bool(ps.off_stage), "shield": round(float(ps.shield_strength)), "jumps": int(ps.jumps_left),
        "invuln": bool(ps.invulnerable), "hitlag": int(ps.hitlag_left),
        "hitstun": int(ps.hitstun_frames_left) if ps.action in DAMAGED else 0,
        "actionable": actionable(ps), "edge_dist": round(e - abs(float(ps.position.x)), 1),
        "on_ledge": ps.action in LEDGE,
    }


def observe(gs: melee.GameState, port: int, opp_port: int) -> dict:
    me, op = gs.players[port], gs.players[opp_port]
    o = {"frame": int(gs.frame), "time_left": max(0, GAME_SECONDS - max(int(gs.frame), 0) // FPS),
         "stage": gs.stage.name, "me": player_obs(me, gs.stage), "opp": player_obs(op, gs.stage)}
    dx = float(op.position.x - me.position.x)
    dy = float(op.position.y - me.position.y)
    o["rel"] = {"dx": round(dx, 1), "dy": round(dy, 1), "dist": round((dx * dx + dy * dy) ** .5, 1),
                "me_facing_opp": (dx >= 0) == bool(me.facing), "opp_facing_me": (dx <= 0) == bool(op.facing)}
    o["projectiles"] = [
        {"type": getattr(p.type, "name", "unknown").lower(), "owner": "me" if p.owner == port else "opp",
         "dx": round(float(p.position.x - me.position.x)), "dy": round(float(p.position.y - me.position.y)),
         "vx": round(float(p.speed.x), 1)}
        for p in sorted(gs.projectiles, key=lambda p: abs(p.position.x - me.position.x))[:3]
    ]
    return o


def _side(dx: float, dy: float) -> str:
    h = "right" if dx > 3 else "left" if dx < -3 else "level"
    v = "above" if dy > 8 else "below" if dy < -8 else ""
    return f"{h}{'+' + v if v else ''}"


def _render_player(label: str, p: dict) -> str:
    where = "ON LEDGE" if p["on_ledge"] else "OFFSTAGE" if p["offstage"] else "ground" if p["ground"] else "air"
    act = f"{p['action']} f{p['af']}" + (f" [{p['phase']}]" if p["phase"] else "")
    flags = [f"jumps {p['jumps']}"]
    if p["shield"] < 55:
        flags.append(f"shield {p['shield']}/60")
    if p["invuln"]:
        flags.append("INVULNERABLE")
    if p["hitlag"]:
        flags.append(f"hitlag {p['hitlag']}")
    if p["hitstun"]:
        flags.append(f"hitstun {p['hitstun']}")
    flags.append("actionable" if p["actionable"] else "busy")
    return (f"{label} {p['char']} {p['pct']}% {p['stocks']}stk | pos ({p['x']:.0f},{p['y']:.0f}) vel ({p['vx']:+.1f},{p['vy']:+.1f}) "
            f"face {p['facing']} {where} | {act} | {', '.join(flags)} | {p['edge_dist']:.0f} from edge")


def render(o: dict, events: str = "") -> str:
    """Compact prompt text (~120-200 tokens)."""
    t = o["time_left"]
    r = o["rel"]
    lines = [
        f"f{o['frame']} time {t // 60}:{t % 60:02d}",
        _render_player("YOU", o["me"]),
        _render_player("OPP", o["opp"]),
        f"REL opp is {_side(r['dx'], r['dy'])}: dx {r['dx']:+.0f} dy {r['dy']:+.0f} dist {r['dist']:.0f}; "
        f"you {'face' if r['me_facing_opp'] else 'face AWAY from'} opp; opp {'faces' if r['opp_facing_me'] else 'faces away from'} you",
    ]
    if o["projectiles"]:
        lines.append("PROJ " + "; ".join(f"{p['owner']} {p['type']} at dx {p['dx']:+d} dy {p['dy']:+d} vx {p['vx']:+.1f}"
                                         for p in o["projectiles"]))
    if events:
        lines.append(f"EVENTS {events}")
    return "\n".join(lines)


class EventTracker:
    """Feed every frame; `drain()` returns what happened since the last drain as one short line."""

    def __init__(self, port: int, opp_port: int):
        self.port, self.opp = port, opp_port
        self.prev: dict[int, tuple] = {}
        self.events: list[str] = []
        self.dealt = self.taken = 0.0
        self.hits_dealt = self.hits_taken = 0

    def update(self, gs: melee.GameState) -> None:
        for p, who in ((self.port, "you"), (self.opp, "opp")):
            ps = gs.players.get(p)
            if ps is None:
                continue
            cur = (float(ps.percent), int(ps.stock), ps.action, bool(ps.off_stage))
            if p in self.prev:
                pct, stock, act, off = self.prev[p]
                if cur[1] < stock:
                    self.events.append(f"{'YOU' if who == 'you' else 'OPP'} LOST A STOCK ({cur[1]} left)")
                elif cur[0] > pct + 0.5:
                    if who == "opp":
                        self.dealt += cur[0] - pct
                        self.hits_dealt += 1
                    else:
                        self.taken += cur[0] - pct
                        self.hits_taken += 1
                if ps.action != act:
                    a = ps.action
                    if a == A.EDGE_CATCHING:
                        self.events.append(f"{who} grabbed ledge")
                    elif a == A.SHIELD_BREAK_FLY:
                        self.events.append(f"{who} SHIELD BROKE")
                    elif a in GRABBED and act not in GRABBED:
                        self.events.append(f"{who} got grabbed")
                    elif a in TECHS:
                        self.events.append(f"{who} teched")
                    elif a in MISSED_TECH:
                        self.events.append(f"{who} missed tech")
                    elif a == A.ON_HALO_WAIT:
                        self.events.append(f"{who} respawned")
                if cur[3] and not off and ps.action in DAMAGED:
                    self.events.append(f"{who} knocked offstage")
            self.prev[p] = cur

    def drain(self) -> str:
        parts = []
        if self.hits_dealt:
            parts.append(f"you hit opp {self.hits_dealt}x +{self.dealt:.0f}%")
        if self.hits_taken:
            parts.append(f"you got hit {self.hits_taken}x +{self.taken:.0f}%")
        parts += self.events
        self.events, self.dealt, self.taken, self.hits_dealt, self.hits_taken = [], 0.0, 0.0, 0, 0
        return "; ".join(parts)
