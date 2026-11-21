# Status: what we built, what we learned, what's left

As of 2026-11-15. This page is the map; each track's details are in its own doc.

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
| **Melee Bench** | One rating for every entrant, anchored to CPU 9 = 1500. Fox ditto on Battlefield and Final Destination. | [bench](bench.md) |
| Web UI | https://melee.m19182.dev, public since 2026-11-14 and styled after Melee's menus: Bench, Live, All matches, Launch, Games, Arena, Docs, Write-up. Visitors browse and queue limited matches; Mateo signs in at `/login`. | [web-ui](web-ui.md) |
| Netplay | You vs any bot over Slippi Direct Connect. Built, not yet played. | [netplay](netplay.md) |
| Live commentary | Play-by-play ticker on the Live page, plus an optional two-caster LLM booth with ElevenLabs voices (only while someone listens). | [web-ui](web-ui.md) |
| Simulator | `--mode sim`: games in melee-sim-light (Melee's decompiled gameplay code), no Dolphin. Checked frame for frame against Dolphin replays. Learned bots run in it through Slippi events; no CPUs. | [simulator](simulator.md) |
| m19182-yoshi | Our own behaviour-cloned Yoshi (`train/`). `bc-6m-v1` lost 12 of 12 to CPU 9; `bc-20m-v2` won 1 of 12. | `train/` |
| Local play | `play.py`: play any bot on the laptop with a controller. | [local-play](local-play.md) |
| Write-up | "Melee bots are getting really good": history and why now, how the best bots work, findings, on one page at `/writeup/`. | `writeup/` |

## What we learned (bench as of 2026-11-15 evening: one board, 4,082 rated games)

Elo is relative to CPU 9 = 1500, ± the 95% half-width.

- **Learned bots are far ahead.** Faynt above 3300 (it has never lost), Phillip gm 2546, HAL 2297, MIMIC 2007, Reyn 1844.
- **Coaching Reyn works because Reyn needs a command, and "Don't die." is the best one** ([coach-deepdive](coach-deepdive.md)).
  - Reyn with no command: 1844. Any single random command held all game: about 2050. A random coach switching every 5 s: 2141 ±100.
  - Reyn holding "Don't die." all game, with no coach: **2452**, level with the Jev coach (2403) and above every LLM coach by point estimate (2130-2324; its own interval is ±162 on 32 games).
  - **Three of four LLM coaches beat the random coach** in 300 direct coach-vs-coach games (2026-11-15, 24.6M tokens): Sonnet 5.5 won 29 of 36 against it, Haiku 4.5 28 of 37, GPT-6 Luna 30 of 45; they rate 2303-2324, level with each other. GPT-6.1 Sol does not (15 of 35, 2130); it is the slowest coach at 3.1 s a call.
  - Jev coaches best because it ends up holding "Don't die." 41% of the time, mostly via a router accident.
- **LLMs playing directly in real time are below CPU 1** (762-878, CPU 1 is 976) **and no better than never asking the model**: the live player's fallback alone scores 824 ±105, random macros 700 ±111. The earlier "about CPU 4" came from wins over scripted bots that stalled, now retired.
- **Given unlimited thinking time, GPT-6.1 Sol beats CPU 9** (1729 ±140). The other paused LLMs land between CPU 7 and CPU 9 (1254-1474, on 19 to 33 games each). Random macros untimed score 732, so here the model does matter.
- **30 minutes of LLM coding gives anything from a CPU 1 to a bot level with MIMIC.** 27 bots from 936 to 1945; 20 beat CPU 9. In round 2 (five runs each at high effort) Opus, Haiku and Sonnet came out level at 1699, 1686 and 1660, because the starter bot they were given is itself at 1685: 60 lines that run in and up-smash. Two of fifteen sessions clearly improved on it ([bot-writer](bot-writer.md)).
- **Screenshots don't help.** Image-only play is worse than text; text plus image is no better than text.
- **CPU levels rise as expected** once they play each other, from about 975 for level 1 to 1447 for level 8 and 1500 for level 9 (±83 to ±98). The earlier "not monotonic" was too few games.
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
| **Melee hub** (server) | The map, bench, deploys, coordination, write-up, docs | Write-up restyled and reframed; docs tightened. Later: rate m19182-yoshi and Mateo (`human:mateo`) on the bench, cheap entrants (Jev with named features, MIMIC on Mateo's replays) |
| **Melee B · Own bot** (server) | `train/`, `meleebot`, `data/train/`, [experiment log](experiments/README.md) | Best Yoshi is now Faynt 10M Arena after 1,000 steps of Faynt-style RL in the simulator farm (E32): it beats every Phillip anti-Yoshi agent by 2 to 3 stocks, in the farm and in Dolphin, with no delay. It breaks under any input delay, so stomped.dev (10 frames from here) keeps the bot paused. Next: the same RL at delay 10 (E33). Every experiment is in the [log](experiments/README.md)
| **Melee D · Play** (laptop) | Local play (`play.py`), [netplay](netplay.md), m19182-yoshi speed on the laptop | Both demo bots hold 60 fps. Open: a full game with the GameCube controller against each |
| **Melee F · Web** (server) | `melee_llm/web/static`, the public site | Melee menu look and the public site are live (PR #30) |
| **Melee I · Bot-writer** (server) | `melee_llm/botwriter/`, bench rules | Round 2 done and on the bench; Mateo stopped it there. Open: a rerun from a weak starter, a round robin among the written bots, a written bot on stomped.dev |

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
