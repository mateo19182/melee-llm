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
  - Before the counter fix, the bench didn't count discarded replies, so real spend is ~115M tokens, not 100M.

## What's left (rough priority)

1. **Fix the bench's token counter** to include discarded replies. Small.
2. **Coach deep-dive.** Why does the Jev coach beat random? Ablations on interval, prompt, named features (e.g. "opponent in endlag") and Jev vs LLM. Cheap: Jev costs cents.
3. **Janky entrants**, dropped into the bench:
   - Jev with named features
   - two LLMs sharing one character
   - an image-only player
   - MIMIC trained on your replays
   - random-command Reyn variants
4. **Netplay with you.** Blocked on a bot Slippi account and a controller; this takes the `human:mateo` slot.
5. **Bot-writer round 2.** 3 runs per model plus GPT, longer sessions, harder scripted opponents. Also fix the tool loop that quits after 3 idle replies.
6. **Write-up "Melee Bot Elo".**
   - Draft at `writeup/`. Not finished on purpose.
   - Decided: name the models, SVG figures, include a 2D replay render.
   - Regenerate the numbers with `python3 writeup/make_figures.py`.
7. **Longer bets:** a fast local brain (a small model trained on our logs, ~50 ms decisions), Melee puzzles (savestate scenarios), a live AI caster, a world model / V-JEPA.

## Running services (user units)

| Unit | Role |
|---|---|
| `melee-web` | Web UI |
| `melee-arena` | Live-slot worker. The arena is switched off. |
| `melee-mediamtx` | Stream server |
| `melee-xvfb`, `melee-xvfb-headless` | Virtual displays :99 and :98 |
| `melee-viewer` | Old Tailscale-only replay viewer |

Finished and stopped: `melee-bench`, `melee-llm-arena`, `melee-ladder*`.
