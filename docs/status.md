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
| Simulator | `--mode sim`: games in melee-sim-light (Melee's decompiled gameplay code), no Dolphin. Checked frame for frame against Dolphin replays. Controller-driven players only (no CPUs, no learned bots). | [simulator](simulator.md) |

## What we learned (final bench: 2,325 real-time games, 1,993 untimed)

Elo is relative to CPU 9 = 1500, ± the 95% half-width.

- **Learned bots are far ahead.** Faynt 3349 ±237, Phillip gm 2489, HAL 2244, MIMIC 1931, Reyn 1765.
- **Coaching Reyn works, but mostly because any change of command does.**
  - A random coach lifts Reyn from 1765 to 2096.
  - The LLM coaches score 2147-2275, which overlaps the random coach.
  - Only **Jev as coach (2371)** is clearly above random.
- **LLMs playing directly in real time are about CPU 4 strength** (1042-1102).
- **Given unlimited thinking time, GPT-6.1 Sol beats CPU 9** (1691). The other paused LLMs land around CPU 8 (1325-1436).
- **30 minutes of LLM coding gives a CPU-9-class bot.** Sonnet's scored 1664, Haiku's 1605 and Opus's 1536, one run each.
- **Screenshots don't help.** Image-only play is worse than text; text plus image is no better than text.
- **CPU levels aren't monotonic** in Fox ditto (levels 1, 3 and 7 are about equal). This looks like a real Melee quirk.
- **Caveats:**
  - Live GPT-6.1 Sol discards ~95% of its replies because they arrive more than 2 s late, so its live rating is mostly the fallback behaviour.
  - The overnight run counted 100.1M CLIProxy tokens, but discarded replies weren't counted then: real spend was **115.1M** (recounted from the logs; `spent_recounted` in `data/bench/status.json`). Fixed: every call's tokens now count ([bench](bench.md#scheduler-active-sampling-under-a-budget)).

## Lanes (who works on what)

Mateo wants all of these; the LLM-playing side is now lower priority. Budget: moderate, ~10-20M LLM tokens in total, mostly lane A. One T3 thread per lane, titled "Melee <letter> · ...".

| Lane | Owns | Now | Next |
|---|---|---|---|
| **A · Hub** | this map, the bench (`melee_llm/bench*`, `ratings.py`, `entrants.py`), the coach, `scripts/coach_deepdive.py`, `writeup/`, `data/bench*` | Coach deep-dive bench running (`coach-deepdive.service`, `data/bench-deepdive/`); log-mining half in [coach-deepdive](coach-deepdive.md) | Ablation results; cheap non-LLM janky entrants (Jev with named features, MIMIC on Mateo's replays, random-command Reyn variants); write-up "Melee Bot Elo" (draft in `writeup/`, not finished on purpose) |
| **B · Own bot** | `train/`, `meleebot`, `data/train/` | Yoshi behaviour-cloning dataset built from ranked replays | Model design with Mateo, then training; the bot joins the bench through lane A. This is the "fast local brain" bet |
| **C · Simulator** | `--mode sim`, melee-sim-light, [simulator](simulator.md) | PR #4 open | Run learned bots in the sim so bot-only games (and B's training) get cheap. This is the "world model" bet |
| **D · Play** | `human` player, `play.py`, [netplay](netplay.md) | Local play on the laptop works (Phillip); server netplay built but not played | `human` player type in the runner, then Mateo on the bench as `human:mateo` |
| **E · Show** | `melee_llm/web/`, commentator, services, live checkout, deploys | Commentator duo + voice shipped | AI caster, web UI |

Parked: bot-writer round 2 (3 runs per model plus GPT; also fix the tool loop that quits after 3 idle replies), two LLMs sharing a character, image-only player, Melee puzzles.

**Rules for every lane**
1. Work in a worktree under `~/.t3/worktrees/melee-llm/<slug>`. The live checkout `~/projects/ai/melee-llm` is production: only lane E changes it or restarts services, and never while a bench is running (bench games import the live checkout).
2. Open PRs freely; merge only after Mateo says so in that lane's thread.
3. For files another lane owns, keep PRs small and name the owning lane in the PR body.
4. The machine is shared: check `uptime` and `systemctl --user list-units 'melee*' 'coach*'` before heavy jobs (training, dataset builds, benches).
5. Each lane edits only its own row here.

## Running services (user units)

| Unit | Role |
|---|---|
| `melee-web` | Web UI |
| `melee-arena` | Live-slot worker; the arena fills idle time (`data/arena/`). |
| `melee-mediamtx` | Stream server |
| `melee-xvfb`, `melee-xvfb-headless` | Virtual displays :99 and :98 |
| `melee-viewer` | Old Tailscale-only replay viewer |

Finished and stopped: `melee-bench`, `melee-llm-arena`, `melee-ladder*`.
