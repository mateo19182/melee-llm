# Status: what we built, what we learned, what's left

As of 2026-11-14. This page is the map; each track's details are in its own doc.

## The question

Where do LLMs land on one Elo scale for real Super Smash Bros. Melee? The scale covers every way an LLM can be in the loop, next to built-in CPUs, learned bots and (later) a human. The write-up is titled **Melee bots are getting really good**.

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
| Web UI | https://melee.m19182.dev, public since 2026-11-14 and styled after Melee's menus: Bench, Live, All matches, Launch, Games, Arena, Docs, Write-up. Visitors browse and queue limited matches; Mateo signs in at `/login`. | [web-ui](web-ui.md) |
| Netplay | You vs any bot over Slippi Direct Connect. Built, not yet played. | [netplay](netplay.md) |
| Live commentary | Play-by-play ticker on the Live page, plus an optional two-caster LLM booth with ElevenLabs voices (only while someone listens). | [web-ui](web-ui.md) |
| Simulator | `--mode sim`: games in melee-sim-light (Melee's decompiled gameplay code), no Dolphin. Checked frame for frame against Dolphin replays. Learned bots run in it through Slippi events; no CPUs. | [simulator](simulator.md) |
| MeleeBot | Our own behaviour-cloned Yoshi (`train/`). `bc-6m-v1` lost 12 of 12 to CPU 9; `bc-20m-v2` won 1 of 12. | `train/` |
| Local play | `play.py`: play any bot on the laptop with a controller. | [local-play](local-play.md) |
| Write-up | "Melee bots are getting really good": history and why now, how the best bots work, findings, on one page at `/writeup/`. | `writeup/` |

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

Mateo gives the project one or two more weeks (decided 2026-11-14). LLMs are no longer the centre. Three goals:

1. **A published post.** The write-up at `/writeup/` is the draft; it moves to his blog when finished.
2. **His own bot climbing [stomped.dev](https://stomped.dev)**, to learn how these bots are trained.
3. **Something playable:** people watch or play bots through the public site and local play.

| Thread | Covers | Now / next |
|---|---|---|
| **Melee hub** (server) | The map, bench, deploys, coordination, write-up, docs | Write-up restyled and reframed; docs tightened. Later: rate MeleeBot and Mateo (`human:mateo`) on the bench, cheap entrants (Jev with named features, MIMIC on Mateo's replays) |
| **Melee B · Own bot** (server) | `train/`, `meleebot`, `data/train/` | `bc-20m-v2` beat CPU 9 once in 12. Next: a stomped.dev deployment (small US-East server), inference fast enough for a bigger model, fine-tuning on aMSa's replays, self-play in the simulator |
| **Melee D · Play** (laptop) | Local play (`play.py`), [netplay](netplay.md), MeleeBot speed on the laptop | Both demo bots hold 60 fps. Open: a full game with the GameCube controller against each |
| **Melee F · Web** (server) | `melee_llm/web/static`, the public site | Melee menu look and the public site are live (PR #30) |
| **Melee I · Bot-writer** (server) | `melee_llm/botwriter/` | Round 2 proposal: more runs per model, iteration, practice in the simulator |

Done: **C · Simulator** (`--mode sim`, frame-exact and ~100× faster than headless Dolphin; next steps in [simulator](simulator.md#next-work)), **G · Public site** (merged into F's PR #30), **H · Showcase** (write-up, backup clip, demo script).

Parked: two LLMs sharing a character, image-only player, Melee puzzles, simulator scenario probes.

Open: `tests/test_shared.py::test_every_kind_builds_with_its_character` fails without `TYPESAFE_API_KEY`; it should skip.

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
