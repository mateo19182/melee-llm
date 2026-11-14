# Melee AI research notes

Background for this repo: the game, the history of Melee bots and how each one works, the tooling, the community and the people. This was compiled from web research on 2026-11-14. Each claim has a link. **[unverified]** means no primary source was found. Bot-specific details on how we wrap them are in [bots.md](bots.md).

## 1. The game, briefly

- **Super Smash Bros. Melee** came out on GameCube in 2001. Its competitive scene is grassroots and has never had Nintendo's support.
  - The documentaries are *The Smash Brothers* (2013, by Samox; [wiki](https://en.wikipedia.org/wiki/The_Smash_Brothers)) and *Metagame* (2020).
  - *Metagame* covers the "Five Gods": Mang0, Armada, Hungrybox, Mew2King and PPMD ([wiki](https://www.ssbwiki.com/Metagame_(documentary))).
- **Current top players** ([SSBMRank 2025](https://liquipedia.net/smash/SSBMRank)): Zain #1, Cody Schwab #2, Hungrybox #3, Joshman, Axe and Jmook; aMSa is #23.
  - Cody won GENESIS X3 in Feb 2026 ([Liquipedia](https://liquipedia.net/smash/GENESIS/X3/Melee)).
  - The Big House has been on hiatus since July 2024 ([wiki](https://en.wikipedia.org/wiki/The_Big_House_(tournament))).
- **Nintendo:**
  - It cancelled Smash World Tour in late 2022 ([SmashWiki](https://www.ssbwiki.com/Cancellation_of_Smash_World_Tour_2022)).
  - In Oct 2023 it published Community Tournament Guidelines: caps of 200 in-person or 300 online entrants and about $5k in prizes, and no modified game versions ([SmashWiki](https://www.ssbwiki.com/Community_Tournament_Guidelines)).
- **Why it survives:** Slippi's rollback netplay (June 2020) kept the game alive through COVID ([SmashWiki](https://ssbwiki.com/Project_Slippi)). Its ranked replays are now the training data for every modern bot.

### Mechanics a bot author needs

The game runs at 60 fps, so one frame is 16.7 ms. Every mechanic below has a SmashWiki page at `https://www.ssbwiki.com/<Term>`.

| Concept | Why it matters for bots |
| --- | --- |
| Wavedash (jump, then air-dodge diagonally into the ground) | Needs a trigger in the action space. HAL's original 5-class button head could not do it; MIMIC moved to 7 classes for this reason ([MIMIC card](https://huggingface.co/erickfm/MIMIC)) |
| L-cancel, SHFFL | Pressing a trigger in a narrow window halves landing lag. MIMIC's RLVR raised its L-cancel rate from 94% to 99% |
| Multishine | Frame-perfect Fox/Falco loop. libmelee ships it as the `shine` demo |
| DI / SDI / ASDI, hitlag | Survival inputs given during hitlag. Behaviour cloning learns them from humans |
| Tech chase | Reading a knockdown option and punishing it. SmashBot needed exact speeds to do it ([libmelee](https://github.com/altf4/libmelee)) |
| Ledge, edgeguarding, recovery | A classic weakness of bots: Nabla admits it, and the CPU never fights off edgeguards |
| Shield, out-of-shield options, powershield | The level 9 CPU almost never shields attacks |
| Top tier: Fox, Falco, Marth, Sheik, Puff, Peach, Falcon | **Fox ditto on Final Destination or Battlefield is the default benchmark matchup** |

## 2. History of the bots

| Year | Bot | Author | Technique |
| --- | --- | --- | --- |
| 2001 | In-game CPU | HAL Laboratory | Scripted. Level sets reaction and commitment, not strategy |
| 2015–16 | SmashBot | Dan "altf4" Petro | Rule-based behaviour tree |
| 2016 | 20XX "AI Overhaul" | Achilles1515 | Patched CPU scripts |
| 2017 | Phillip v1 | Vlad Firoiu, MIT | Pure deep RL from RAM state |
| 2017 | DRQN with 12-frame delay | Sharma & Friedman, Cooper Union | Recurrent DQN |
| 2018 | "At Human Speed" | Firoiu, Ju, Tenenbaum | RL under action delay, plus a predictive model |
| 2020– | slippi-ai / Phillip II | vladfi1 ("x_pilot") | Behaviour cloning on Slippi ranked replays, then self-play RL |
| 2022 | Project Nabla | Bryan Chen | Behaviour cloning (GRU), then PPO |
| 2025–26 | HAL | Eric Gu | Behaviour-cloning transformer, 20M then 247M parameters |
| 2025–26 | MIMIC | erickfm | Behaviour cloning, one transformer per character, plus RLVR |
| Sep 2026 | Jev ("System One") | TypeSafe AI | General decision API, not Melee-specific |
| Oct 2026 | Faynt | Frisson Labs | Behaviour cloning, winner curriculum, then PPO, all 26 characters |
| Nov 2026 | Reyn | Frisson Labs | Faynt-based policy steered by language commands |

### How bots read state and press buttons

All serious bots read structured state, not pixels: positions, speeds, action state and its frame, percent, stocks.

- **2015–2020:** Dolphin's MemoryWatcher streamed hand-mapped RAM addresses. Inputs went back through a named pipe. altf4 called this "a really kludgey way of doing it" ([SmashBot #115](https://github.com/altf4/SmashBot/issues/115)).
- **Since May 2020:** libmelee reads the **Slippi spectator stream** instead (ENet on port 51441, base64 SLP events). It works on Dolphin, on a hacked Wii, and on `.slp` replays. That is why replays became the training corpus.

### In-game CPU (level 1–9)

Level 9 jabs and grabs frame-perfectly. It also:
- dashes only to dash-attack or dash-grab;
- almost never shields physical attacks, though it powershields projectiles;
- has fixed recovery paths and barely edgeguards;
- can be beaten by standing still and spamming one move.

Phillip v1's Q-learner found a trick that made the CPU kill itself. Sources: [SmashWiki AI flaws](https://www.ssbwiki.com/List_of_flaws_in_artificial_intelligence_(SSBM)), [arXiv 1702.06230](https://arxiv.org/abs/1702.06230).

**Level 9 is a sanity check, not a strength measure.** Every learned bot 4-stocks it, which our closed-loop results in bots.md confirm.

### SmashBot (altf4, 2015–2016)

- **Design:** hand-written, with a Goals → Strategies → Tactics → Chains hierarchy. A Chain is an input sequence such as a wavedash or a jump-cancelled upsmash. It uses exact frame data to know when the opponent is actionable.
- **Scope:** originally Fox vs Marth only, on FD or Stadium.
- **History:** presented at DEF CON 24 in 2016. libmelee is "all the SmashBot stuff that is plumbing" split out on 2016-12-31.
- **Fairness:** the FAQ says it "doesn't cheat": it presses a virtual controller, but with zero reaction time.

[repo](https://github.com/altf4/SmashBot), [Bishop Fox write-up](https://bishopfox.com/blog/reversing-video-games-to-create-smashbot-ai), [Hackaday](https://hackaday.com/2016/08/16/creating-unbeatable-videogame-ai/). It is still a good design reference for a rule-based or LLM-written bot, which is what our bot-writer track does.

### Phillip v1 (Firoiu, Whitney, Tenenbaum, 2017)

Paper: "Beating the World's Best at Super Smash Bros. Melee with Deep Reinforcement Learning" ([arXiv 1702.06230](https://arxiv.org/abs/1702.06230), [repo, archived](https://github.com/vladfi1/phillip)).

**Setup:**
- RAM features as input. There were no projectiles, so it played Captain Falcon.
- Acts at 30 Hz with 54 discrete actions: 9 stick positions × 5 single buttons, or none.
- Reward is ±1 per KO plus a small weight on damage.
- Trained with an actor-critic plus entropy bonus (also n-step SARSA), two 128-unit layers, and 50+ parallel Dolphins on the MGHPCC cluster.

**Results:**
- It beat the level 9 CPU within a day.
- After two weeks of self-play it took more stocks than it lost against ten ranked pros at Genesis 4: S2J, Gravy (8–5), Zhu, Mafia and others.
- Coverage: [Quartz](https://qz.com/917221/a-super-smash-bros-playing-ai-has-taught-itself-how-to-stomp-professional-players), [MIT CSAIL](https://www.csail.mit.edu/news/ai-beats-pros-super-smash-bros).

**Caveats:**
- About 33 ms reaction time, against roughly 200 ms for a human.
- Falcon dittos on Battlefield only.
- An exploit: crouching at the ledge made it walk off.

**Follow-up:** "At Human Speed" ([arXiv 1810.07286](https://arxiv.org/abs/1810.07286)) puts a fixed delay queue on the actions. It calls 12 frames the lowest human-plausible delay. Plain deep RL collapses under delay; a learned predictive model, built on IMPALA, recovers.

### slippi-ai / Phillip II (vladfi1, 2020–)

[repo](https://github.com/vladfi1/slippi-ai). It is the "phillip" bot in this repo.

**Pipeline:**
1. Behaviour cloning on anonymised Slippi ranked replays (Fizzi gave the collections to vladfi1), plus pro replays.
2. Self-play RL with a KL penalty that keeps it close to the cloned policy.

**Policy:** a recurrent network with an autoregressive controller head: a 728-way "joint" (buttons, shoulder, C-stick), then an 85-way main stick. Faynt reuses this codec.

**Fairness is delay:**
- Releases act 18–24 frames late. Firoiu describes the two setups as 18-frame delay with 7-frame masking of tech actions, or 21-frame delay with 4-frame masking ([Gaming Intelligence](https://gamingintelligence.ai/news/phillip-replay-opt-outs)).
- The delay is also why it plays well over netplay at up to about 300 ms ping.

**Public access:**
- Type `!play` in the [x_pilot](https://twitch.tv/x_pilot) Twitch chat, then direct-connect to `PHAI#591`.
- Tiers range from basic to gm to auto.
- On 26 Oct 2026, agents trained on players who opted out of the dataset were removed.

**Against pros:**
- Moky lost a first-to-10 Fox ditto 3–10 ([video](https://www.youtube.com/watch?v=1kviVflqXc4)).
- Zain won a first-to-5, 5–3 ([video](https://www.youtube.com/watch?v=c8nRFAGvr2c)).
- Cody and aMSa ([video](https://www.youtube.com/watch?v=WGsN7lWBQPw)) and Aklo ([video](https://www.youtube.com/watch?v=OGOEqhMptq0)) also played it.
- In late Oct 2026 Cody streamed "Humanity vs AI: Top Players Crew Battle vs Phillip" ([VOD](https://www.twitch.tv/videos/2903721139)); **result [unverified]**.
- A Manifold market on "a human beats a plausibly superhuman agent in a best-of-5 in 2025" resolved **NO** ([market](https://manifold.markets/NBAP/will-a-human-player-defeat-the-ssbm)).

**Known exploits:**
- Reacting to lasers with Marth's wavedash f-smash beats the Fox agent (Cody).
- Some Samus agents can be stunlocked into missiles.
- Fox agents have no answer to Puff's Rollout.

### Project Nabla (Bryan Chen, 2022)

- Behaviour cloning on tournament replays with a GRU policy, then PPO fine-tuning.
- Known for very human-like play, and admits it edgeguards poorly.
- Write-ups: [part 1](https://bycn.github.io/2022/08/19/project-nabla.html), [part 2](https://bycn.github.io/2022/08/19/project-nabla-writeup.html).

### HAL (Eric Gu, 2025–2026)

[repo](https://github.com/ericyuegu/hal). It is the "hal" bot in this repo.

**Part 1, Feb 2025** ([blog](https://ericyuegu.com/behavior-cloning-melee/)):
- A 20M decoder-only transformer, trained to predict the next frame's controller from state plus the previous input.
- 3B frames of pro Fox; about $5 of compute (2× 3090, 5 h).
- Wins 95% against the level 9 CPU.
- Lessons: first overfit a synthetic multishine episode, and build closed-loop evaluation early.

**Part 2, Oct 2026** ([blog](https://ericyuegu.com/hillclimbing-melee/)):
- A 247M transformer with 256-frame context, trained on a 1.3M-game dataset (published on HF) in 16 h on one B200.
- **Steering:** conditioning on return (ask for the 90th–99th percentile) and on player identity, e.g. "Cody". That is our `return_target` and `identity` knobs.
- **Action chunks:** it replans every few frames, which hides inference latency and netplay delay.
- **Key finding:** "each additional frame of reaction delay hurts performance twice as much as each additional frame of open-loop action execution."
- **Results:** about 2200 Elo on the Slippi ladder (top ~1%) with 3 frames of observation delay. Win rates: 97.4% vs level 9 CPU, 94.8% vs Phillip with behaviour cloning only, 25% vs Phillip with RL.
- He writes: "I do not condone running bots on Slippi without permission."
- Part 3 (self-play RL) is planned.

### MIMIC (erickfm, 2025–2026)

[repo](https://github.com/erickfm/MIMIC), [HF](https://huggingface.co/erickfm/MIMIC)
- **Models:** about 20M transformers, one per character or rank tier (e.g. `fox-master`, about 77k master Fox games), with a 180-frame window. Bootstrapped from HAL's recipe, with a 7-class button head so it can wavedash.
- **RLVR:** PPO on skill metrics the engine can verify, such as L-cancel rate.
- **Strength:** pure behaviour-cloning `fox-master` wins 29% against hosted Phillip over netplay.
- **Data:** published [erickfm/melee-ranked-replays](https://huggingface.co/datasets/erickfm/melee-ranked-replays), about 850k ranked replays, 1.43 TB, with about 90% duplication across per-character buckets.

### Faynt (Frisson Labs, Oct 2026)

Paper [arXiv 2610.02144](https://arxiv.org/abs/2610.02144), [site](https://www.frisson-labs.com/faynt), [runtime](https://github.com/Na00s/Faynt-Tournament). Authors include Ali Janati and Nikita Kuzmin.

**Models:**
- 10M (5×384) and 75M (11×768) transformers; one checkpoint plays all 26 characters.
- Uses GQA, RoPE and the Muon optimiser, with the slippi-ai 728/85 controller codec.

**Training stages:**
1. **Base:** behaviour cloning on about 840k ranked replays.
2. **Expert:** a "winner curriculum" that ends on 90% Master-winning data, plus 75M→10M distillation.
3. **Arena:** PPO on Fox mirrors only, run on 96 Dolphins on one L4 GPU, with a KL penalty toward the supervised policy.

**Results:** 240/244 mirror games against 14 slippi-ai releases, and 68/68 against a private zero-delay slippi-ai checkpoint.

**Caveat:** Faynt runs with **zero delay** while the slippi-ai opponents keep 21–24 frames. The authors say they "have not isolated the effect".

### Reyn (Frisson Labs, 11 Nov 2026)

[site](https://www.frisson-labs.com/reyn), [repo](https://github.com/frisson-labs/Reyn), [HF](https://huggingface.co/frisson-labs/Reyn-26C)
- **Steering:** builds on Faynt's 10M policy. A small neural router maps an English phrase to one of about 200 learned command tokens, such as "be more aggressive" or "pull a turnip". **There is no LLM in the frame loop.**
- **Command following:** met its target in 81.8% of 1,672 tests. It does not measure fighting strength.
- **Also released:** Reyn-Pair (2v2, trained with MAPPO) and a "wombo combo" experiment.
- **Browser arena:** [frisson-labs.com/arena](https://www.frisson-labs.com/arena).

It is the closest published work to this repo's coach track: an LLM above a learned policy. Our coach is the LLM layer Reyn leaves out.

### TypeSafe Jev (Sep 2026)

- **What it is:** a "System One" model from TypeSafe AI, founded by ex-OpenAI researcher Diogo Almeida ([blog](https://typesafe.ai/blog/introducing-system-one-models-and-jev), [docs](https://docs.typesafe.ai/models)).
- **How it works:** you send `state` and typed questions (Choice, Score, …) to `POST /v1/systemone`. It returns calibrated probabilities in one pass, with no text generation.
- **Speed and price:** 70–500 ms, $42 per billion input tokens.
- **Where it fits:** too slow for frame-level control, but it suits choosing a tactic every 4–30 frames, which is what `jev_live` / `coach_jev` do here.
- **Melee demos:** community builds exist, and one person self-reports beating the level 9 CPU after 13 games. **No official TypeSafe Melee write-up was found [unverified].**
- **Related:** Google followed with "Gemini Decisions" in Nov 2026 ([codelab](https://codelabs.developers.google.com/codelabs/discriminative-models)).

### Other attempts worth knowing

- **Qwen plays Smash** ([post](https://hgali.sh/reflex), 2026): the closest LLM-in-the-loop prior work.
  - Qwen3-1.7B scores 19 tactic words from a one-line state, and a motor layer executes the chosen tactic.
  - A CUDA-graph rewrite took a decision from 260 ms to 30 ms.
  - He compared it honestly against six if-statements. His verdict: "It is not a good Melee player."
- **Academic and hobby projects:**
  - [Stanford CS224R 2025](https://cs224r.stanford.edu/spring_2025/projects/pdfs/cs224rfinalprojectreport.pdf): behaviour cloning plus IQL or PPO. It couldn't recover or beat the level 9 CPU.
  - [Leiden MSc thesis](https://theses.liacs.nl/pdf/2025-2026-HamelinkJJosef.pdf): fine-tunes HAL's architecture on Fox mirrors.
  - [ExPhil](https://github.com/blasphemetheus/exphil): Mamba, attention or LSTM backbones.
  - [BaiShiXi Fox bots](https://baishixi.blog/posts/melee-fox-bots/).
  - [boxxfish smash-RL blog](https://boxxfish.github.io/blog/smash-rl-1).
  - [Athena](https://github.com/Sciguymjm/athena): a 2016 keras-rl stub.
  - [Sharma & Friedman 2017](https://www.yash-sharma.com/files/learning-play-super%20(3).pdf).
- **[No Johns](https://github.com/ScavieFae/nojohns):** agents wagering on bot-vs-bot matches, using Phillip or SmashBot as fighters.
- **Adjacent LLM game benchmarks:**
  - [LLM Colosseum](https://github.com/OpenGenerativeAI/llm-colosseum): Street Fighter III from text state. GPT-3.5 beat GPT-4 there, because speed won.
  - [VideoGameBench](https://arxiv.org/abs/2505.18134): its "Lite" mode pauses the game while the model thinks, the same idea as our `paused` mode.
  - Claude and Gemini Plays Pokémon.
  - No public LLM-plays-Melee benchmark was found.

## 3. Fairness, the recurring debate

- **Reaction time.** Humans react in about 12–15 frames. Phillip v1 took about 2, SmashBot 0.
  - Fixes so far: fixed action queues (12 frames in Sharma, 18–24 in Phillip II); predictive models; masking early action-state labels such as tech direction; and behaviour cloning, which inherits human timing.
- **Lockstep vs real time.** In local or lockstep play Dolphin waits for the bot, so inference cost is invisible and "0 delay" is superhuman (HAL README, Faynt §F.3).
  - Over netplay a bot must fit in 16.7 ms per frame, or plan in chunks. Slippi rollback adds about 2 frames of buffer.
  - **Cross-bot results only compare fairly at equal delay.** Faynt's 240/244 is zero delay against 21–24 frames.
- **Precision.** Bots see exact coordinates and action IDs and have no stick noise. Firoiu concedes an "unrealistically precise execution" advantage.
- **Platform rules.** No bots on Slippi Ranked or Unranked: libmelee, slippi-ai, MIMIC and Faynt all say so, and accounts get banned. A bot opt-in is "planned". Use Direct Connect or local play, as [netplay.md](netplay.md) does.
  - Frisson's claim of reaching Platinum on ranked and Gu's 2200 Elo ladder test sit in tension with this rule.
- **Data consent.** Players can opt out of having their replays used for training. Phillip pulled opted-out agents in Oct 2026.

## 4. Tooling and data

### Slippi (Fizzi / Jas Laferriere)

- **Netplay:** rollback shipped June 2020; Ranked opened Dec 2022. The in-game parts are PowerPC ASM Gecko codes ([slippi-ssbm-asm](https://github.com/project-slippi/slippi-ssbm-asm)).
- **`.slp` format** ([SPEC.md](https://github.com/project-slippi/slippi-wiki/blob/master/SPEC.md)):
  - The file is UBJSON with two parts: `raw`, a big-endian event stream, and `metadata`.
  - Event 0x35 declares the size of every other event. Fields are only appended, so parsers stay forward-compatible.
  - Main events: Game Start 0x36, Pre-Frame 0x37 (inputs), Post-Frame 0x38 (state after the frame), Game End 0x39, Frame Start 0x3A (RNG), Item Update 0x3B, Frame Bookend 0x3C (`latestFinalizedFrame`).
  - Frames start at **−123**; frame 0 is when the timer starts. Under rollback a frame can be emitted several times, so trust only what is ≤ `latestFinalizedFrame`.
- **Spectator protocol** ([SPECTATOR_PROTOCOL.md](https://github.com/project-slippi/slippi-wiki/blob/master/SPECTATOR_PROTOCOL.md)):
  - ENet/UDP on port 51441, JSON messages: `connect_request` / `connect_reply`, `game_event` (base64 SLP), and `menu_event` (a snapshot of menu state).
  - libmelee reads exactly this stream, and `ConsoleTap` in this repo taps it.
- **Dolphin builds:**
  - Production is Ishiiruka-based (v3.6.x).
  - The mainline port is in beta: [project-slippi/dolphin](https://github.com/project-slippi/dolphin), beta.19.
  - **ExiAI** ([vladfi1/slippi-Ishiiruka](https://github.com/vladfi1/slippi-Ishiiruka/releases), `exi-ai-rebase` branch) is a headless build. Inputs go over EXI instead of pipes, with null graphics and a fast-forward Gecko code.

### libmelee

- **History:** altf4's [original repo](https://github.com/altf4/libmelee) is archived. vladfi1's [fork](https://github.com/vladfi1/libmelee) has been the PyPI `melee` package since 0.45.
- **The fork's changes:**
  - Raw `.slp` values, so live state matches replays parsed with peppi.
  - An ENet keepalive: without it the connection drops after about 60 s idle.
  - `use_exi_inputs` / `enable_ffw`.
  - Stick values corrected to what the game actually reads.
  - Mainline Dolphin support.
- **Quirks:**
  - A press and release within one frame is never seen; use `release_all()`.
  - `action_frame` starts at 1.
  - Zelda and Sheik share one character ID.

### Replay parsers, viewers and data

- **Parsers:**
  - [slippi-js](https://github.com/project-slippi/slippi-js): the official TypeScript parser, with built-in stats (conversions, openings per kill, L-cancel %, inputs per minute).
  - [peppi](https://github.com/hohav/peppi) (Rust) and [peppi-py](https://github.com/hohav/peppi-py): Arrow struct-of-arrays, e.g. `game.frames.ports[0].leader.post.position.x`, which goes straight to numpy. This is the standard way ML projects load replays. py-slippi is superseded.
  - [slp-realtime](https://github.com/vinceau/slp-realtime) and [Project Clippi](https://github.com/vinceau/project-clippi): live event hooks such as combo detected or stock lost.
- **Viewers:**
  - [Slippi Lab](https://github.com/frankborden/slippilab) (frankborden): a SolidJS viewer that draws characters from per-frame data, not from the game's 3D models. We patch it; see `patches/slippilab.patch`.
- **Datasets:**
  - Fizzi's anonymised ranked collections: distributed through the slippi-ai Discord.
  - [erickfm/melee-ranked-replays](https://huggingface.co/datasets/erickfm/melee-ranked-replays): needs deduplication before use.
  - HAL's 1.3M-game dataset on HF.
  - `erickfm/slippi-public-dataset-v3.7`: about 95k older tournament replays.

### Game internals and frame data

- **[doldecomp/melee](https://github.com/doldecomp/melee):** targets NTSC 1.02. [decomp.dev](https://decomp.dev/doldecomp/melee) reports it 100% decompiled and linked; current work is naming. It is the authoritative source for player structs, action-state logic and physics.
- **Action states:** IDs 0x000–0x154 are shared by all characters; higher IDs are character-specific. libmelee's `enums.Action` is the practical lookup table; cross-check it against the [ssbm-data](https://docs.rs/ssbm-data/) crate.
- **Frame data:**
  - [IKneeData](https://ikneedata.com): hitboxes and a knockback calculator.
  - [Melee Framedata Repository](https://meleeframedata.notion.site/Frying-Pan-b2d7f7a9a78a459aaa2eb2576a789cc7).
  - [SmashWiki](https://www.ssbwiki.com/).
  - [SRK SSBM Technical Data](https://srk.shib.live/w/SSBM/Technical_Data).
  - The Smashboards [hitbox and frame data thread](https://smashboards.com/threads/complete-hitbox-frame-data-for-every-character-now-with-ko-percents.383550/).
  - [The Melee Library](https://www.meleelibrary.com) (guides).
  - These are inputs the bot-writer and LLM prompts could cite.
- **Mods:**
  - [UnclePunch Training Mode](https://github.com/UnclePunch/Training-Mode), continued as [TrainingMode Community Edition](https://github.com/AlexanderHarrison/TrainingMode-CommunityEdition): scripted drills for ledge, tech chase and SDI.
  - [20XXTE](https://20xx.me).
  - [m-ex](https://github.com/akaneia/m-ex).
  - [Melee Code Manager](https://github.com/DRGN-DRC/Melee-Code-Manager).
  - [MeleeLight](https://github.com/schmooblidon/meleelight): an HTML5 clone with approximate physics. Fine for prototyping, too inexact to train on.

## 5. Where it is discussed

| Venue | What |
| --- | --- |
| [Phillip / slippi-ai Discord](https://discord.gg/hfVTXGu) | The main Melee AI server, run by vladfi1. Replay datasets are distributed here |
| [Doubles-Phillip Discord](https://discord.gg/k7ZuNmh7ed) (Enzyme) | Listed in the slippi-ai README |
| [Frisson Labs Discord](https://discord.gg/vV3DaXCwFS) | Faynt and Reyn |
| Slippi Discord | Slippi development; the source of the ranked collections |
| [twitch.tv/x_pilot](https://twitch.tv/x_pilot) | Phillip on stream; anyone can play it |
| [Phillip YouTube](https://www.youtube.com/channel/UCzpDWSOtWpDaNPC91dqmPQg) | Sets against pros |
| [Manifold markets by NBAP](https://manifold.markets/NBAP/will-a-human-player-defeat-the-ssbm) | The community's running humans-vs-bots scoreboard |
| [r/SSBM](https://www.reddit.com/r/SSBM) | Threads when pros beat or lose to Phillip |
| [Smashboards](https://smashboards.com) | Older modding and frame-data threads (20XX, Training Mode, `.dat` formats) |
| Blogs | [Eric Gu](https://ericyuegu.com/), [Frisson Labs](https://www.frisson-labs.com/), [bycn (Nabla)](https://bycn.github.io/) |

No tournament has run an official AI exhibition since Genesis 4 in 2017 **[unverified absence]**. Pro-vs-bot sets now happen on stream: x_pilot, and Cody's own channel.

## 6. People

| Person | Handle | Known for |
| --- | --- | --- |
| Vlad Firoiu | vladfi1, x_pilot | Phillip v1 and v2 (slippi-ai), the libmelee fork, ExiAI Dolphin. The central figure |
| Dan Petro | altf4 | SmashBot, original libmelee (Bishop Fox) |
| Jas Laferriere | Fizzi | Project Slippi; gave the ranked replays to the AI efforts |
| Eric Gu | ericyuegu | HAL and its blog series on scaling behaviour cloning |
| Bryan Chen | bycn | Project Nabla |
| Erick FM | erickfm | MIMIC and the HF ranked-replay dataset |
| Ali Janati, Nikita Kuzmin (with Tongke Xue; CEO Charles Niu, CTO Rohit Swamy) | Na00s, frisson-labs | Faynt and Reyn |
| Diogo Almeida | TypeSafe AI | Jev and System One models |
| Hareesh Gali | hgali.sh | Qwen plays Smash |
| hohav (now maintained by NickCondron) | hohav | peppi, py-slippi |
| Frank Borden | frankborden | Slippi Lab |
| vinceau | vinceau | slp-realtime, Project Clippi |
| UnclePunch | UnclePunch | Training Mode, Slippi contributions |
| Achilles1515 | Achilles | 20XX Training Pack, including the CPU AI overhaul |
| Enzyme | | Doubles Phillip; an Enzyme-built decomp-based simulator is credited in slippi-ai **[unverified]** |
| Pros vs bots | Cody Schwab, Zain, Moky, aMSa, Aklo, Gravy, S2J | Recorded sets against Phillip |

## 7. What this means for this repo

- **Prior work:** no public LLM-plays-Melee benchmark exists. The closest are Reyn (a language router over a policy, with no LLM), Qwen plays Smash (a small LLM choosing tactics) and Jev community builds. Our coach-over-learned-bot and LLM-writes-bots tracks look new.
- **Benchmark design:**
  - Report results as Fox ditto on FD or Battlefield, and **state the delay and the mode** (lockstep, paused or real time). Otherwise results don't compare with Phillip, HAL or Faynt.
  - Level 9 is only a floor. The ladder above it, roughly by published head-to-heads: MIMIC < HAL < Phillip RL ≈ Faynt (at unequal delay).
- **Play rules:** never put a bot on Slippi online matchmaking. Direct Connect only.
- **Exploits to test:** the known Phillip exploits (Puff Rollout, Marth reacting to lasers) are cheap probes for whether an LLM coach can find and exploit a weakness.
- **Cheap upgrades:**
  - peppi-py over the HF ranked replays for few-shot examples per situation.
  - doldecomp, IKneeData and frame-data tables to make LLM state summaries accurate.
  - TM-CE drills as unit scenarios.

## Open questions (not resolved by this research)

- The result of Cody's Oct 2026 crew battle against Phillip.
- Whether Phillip has played Hungrybox or Mang0 on record.
- Whether TypeSafe has published any Melee material of its own.
- Melee's status at Evo 2025–2026.
