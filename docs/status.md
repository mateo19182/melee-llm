# Status: what we built, what we learned, what's left

As of 2026-11-14. This page is the map; each track's details are in its own doc.

## The question

Where do LLMs land on one Elo scale for real Super Smash Bros. Melee? The scale covers every way an LLM can be in the loop, next to built-in CPUs, learned bots and (later) a human. The working title is **Melee Bot Elo**.

## What exists

| Piece | What it is | Doc |
|---|---|---|
| Game engine | Real Melee (your ISO) in Slippi Dolphin, driven by libmelee. Modes: lockstep (rendered, 60 fps), realtime (headless, 60 fps), fast (headless, as fast as possible), paused (waits for each input). | README |
| Learned bots | HAL, Phillip (several tiers), MIMIC, Faynt, and Reyn (takes English commands). All run on the 3090. | [bots](bots.md) |
| LLM plays directly | Text state goes to an LLM, which picks a macro action. Paused (unlimited thinking time) or live (real time). | [llm-player](llm-player.md) |
| Jev | TypeSafe's fast decision model (~0.16 s), as player and as coach. | [jev](jev.md) |
| LLM coach | An LLM picks Reyn's command every few seconds while Reyn plays at 60 fps. | [coach](coach.md) |
| Bot-writer | A coding agent gets 30 minutes to write a Python bot, which is then laddered. | [bot-writer](bot-writer.md) |
| Perception test | Screenshots vs text state. | [perception](perception.md) |
| LLM vs LLM arena | Paused LLMs play each other. | [llm-arena](llm-arena.md) |
| **Melee Bench** | One rating per track for every entrant, anchored to CPU 9 = 1500. Fox ditto on Battlefield and Final Destination. | [bench](bench.md) |
| Web UI | https://melee.m19182.dev (you only): Bench, Live, All matches, Launch, Games, Arena, Docs. | README |
| Netplay | You vs any bot over Slippi Direct Connect. Built, not yet played. | [netplay](netplay.md) |
| Live commentary | Play-by-play ticker on the Live page, plus an optional two-caster LLM booth with ElevenLabs voices (only while someone listens). | [web-ui](web-ui.md) |
| Simulator | `--mode sim`: games in melee-sim-light (Melee's decompiled gameplay code), no Dolphin. Checked frame for frame against Dolphin replays. Learned bots run in it through Slippi events; no CPUs. | [simulator](simulator.md) |

## What we learned (final bench: 2,325 real-time games, 1,993 untimed)

Elo is relative to CPU 9 = 1500, ± the 95% half-width.

- **Learned bots are far ahead.** Faynt 3349 ±237, Phillip gm 2489, HAL 2244, MIMIC 1931, Reyn 1765.
- **Coaching Reyn works because Reyn needs a command, and "Don't die." is the best one** ([coach-deepdive](coach-deepdive.md)).
  - Reyn with no command: 1765. Any single random command held all game: ~2020. A random coach switching every 5 s: ~2070-2100.
  - Reyn holding "Don't die." all game, with no coach: **2398**, level with the Jev coach (2346-2371) and above every LLM coach (2132-2275).
  - Jev coaches best because it ends up holding "Don't die." 41% of the time, mostly via a router accident.
- **LLMs playing directly in real time are about CPU 4 strength** (1042-1102).
- **Given unlimited thinking time, GPT-6.1 Sol beats CPU 9** (1691). The other paused LLMs land around CPU 8 (1325-1436).
- **30 minutes of LLM coding gives a CPU-9-class bot.** Sonnet's scored 1664, Haiku's 1605 and Opus's 1536, one run each.
- **Screenshots don't help.** Image-only play is worse than text; text plus image is no better than text.
- **CPU levels aren't monotonic** in Fox ditto (levels 1, 3 and 7 are about equal). This looks like a real Melee quirk.
- **Caveats:**
  - Live GPT-6.1 Sol discards ~95% of its replies because they arrive more than 2 s late, so its live rating is mostly the fallback behaviour.
  - The overnight run counted 100.1M CLIProxy tokens, but discarded replies weren't counted then: real spend was **115.1M** (recounted from the logs; `spent_recounted` in `data/bench/status.json`). Fixed: every call's tokens now count ([bench](bench.md#scheduler-active-sampling-no-token-cap)).

## What's next

Mateo wants all of it, with the LLM-playing side now lower priority. No fixed token budget: spend where games still answer something. On 2026-11-14 evening he shows the project to people (write-up, website, live demos), so the current threads lean toward that.

| Thread | Covers | Now / next |
|---|---|---|
| **Melee A · Hub** (server) | The map, bench, deploys, coordination | Coach deep-dive done ([coach-deepdive](coach-deepdive.md)). Later: cheap non-LLM janky entrants (Jev with named features, MIMIC on Mateo's replays) |
| **Melee B · Own bot** (server) | `train/`, `meleebot`, `data/train/` | MeleeBot (`meleebot:bc-6m-v1`, behaviour-cloned Yoshi) plays live; lost its first game 0-3 to CPU 9. Next: a faster model, then the bench |
| **Melee D · Play** (laptop) | Local play (`play.py`), [netplay](netplay.md), MeleeBot inference speed (`train/meleebot/play.py`, with B) | Local play works: 60 fps vs Phillip gm with onnxruntime pinned to 8 threads (opt-in `threads` in `bot_phillip.py`), 2-3 human free-for-all; MeleeBot ~55 fps on the laptop. On branch `local-play`, no PR yet. Next: demo-ready with a controller |
| **Melee F · Web redesign** (server) | Styling and markup in `melee_llm/web/static` | Mockups of a restyle after Melee's real GameCube menus |
| **Melee G · Public site** (server) | A read-only public mode of the web UI on its own hostname | Design for Mateo first; nothing goes public without his OK |
| **Melee H · Showcase** (server) | Write-up "Melee Bot Elo" (`writeup/`), demo script, backup clip | Blog-post write-up of everything built, then a commentated clip with voices, then the demo script |

Done: **Melee C · Simulator**. `--mode sim` runs our agents and the learned bots in melee-sim-light, frame-exact against our replays and ~100× faster than headless Dolphin; next steps in [simulator](simulator.md#next-work) (scenario probes first).

Parked: bot-writer round 2 (also fix the tool loop that quits after 3 idle replies), two LLMs sharing a character, image-only player, Melee puzzles.

Rules: work in worktrees under `~/.t3/worktrees/melee-llm/`; don't change the live checkout while a bench is running (bench games import it); merge and deploy after Mateo's OK.

## Running services (user units)

| Unit | Role |
|---|---|
| `melee-web` | Web UI |
| `melee-arena` | Live-slot worker; the arena fills idle time (`data/arena/`). |
| `melee-mediamtx` | Stream server |
| `melee-xvfb`, `melee-xvfb-headless` | Virtual displays :99 and :98 |
| `melee-viewer` | Old Tailscale-only replay viewer |

Finished and stopped: `melee-bench`, `melee-llm-arena`, `melee-ladder*`.
