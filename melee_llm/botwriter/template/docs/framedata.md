# Frame data

libmelee ships three CSVs inside the `melee` package. Your bot may read them at import time
(evaluation allows reads from the installed package):

```sh
python -c "import melee, os; print(os.path.dirname(melee.__file__))"
```

| file | content |
| --- | --- |
| `framedata.csv` (6.6 MB) | Per character, action and frame: up to 4 hitboxes (status, size, x and y relative to the character, facing right), locomotion, iasa, projectile flag. Keys are numeric: `character` = `melee.Character` value, `action` = `melee.Action` value. |
| `actiondata.csv` | Whether an action's frame counter starts at 0 or 1. |
| `characterdata.csv` | Physics per character: Jumps, Friction, Gravity, TerminalVelocity, MaxWalkSpeed, InitDJSpeed, FastFallSpeed, AirSpeed, AirFriction, AirMobility. |

Use them through `melee.framedata.FrameData()` (see `libmelee.md`). Build any lookup tables once,
in `__init__`, never inside `step`.

Fox numbers (NTSC 1.02, frames at 60 fps). Check them against the CSV before relying on them:
jumpsquat 3, shine hits on frame 1 and can be jump-cancelled from frame 4, up-smash hits frames 7-17
(41 total), neutral air hits from frame 4, firefox charges about 42 frames before travelling, and
after it you are helpless until you land or grab the ledge. Gravity 0.23, fast-fall speed 3.4. Some
actions (shine, jumpsquat) have no rows, so `FrameData` returns -1 for them.
