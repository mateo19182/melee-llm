# Write a Super Smash Bros. Melee bot

Your job: make `bot.py` the strongest Melee bot you can before your time runs out. There is no
submit step. When the session ends, whatever is in `bot.py` is your entry, so keep it loading and
running at all times.

## Match format

- 1v1, **Fox vs Fox**, 4 stocks, 8 minutes, on **Final Destination** and **Battlefield**. You play
  both port 1 and port 2.
- Opponents get harder in tiers: in-game CPUs (levels 1-9), scripted bots, then stronger bots you
  cannot practice against. You can practice against the CPUs, the scripted bots in `opponents/`,
  and older copies of your own bot.
- Score: your average win rate over the evaluation roster, with each opponent weighted equally
  (a draw counts as half a win). Beating stronger opponents counts as much as beating weak ones,
  so don't stop once you beat CPU level 9.

## Bot contract

```python
import melee

class Bot:
    character = melee.Character.FOX        # must be FOX for now
    def step(self, gamestate, controller, port, opp_port): ...
    def on_game_end(self, gamestate): ...  # optional; reset per-game state here
```

- `Bot()` is constructed once and may play several games in a row. Construction and imports must
  finish within 20 s.
- `step` is called once per frame (60 fps) with a `melee.GameState`. Set inputs on `controller`
  (a `melee.Controller`: `press_button`, `release_button`, `tilt_analog`, `press_shoulder`,
  `release_all`). Inputs **persist** between frames until you change them. Holding a button
  does not repeat it, so release it for one frame before pressing it again. `controller.prev`
  is last frame's state. Don't call `flush()`: the harness does.
- **Frame budget: 16 ms per `step`.** A late answer is discarded, and your controller keeps its old
  inputs while you catch up. Exceptions are caught and logged. That frame is lost, and so is the game if it
  keeps happening. If the process dies, your character stands still for the rest of the match.
- `gamestate.players[opp_port].controller_state` is blanked: you cannot see the opponent's inputs.
  Opponent identity (`cpu_level`, names) is hidden too.

## Rules

- One file, `bot.py`. Allowed imports: the Python 3.12 standard library, `melee` (libmelee) and
  `numpy`. Read data at import time only from the `melee` package (frame data CSVs, see
  `docs/framedata.md`), or embed it in `bot.py`.
- No network, no subprocesses, no `ctypes`, no reading or writing files outside the bot's own
  scratch directory during evaluation, and no reading the emulator's memory or the replay being
  recorded. The evaluator enforces this and logs every attempt. A bot that tries is disqualified.
- Don't try to find or read the evaluation harness, the hidden opponents or other entries. Work
  inside this directory.
- Write your own bot. Don't port or copy SmashBot or other public Melee bots, from memory or
  otherwise. Entries are checked for near-copies of SmashBot.

## Tools (run from this directory)

| Command | What it does |
| --- | --- |
| `tools/practice --opponent cpu:7 --games 4 [--stage fd\|bf] [--bot bot.py]` | Plays real games headless and unthrottled. Prints one compact block per game: result, stocks, damage dealt and taken, hits, your deaths (kill or self-destruct, percent, blast zone), % time offstage, your most frequent actions, frame-budget stats. Ends with a JSON line. Replays and `bot-port{1,2}.log` go to `runs/<timestamp>/`. |
| `tools/practice --opponent baseline:rusher` | Scripted opponents. Their source is in `opponents/`. |
| `tools/practice --opponent bot:old/bot_v2.py` / `--opponent self` | Plays against a saved version of your bot, or a copy of the current one. |
| `tools/practice --opponent baseline:rusher --games 10 --sim` | Plays in a simulator that runs Melee's own game code without the emulator: several times faster, same per-game summary. No CPU opponents and no replay files. |
| `tools/inspect-replay runs/.../Game_x.slp --port 1 [--timeline]` | Summary of one replay from a port's point of view. Without `--port`, prints full JSON for both players. |
| `tools/check-bot [--bot bot.py]` | **Offline, needs no game.** Runs your bot over recorded replays and reports exceptions, crashes, policy violations and frame times. Run it after every edit. |
| `tools/time-left` | Time remaining in this session. |

Games alternate spawn ports, and the two ports play at the same time in separate emulators. A
game takes roughly 30 s to 3 min of wall time (longer if nobody dies: 8-minute timeouts), so
`--games 2` is about 1-3 min and `--games 4` about 2-6 min. Give the command a long enough tool
timeout, or run it in the background and read its output later. Several practice commands can
run at once. Games are noisy, so play several before you trust a change. Save versions you like with
`cp bot.py old/bot_vN.py`, then check new versions against them.

`--sim` is for quick iteration against scripted bots and your own versions. Evaluation runs in the
emulator, so confirm a change there before you trust it. Two deterministic bots tend to play the
same game every time in the simulator, so repeats of one matchup are not new evidence: vary the
opponent and the stage instead.

If `tools/practice` says no ISO is configured, you can't play games in this session. Use
`check-bot` and reason from the docs and frame data.

## Reference

- `docs/libmelee.md`: condensed libmelee API (GameState, PlayerState, Action, stages, FrameData).
- `docs/framedata.md`: where the frame data lives and how to use it.
- `opponents/`: the scripted baseline bots, which also show the bot contract working.
