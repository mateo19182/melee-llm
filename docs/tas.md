# Tool-assisted Melee (TAS)

What tool-assisted play is in Melee, its history, records, tools and RNG, and why it is close to what this repo does. Compiled from web research on 2026-11-16. Each claim has a link; **[ours]** marks ideas and observations from this repo, not from the TAS community.

## 1. What a TAS is

- A **tool-assisted superplay** (or speedrun) is an input file built on an emulator with frame advance, savestates and rerecording, then played back from power-on. Playback is deterministic, so the same inputs give the same game every time ([SmashWiki](https://www.ssbwiki.com/Tool-assisted_superplay)).
- It shows what the game allows, not what a human can do: frame-perfect inputs every frame, exact stick angles, manipulated randomness, and "controllers" no human could hold.
- **TAS vs bot [ours]:** a TAS is open loop. It knows the whole future, because every opponent and random event is fixed by the inputs, and it is searched offline with unlimited retries. A bot is closed loop: it sees each frame once, has 16.7 ms, and faces an opponent it can't rewind. Both read the same game state and press the same virtual controller.

## 2. History in Melee

| When | What |
| --- | --- |
| 2005 | **"AR videos."** An Action Replay unlocks the game's hidden debug menu, which has a frame-by-frame mode. People built input sequences by trial and error and spliced captured frames into video. Examples: SuperDoodleMan's [*Perfect Control*](https://smashboards.com/threads/perfect-control-ar-video-finished.48700/) (Feb 2005: float-cancelled n-airs, multishines, Samus's super wavedash) ([SmashWiki](https://www.ssbwiki.com/Tool-assisted_superplay)) |
| 2007 | ajp_anton starts making Break The Targets TASes in debug mode, and helps real-time runners find strategies ([TASVideos #7174](https://tasvideos.org/7174S)) |
| ~2010 | Dolphin gets usable TAS tools (savestates, frame advance, input movies). ajp_anton moves to it; JPleal10 makes the first "true" TAS, Falcon against three CPUs without taking damage. Wak, MUGG and SW-1988 compete on Home-Run Contest and Event Match videos and replace the old AR videos ([SmashWiki](https://www.ssbwiki.com/Tool-assisted_superplay)) |
| 2011 | A Smashboards [getting-started guide](https://smashboards.com/threads/ssb-melee-tas-getting-started-dl-link-fixed.314975/) for Dolphin TASing; the first Melee submission to TASVideos (All-Star) |
| 2013 | numerics's Adventure Mode TAS (Samus, glitch-heavy), published on TASVideos with 100% approval ([TASVideos](https://tasvideos.org/Games/844)) |
| 2015 | PracticalTAS starts his Melee channel. MUGG keeps a [records page](https://tasvideos.org/GameResources/GC/SuperSmashBrosMelee/Records?revision=136) of every character in every single-player mode |
| 2016–2021 | The 20XX hack pack shows exact positions and speeds on screen, Gecko codes tame the RNG stages, and new routes push the Target Test sum down fast: 22 of 25 TAS records fall in 2020–2021 ([TASVideos #7174](https://tasvideos.org/7174S)) |
| 2019 | PracticalTAS's [69-hit combo video](https://www.youtube.com/watch?v=F-mUcQXeSSc) and the Peach Break The Targets documentary (Dec 2019, 1.1M views) |
| 2021 | Two TASVideos publications by PracticalTAS: All-Star pacifist (Luigi wins without dealing damage) and Target Test, all 25 stages, with ajp_anton, Mario 64 Master and tauKhan |
| 2024 | PracticalTAS publishes [ssbm-lua-core](https://github.com/practicaltas/ssbm-lua-core), Lua helpers for Melee on Dolphin Lua Core |

**TASVideos publications** ([game page](https://tasvideos.org/Games/844), [goals](https://tasvideos.org/Games/844/Goals/List)):

| Goal | Author | Time | Published |
| --- | --- | --- | --- |
| Adventure Mode | numerics (Samus) | 10:23.48 | 2013 |
| Classic Mode, hardest difficulty, played for entertainment | Noxxa | 5:36.93 | May 2020 |
| All-Star Mode, pacifist | PracticalTAS (Luigi) | 7:12.22 | Jul 2021 |
| Target Test, all 25 characters | PracticalTAS, Mario_64_Master, ajp_anton, tauKhan | 6:55.73 (in-game 2:39.97) | Aug 2021 |

## 3. Records and showpieces

- **Break The Targets.** Each character has a 10-target stage of 2.6–12.7 seconds. The TAS sum is 2:39.97 in-game. The sum of the real-time records was 2:56.73 in 2021 ([TASVideos #7174](https://tasvideos.org/7174S)).
- **The sub-3:00 bounty (2019–2020).** Real-time players were stuck at 3:00.87 after ten years of gains of a third of a second per year. In Feb 2019 the Smash Stadium Discord put money on every frame saved, about $31 a frame, $1,658.90 total. A new Pikachu route took it under 3:00 on 2 Jan 2020, finished by Moody. Then an "early cloud" for Ice Climbers, a strategy taken from TAS, saved 91 frames, more than the whole 53-frame bounty, and by March 2020 the sum was 2:57.93. Told in Summoning Salt's [*Melee: The Quest for Sub 3:00*](https://www.youtube.com/watch?v=qsT08n_96p4) (Jun 2025). It is the clearest case of TAS findings flowing back into human play.
- **Home-Run Contest.** Past 3458.5 m (11,347.2 ft) the ground stops being solid, the bag never lands and no score is saved. Ganondorf reaches the limit in real time, Ice Climbers with the freeze glitch, Peach only with TAS. With the limit hacked out, TAS reaches 6,640.8 m with Ganondorf, and a perfect-RNG Peach is estimated at about 91.6 km (300,510 ft), if the RNG can even produce that sequence ([SmashWiki](https://www.ssbwiki.com/Home-Run_Contest), [TAS playlist](https://www.youtube.com/playlist?list=PLP-fO_NfCBaqUn-Ffu9prgx7n7Qu-e5HJ)).
- **Combo videos.** TAS lets every link be frame perfect and every DI chosen:
  - [Every combo ends at exactly 69 hits](https://www.youtube.com/watch?v=F-mUcQXeSSc) (2019): eleven characters manage it without stage help ([EventHubs](https://www.eventhubs.com/news/2019/aug/28/tas-super-smash-bros-melee-combo-video-practical-tas-hits-crazy-69-hit-combos/)).
  - TAS recreations of tournament moments (Mew2King's triple dip on Armada; Axe vs SFAT), "Two Foxes, One Controller", and per-character 0-to-death true-combo videos (2022).
- **Speedrun bridge.** Many single-player records are tracked for both TAS and real time (RTA), and TAS routes regularly become RTA routes, as with Ice Climbers' early cloud ([speedrun.com forum](https://www.speedrun.com/ssbm/forums/igvke)).

## 4. How it's done

- **Dolphin's built-in tools** ([tutorial](https://www.youtube.com/watch?v=M0Cxf8NhlpY), [Dolphin blog](https://dolphin-emu.org/blog/2014/12/01/dolphin-progress-report-november-2014/)):
  - Frame advance, savestate slots, and input movies (`.dtm`, the inputs per poll plus a header with game ID, VI and tick counts).
  - The TAS Input window, a virtual controller with exact stick and trigger values.
  - Read-only mode, which plays back the movie and lets you take over at any frame.
- **Determinism settings:**
  - Turn off dual core and idle skipping.
  - Keep the memory card's settings (language, rules) identical, or the movie desyncs.
  - Disc loading times can desync menu transitions; Slippi hit the same problem with replays ([Fizzi](https://medium.com/project-slippi/fighting-desyncs-in-melee-replays-370a830bf88b)).
- **Scripting:**
  - [Dolphin Lua Core](https://github.com/SwareJonge/Dolphin-Lua-Core) (SwareJonge): Lua reads and writes inputs every frame, reads memory and draws text on screen. The 2021 Target Test TAS was made on v3.5.
  - [ssbm-lua-core](https://github.com/practicaltas/ssbm-lua-core): Melee helpers on top of it, such as `getRngSeed()`, info text and automatic character select. PracticalTAS generates long input scripts from Python.
  - The [Dolphin TAStudio fork](https://tasvideos.org/Forum/Topics/22160) adds a piano-roll editor.
  - [Dolphin Memory Engine](https://github.com/aldelaro5/dolphin-memory-engine) is for finding addresses.
- **Debug mode caveat:** debug-mode videos ignore move staling, so moves always deal full damage and knockback, and they don't match console. That is why Dolphin TASes replaced them even when slower ([TASVideos records page](https://tasvideos.org/GameResources/GC/SuperSmashBrosMelee/Records?revision=136)).
- **Stick precision:** the stick's input logic and every reachable coordinate are mapped in [ssbm-stickmap](https://github.com/practicaltas/ssbm-stickmap). TASes use exact angles that humans can't hit reliably; air dodges have 6,456 distinct angles ([TASVideos #7174](https://tasvideos.org/7174S)).
- **On real hardware:** [gcbot](https://github.com/jiinurppa/gcbot) plays `.dtm` files into a real GameCube through a Raspberry Pi Pico. Its author doubts frame-perfect TASes survive, because disc seek timing varies on console.

## 5. RNG

From the Target Test submission ([TASVideos #7174](https://tasvideos.org/7174S)), the most detailed public write-up:

- **The generator:** a single 32-bit seed at a fixed address, advanced by a linear congruential generator, `seed = seed × 214013 + 2531011 mod 2³²`, once per random call, not once per frame.
- **The starting seed** comes from the GameCube's timebase register (`mftbl`). On console it can be anything. Dolphin starts it from the clock time, so a TAS picks its start date to pick its seed: only 1 seed in 32 is reachable that way, and the game spends 42 calls during startup.
- **Steering the seed:**
  - Each random character pick on the select screen spends exactly 2 calls (character, then colour).
  - Holding L to get random stage music spends 1.
  - The authors chain stages so that one stage's final seed lands near the next stage's good one.
- **Why it matters:** five target stages are random (Samus's grapple shape, Bowser's fire angles, Peach's turnips...). Finishing the first four back to back without manipulation has odds of about 1 in 6 quadrillion, far below the 4.3 billion seeds there are. A conservative estimate puts the attempts behind the 2021 run at hundreds of thousands.
- **Slippi** stores the seed in its replays and restores it with every player's inputs, so replays stay in sync even when RNG calls happen in a different order ([Fizzi](https://medium.com/project-slippi/fighting-desyncs-in-melee-replays-370a830bf88b)). The Frame Start event (0x3A) carries it.

## 6. Search instead of hand-crafting

Other communities automate TAS work with search, usually on top of a decompilation:
- **Super Mario 64:** RNG brute-forcers replay a fixed input file under every possible seed and filter outcomes ([SM64Scripts](https://github.com/MikeXander/SM64Scripts)). Input brute-forcers randomly perturb stick angles and keep improvements, simulated annealing with a fitness over position, speed or action ([sm64-bruteforce-gui](https://github.com/tjk113/sm64-bruteforce-gui)). The fastest ones run the decompiled game code directly instead of an emulator ([sm64_bruteforcers](https://github.com/FramePerfection/sm64_bruteforcers), built from n64decomp).
- **Bounded exhaustive search:** a BizHawk script tries every timing inside user-given windows for a few button presses and keeps the best by a RAM-defined goal ([TASVideos forum](https://tasvideos.org/Forum/Topics/14693)).
- **Tom7's [learnfun/playfun](http://tom7.org/mario/)** (2013) learned an objective from RAM orderings in a human playthrough, then searched inputs to play NES games.

Nothing like this is public for Melee that we found: Melee TAS work is still Lua scripts plus frame-by-frame editing by hand.

## 7. Why this is adjacent to this repo [ours]

- **The simulator is a TAS engine.** [melee-sim-light](simulator.md) is the decompiled game logic with save/restore of a whole game, at about 17,500 frames/s on one thread here (about 100× our headless Dolphin) and batched. Our `melee_llm/sim/world.py` already has `save()`/`restore()`, and `sim/scenes.py` reaches a situation from plain inputs and saves it. That is the setup SM64's decomp bruteforcers use.
- **Limits of the simulator for TAS:**
  - Versus matches only, with UCF on. No menus, so no Target Test, Home-Run Contest or Classic Mode.
  - Its RNG is not Dolphin's, so a sequence found in the simulator replays exactly on Dolphin only if it makes no random calls.
  - No CPU opponents.
- **Ideas, roughly by cost:**
  1. **Feasibility checks:** given a saved scene, search inputs for "does any sequence survive this edgeguard / escape this combo / kill from here by frame N?" Ground truth for coaching and bot-writer prompts, and for spotting where our bots leave options unused.
  2. **Optimal-play labels:** run short-horizon searches (bounded windows as in the BizHawk script, annealing on stick angles) from many replay states, against the opponent's recorded inputs, and use the results as targets for the Yoshi bot. This is "search at training time, not at play time", the thing a 16 ms budget rules out live.
  3. **A TAS ceiling for benchmarks:** the fastest possible kill from a set of fixed start states gives an absolute scale next to the Elo boards.
  4. **TAS-style replays of bench moments:** recreate a bench game's key exchange with frame-perfect alternatives, as PracticalTAS did for tournament moments.
- **Caveat that carries over from Melee TAS:** a found sequence is optimal against a fixed opponent. It says nothing about what a reacting opponent does, so it teaches execution and option coverage, not strategy.

## 8. People and sources

| Person | Known for |
| --- | --- |
| PracticalTAS (Andrew Nestico) | The main Melee TAS creator since 2015; TASVideos publications, combo and record-history videos, ssbm-lua-core; also on the UCF team and the Melee controller ruleset, and a rankings statistician ([SmashWiki](https://www.ssbwiki.com/Smasher:PracticalTAS)) |
| ajp_anton | Break The Targets TASes since 2007; held 18 of 25 by 2015 |
| Mario 64 Master, tauKhan | Target Test TAS co-authors |
| Wak, MUGG, SW-1988 | Early Dolphin-era Home-Run Contest, Event and Multi-Man TASes; MUGG kept the records page |
| SuperDoodleMan, Omnigamer | *Perfect Control* (2005), the debug-mode era |
| SwareJonge | Dolphin Lua Core |

**Start with:** the [Target Test submission text](https://tasvideos.org/7174S) (history, RNG, every stage's tricks), [PracticalTAS's channel](https://www.youtube.com/c/PracticalTAS/videos), Summoning Salt's [Quest for Sub 3:00](https://www.youtube.com/watch?v=qsT08n_96p4), and [SmashWiki's TAS page](https://www.ssbwiki.com/Tool-assisted_superplay).
