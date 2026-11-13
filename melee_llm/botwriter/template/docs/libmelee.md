# libmelee condensed reference (vladfi1 fork, `melee` 0.47.x)

To read the full source: `python -c "import melee, os; print(os.path.dirname(melee.__file__))"`.
Read `gamestate.py`, `enums.py`, `framedata.py`, `stages.py` and `techskill.py` there.

## Coordinates

Units are Melee units. x grows to the right and y grows upward. The main stage ground is at
y = 0 (Battlefield and FD). Stage center is x = 0.

- `melee.stages.EDGE_POSITION[stage]`: x of the ledge (positive side; the other ledge is at the
  negative). FD ≈ 88.47, Battlefield ≈ 71.31.
- `melee.stages.EDGE_GROUND_POSITION[stage]`: last x you can stand on.
- `melee.stages.BLASTZONES[stage]`: `(left, right, top, bottom)`. Crossing one loses a stock.
  FD = (-246, 246, 188, -140), BF = (-224, 224, 200, -108.8).
- `melee.stages.top_platform_position(stage)`, `left_platform_position(stage)` and
  `right_platform_position(stage)` each return `(height, left_x, right_x)`. FD has no platforms.

## GameState (`gamestate`)

| field | meaning |
| --- | --- |
| `frame` | frame counter (starts negative during the countdown) |
| `stage` | `melee.Stage` |
| `players` | dict port → PlayerState |
| `projectiles` | list of Projectile (`position`, `speed`, `owner`, `type`, `expiration_frames`) |
| `distance` | distance between the two players |
| `menu_state` | always IN_GAME or SUDDEN_DEATH when your bot is stepped |

## PlayerState (`gamestate.players[port]`)

| field | meaning |
| --- | --- |
| `character` | `melee.Character` |
| `position.x`, `position.y` | position (feet) |
| `percent`, `stock` | damage and stocks left |
| `facing` | True = facing right |
| `action` | `melee.Action` (395 values, e.g. STANDING, DASHING, KNEE_BEND (jumpsquat), LANDING, SHIELD, EDGE_HANGING, DAMAGE_FLY_*, TUMBLING, DEAD_*) |
| `action_frame` | frame number within the current action (starts at 1) |
| `on_ground` | standing on a surface |
| `off_stage` | beyond the ledges or below the stage |
| `jumps_left` | remaining jumps (Fox: 2 when grounded, 1 after jumping, 0 after double jump) |
| `hitstun_frames_left`, `hitlag_left` | frames left in hitstun or hitlag |
| `invulnerable`, `invulnerability_left` | intangibility (respawn, ledge grab, rolls…) |
| `shield_strength` | 60 = full |
| `speed_air_x_self`, `speed_ground_x_self`, `speed_y_self` | self-induced velocity |
| `speed_x_attack`, `speed_y_attack` | knockback velocity |
| `ecb` (`.top/.bottom/.left/.right` as (x, y) offsets) | environmental collision box |
| `iasa` | interruptible as soon as possible flag |
| `controller_state` | **yours only**; the opponent's is blanked |

## Controller

```python
from melee import Button
c.press_button(Button.BUTTON_A)           # A, B, X, Y, Z, L, R, D_UP... (START is ignored)
c.release_button(Button.BUTTON_A)
c.tilt_analog(Button.BUTTON_MAIN, x, y)   # 0..1, 0.5 = neutral; (0.5, 0) = down
c.tilt_analog(Button.BUTTON_C, x, y)      # C-stick: smash attacks / aerials
c.press_shoulder(Button.BUTTON_L, 0.3)    # analog trigger 0..1 (light shield)
c.release_all()
c.prev                                    # ControllerState sent last frame
```

Fox inputs: jump = X/Y (tap for a short hop; hold through jumpsquat (3 frames) for a full hop).
Laser = B. Shine = down + B (main stick (0.5, 0)). Firefox (up-B) = up + B. Hold a direction while
it charges to aim it. Illusion (side-B) = side + B. Smash attacks = C-stick on the ground. Aerials = C-stick or
A + direction in the air. Wavedash = jump, then air-dodge (L/R + diagonal down) right after
jumpsquat. Fox's up-B actions are named `SWORD_DANCE_*` in `melee.Action` (shared names).
Fox shine is `DOWN_B_GROUND_START`, `DOWN_B_GROUND` and `DOWN_B_AIR`. Laser is `NEUTRAL_B_*` / `LASER_GUN_PULL`.

`melee.techskill.multishine(ai_state=me, controller=c)` and `upsmashes(...)` are small examples.

## FrameData

```python
fd = melee.framedata.FrameData()          # loads the CSVs once: create it in __init__, not per frame
fd.frame_count(char, action)              # total frames of an action
fd.first_hitbox_frame(char, action), fd.last_hitbox_frame(char, action)
fd.iasa(char, action)                     # first actionable frame
fd.is_attack(char, action), fd.is_roll(...), fd.is_grab(...), fd.is_bmove(...), fd.is_shield(action)
fd.attack_state(char, action, action_frame)   # AttackState.WINDUP / ATTACKING / COOLDOWN / NOT_ATTACKING
fd.range_forward(char, action, action_frame), fd.range_backward(...)
fd.in_range(attacker_state, defender_state, stage)   # will attacker's current attack hit? (frames until hit, or 0)
fd.project_hit_location(player_state, stage, frames=-1)  # where knockback will carry a player
fd.roll_end_position(player_state, stage), fd.slide_distance(player_state, initspeed, frames)
fd.dj_height(player_state), fd.frames_until_dj_apex(player_state), fd.max_jumps(char)
fd.characterdata[char]                    # dict: Gravity, TerminalVelocity, FastFallSpeed, AirSpeed, Jumps...
```
