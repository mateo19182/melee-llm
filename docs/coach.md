# LLM coach

A fast learned policy (the **body**) plays every frame, and an LLM (the **coach**) changes its strategy every few seconds without pressing buttons. The default body is [Reyn-26C](bots.md#reyn-language-steerable), which takes English commands; HAL also works, steered through two numeric knobs.

This page covers the design and the first pilot. The rated results, and why coaching helps, are in the [coach deep-dive](coach-deepdive.md).

```sh
uv run -m melee_llm.match --iso ~/melee.iso --p1 "coach:haiku,interval=300" --p2 cpu:9 --mode lockstep
uv run -m melee_llm.match --iso ~/melee.iso --p1 "coach:haiku,body=hal,body_arg=MASTER" --p2 phillip:gm
uv run -m melee_llm.match --iso ~/melee.iso --p1 "reyn:Keep your distance and shoot lasers." --p2 cpu:9   # fixed command
uv run -m melee_llm.match --iso ~/melee.iso --p1 "coach:random,interval=300" --p2 cpu:9                 # random coach
```

Spec: `coach:<model>[,body=reyn|hal,interval=60,body_arg=...,command=<id>,timeout=10,history=4]`. `<model>` is a CLIProxy model id, `haiku`/`sonnet` for short, or `random`. `interval` is the number of frames between coach calls and `command` a starting command id. Use `lockstep` (or `fast`) mode, as for every learned bot.

## Design

`melee_llm/agents/coach.py`, class `CoachedBot(Agent)`:

- **The body owns the frame.** The LLM call runs on a background thread, so `step()` never waits for it. A new request is queued once `interval` frames have passed and none is in flight.
- **What the coach sees** (about 1,850 prompt tokens per call in the pilot, about half of it the command menu): the rendered state of both players, the events since its last call, its last 4 commands with what happened after each, and the current command.
- **What it answers**: strict JSON. For Reyn: `{"command": "<id>|keep|none", "why": "..."}`. For HAL: `{"return_target": number|null, "temperature": number, "why": "..."}`. An unknown id counts as `keep` and is logged as an error.
- **Command menu**: `reyn_commands(character, stage)` turns Reyn's command list (`vendor/Reyn/docs/commands.md`, `commands.csv`) into ids such as `aggressive_play` or `laser_camping`, each mapped to Reyn's own example phrase, and filters them by character and stage. Fox on Battlefield gets 106 commands. The LLM picks an id, not free text, because Reyn's router almost never abstains, even on nonsense (see [bots.md](bots.md#reyn-language-steerable)), so free text would be silently misrouted.
- **Log**: `<replay>.p<port>.coach.jsonl`. One `decision` record per call (the prompt `state`, `command`, `phrase`, `changed`, `why`, latency, tokens, and `router`, Reyn's reply with the command it holds afterwards), then a `game_end` summary.
- **Controls**: `coach:random` picks a uniformly random menu id (or `none`) at the same interval, with no LLM. `reyn` is the same body, uncoached. `reyn:<phrase>` holds one fixed command all game.

## Pilot (2026-11-13)

Fox on Battlefield and Final Destination, in `lockstep` mode, Haiku as coach, `interval=300` frames (about one call every 5 s of game time). Results from `uv run scripts/coach_pilot.py summary replays/coach-pilot/{cpu9,phillip,phillip2}`.

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

- **Steering works.** One fixed command visibly changes play: "shoot lasers" multiplies the laser rate and nearly doubles the distance to the opponent, and "Be more aggressive" halves game length (4,432 frames vs 9,431).
- **Any steering beats no steering against CPU 9**, and against Phillip gm everything loses.
- **No evidence that the LLM helps beyond that.** Haiku sits between the random coach and a fixed command, and with n = 3-6 per cell the differences are within noise.
- **Coach behaviour.** Haiku made 240 decisions in 12 games and changed the command 127 times (53%), with 1.3 s mean latency, no errors and no router abstentions. The random coach changed command almost every call, and four of its picks were abstained.
- **Caveat: Reyn was slow in this pilot.** Its per-frame round trip was p50 32-42 ms and p99 145-210 ms, so these games ran at 15-21 fps, not 60, and the coach's 1.3 s latency was about 25 game frames, against 76 at full speed ([deep-dive](coach-deepdive.md)). Since 2026-11-14 Reyn runs at 58-59 fps (see [bots.md](bots.md#reyn-language-steerable)), so the pilot's results are not directly comparable with later runs.

### Next experiments

The bench has since run the first one (many games per coach against a graded field, with Sonnet and GPT coaches too); see the [deep-dive](coach-deepdive.md). Still open:

1. **A scouting report:** the opponent's recent habits summarised in the prompt, for a slower coach at `interval=600`.
2. **Coach HAL with numeric knobs** (`return_target` and `temperature`), at real-time speed.
