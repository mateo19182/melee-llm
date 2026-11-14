# LLM coach

An LLM does not press buttons here. A fast learned policy (the **body**) plays every frame, and the LLM (the **coach**) changes the body's strategy every few seconds. The default body is [Reyn-26C](bots.md#reyn-language-steerable), which takes English commands; HAL also works, steered through two numeric knobs.

```sh
uv run match.py --iso ~/melee.iso --p1 "coach:haiku,interval=300" --p2 cpu:9 --mode lockstep
uv run match.py --iso ~/melee.iso --p1 "coach:haiku,body=hal,body_arg=MASTER" --p2 phillip:gm
uv run match.py --iso ~/melee.iso --p1 "reyn:Keep your distance and shoot lasers." --p2 cpu:9   # fixed command
uv run match.py --iso ~/melee.iso --p1 "coach:random,interval=300" --p2 cpu:9                 # random coach
```

Spec: `coach:<model>[,body=reyn|hal,interval=60,body_arg=...,command=<id>,timeout=10,history=4]`. `<model>` is a CLIProxy model id, or `haiku`/`sonnet` for short, or `random`. `interval` is the number of frames between coach calls. `command` sets a starting command id. Use `lockstep` (or `fast`) mode, as for every learned bot.

## Design

`melee_llm/agents/coach.py`, class `CoachedBot(Agent)`:

- **The body owns the frame.** `step()` first runs the body's step (the subprocess round trip), then updates the `EventTracker`. Then it applies a coach reply if one has arrived, and queues a new request once `interval` frames have passed since the last one and none is in flight. The LLM call runs on a background thread, so `step()` never waits for it.
- **What the coach sees** (about 1.7k prompt tokens, half of it the command menu):
  - `state.render(observe(...))`: both players' position, percent, stocks, action, jumps and edge distance, plus the distance between them.
  - The events since its last call (`EventTracker.drain()`): hits dealt and taken with percent, stocks lost, ledge grabs, techs, grabs, offstage knockbacks.
  - Its last 4 commands, each with what happened after it.
  - The current command.
- **What it answers**: strict JSON. For Reyn: `{"command": "<id>|keep|none", "why": "..."}`. For HAL: `{"return_target": number|null, "temperature": number, "why": "..."}`. The client is `melee_llm.llm.LLM` in JSON mode, through the local CLIProxy, with `reasoning_effort=none`. An unknown id counts as `keep` and is logged as an error.
- **Command menu**: `reyn_commands(character, stage)` parses `vendor/Reyn/docs/commands.md` and `commands.csv` into ids such as `aggressive_play`, `laser_camping`, `edgeguard_from_the_stage` or `special_up_b`. Each id maps to Reyn's own example phrase. Spacie techniques are offered only to Fox and Falco, sword moves only to Marth and Roy, fireball moves only to the Marios, and platform commands are dropped on Final Destination. Fox on Battlefield gets 106 commands. The LLM picks an id, so the router always receives a phrase it was trained on: the router almost never abstains, even on nonsense (see [bots.md](bots.md#reyn-language-steerable)), so free text would be silently misrouted.
- **Log**: `<replay>.p<port>.coach.jsonl`, using the replay path from `on_game_start`.
  - One `decision` record per call: `frame`, `asked_frame`, `latency_frames`, `latency_s`, `state` (the prompt), `command`, `phrase`, `changed`, `why`, `error`, tokens, and `router`. `router` is Reyn's reply (`outcome`, `row`, `name`, `score`) and `active` the command Reyn holds afterwards.
  - A final `game_end` record: decisions, changes, abstentions, errors, mean latency, tokens and the body's latency.
- **Controls**:
  - `coach:random` picks a uniformly random menu id (or `none`) at the same interval, with no LLM.
  - `reyn` is the same body, uncoached.
  - `reyn:<phrase>` holds one fixed command all game.

## Pilot (2026-11-13)

Fox on Battlefield and Final Destination, in `lockstep` mode (each game isolated: its own port, replay dir and process group), Haiku as coach, `interval=300` frames (about one call every 5 s of game time). Results from `uv run scripts/coach_pilot.py summary replays/coach-pilot/{cpu9,phillip,phillip2}`.

| Condition | vs | n | W-L | Stock diff | % diff | Mean distance | Laser rate |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Reyn uncoached | CPU 9 | 6 | 6-0 | +1.67 | +2 | 27.1 | 0.002 |
| Reyn, fixed "Be more aggressive." | CPU 9 | 6 | 6-0 | **+3.83** | +14 | 24.5 | 0.013 |
| Reyn, fixed "Keep your distance and shoot lasers." | CPU 9 | 6 | 6-0 | +3.67 | -12 | **46.2** | **0.354** |
| Random coach | CPU 9 | 6 | 6-0 | +3.17 | +1 | 23.6 | 0.012 |
| **Haiku coach** | CPU 9 | 6 | 6-0 | +3.50 | +23 | 22.5 | 0.014 |
| Reyn uncoached | Phillip gm | 5 | 0-5 | -3.00 | -83 | 30.5 | 0.002 |
| Random coach | Phillip gm | 3 | 0-3 | -2.33 | -32 | 26.8 | 0.014 |
| **Haiku coach** | Phillip gm | 6 | 0-6 | -2.67 | -11 | 30.6 | 0.003 |

- **Steering works.** One fixed command visibly changes play: "shoot lasers" raises the laser rate from 0.002 to 0.354 and nearly doubles the distance to the opponent. "Be more aggressive" cuts game length in half (4,432 frames vs 9,431).
- **Any steering beats no steering against CPU 9.** Every steered condition (Haiku, random and both fixed commands) took 3.2-3.8 stocks more than it lost; uncoached Reyn took 1.7 more.
- **No evidence the LLM helps beyond that, yet.** Against CPU 9, Haiku (+3.50) sits between the random coach (+3.17) and a fixed "be aggressive" (+3.83). Against Phillip, everything loses. Haiku did lose by less than uncoached Reyn (-2.67 vs -3.00 stocks, -11 vs -83 percent), but random was close (-2.33). With n = 3-6 per cell these differences are within noise.
- **Coach behaviour.** Haiku made 240 decisions in 12 games and changed the command 127 times (53%), with 1.3 s mean latency, no errors and no router abstentions. It used about 1,850 prompt tokens per call. The random coach changed command almost every call, and four of its picks were abstained.
- **Reyn was slow in this pilot.** Its per-frame round trip was p50 32-42 ms and p99 145-210 ms (upstream `predict` on the CPU, games in parallel on a loaded machine), so these games ran at 15-21 fps, not 60. Since 2026-11-14 Reyn runs as one CUDA graph per frame: 2.2 / 4.6 ms p50/p99 in real lockstep games, 58-59 fps, with identical actions (see [bots.md](bots.md#reyn-language-steerable)). The coach's 1.3 s latency is now about 80 frames instead of 25, so the pilot's results are not directly comparable with new runs.

### Next experiments

1. **Bigger n against a beatable opponent.** Use HAL or a Phillip tier around 50% win rate for uncoached Reyn, with 30+ games per condition, so coach effects can show up in win rate and not only stock difference.
2. **A stronger, slower coach.** Sonnet or GPT at `interval=600`, with the opponent's recent habits summarised in the prompt (a scouting report).
3. **Coach HAL with numeric knobs.** `return_target` and `temperature`, at real-time speed.

