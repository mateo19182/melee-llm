# Melee AI research notes

Background for this repo: the game, the Melee bots and how each works, the tooling, the community and the people. Compiled from web research on 2026-11-14, extended on 2026-11-15 with the game's and the scene's history. Each claim has a link; **[unverified]** means no primary source was found. How we wrap each bot is in [bots.md](bots.md).

## 1. The game, briefly

- **Super Smash Bros. Melee** came out on GameCube in 2001. Its competitive scene is grassroots and has never had Nintendo's support.
  - Documentaries: *The Smash Brothers* (2013, by Samox; [wiki](https://en.wikipedia.org/wiki/The_Smash_Brothers)) and *Metagame* (2020), which covers the "Five Gods": Mang0, Armada, Hungrybox, Mew2King and PPMD ([wiki](https://www.ssbwiki.com/Metagame_(documentary))).
- **Current top players** ([SSBMRank 2025](https://liquipedia.net/smash/SSBMRank)): Zain #1, Cody Schwab #2, Hungrybox #3, Joshman, Axe and Jmook; aMSa is #23.
  - Cody won GENESIS X3 in Feb 2026 ([Liquipedia](https://liquipedia.net/smash/GENESIS/X3/Melee)).
  - The Big House has been on hiatus since July 2024 ([wiki](https://en.wikipedia.org/wiki/The_Big_House_(tournament))).
  - Melee was last at Evo in 2018 and was absent in 2025 and 2026 ([Polygon](https://www.polygon.com/2019/2/26/18242497/evo-2019-games-lineup-smash-bros-melee-ultimate/), [Evo 2026](https://evo.gg/events/evo2026/)).
- **Nintendo:**
  - Cancelled Smash World Tour in late 2022 ([SmashWiki](https://www.ssbwiki.com/Cancellation_of_Smash_World_Tour_2022)).
  - Published Community Tournament Guidelines in Oct 2023: caps of 200 in-person or 300 online entrants and about $5k in prizes, and no modified game versions ([SmashWiki](https://www.ssbwiki.com/Community_Tournament_Guidelines)).
- **Why it survives:** Slippi's rollback netplay (June 2020) kept the game alive through COVID ([SmashWiki](https://ssbwiki.com/Project_Slippi)). Its ranked replays are now the training data for every modern bot.

### How the game and the scene got here

- **Made in a hurry.** HAL Laboratory built Melee in about 13 months for the GameCube launch. Sakurai worked "without a single Sunday or holiday off", sometimes 40 hours straight, and was hospitalised once; Satoru Iwata came in to debug and review code, his last job as a programmer ([Engadget](https://www.engadget.com/2010-12-08-sakurai-describes-grueling-development-of-smash-bros-melee.html), [Source Gaming](https://sourcegaming.info/2015/08/10/sakuraimelee/)). Sakurai later called it "the sharpest game in the series".
- **Release and sales.** Japan 21 Nov 2001, North America 3 Dec 2001, Europe 24 May 2002. The GameCube's best-selling game, over 7 million copies by 2008, with an estimated 70% of GameCube owners owning it ([Wikipedia](https://en.wikipedia.org/wiki/Super_Smash_Bros._Melee)).
- **Wavedashing was found within weeks.** The first recorded mention is a Smashboards thread from 24 Jan 2002 ("mad dashing"), and its author said he found it in December 2001. Early pros such as Azen and Recipherus showed what it was for, and within a year nearly every top player used it. Sakurai said he had noticed it during development and left it in, thinking it wouldn't matter; Brawl (2008) removed it, along with L-cancelling ([SmashWiki](https://www.ssbwiki.com/Wavedash), [GameFAQs timeline](https://gamefaqs.gamespot.com/boards/516492-super-smash-bros-melee/42199054)). L-cancelling and short hops were already known from Smash 64; "dash dancing" was named by May 2002, DI studied from Aug 2002, the moonwalk found in 2006.
- **Grassroots scene.** Matt Deezie's Tournament Go series (NorCal, from Apr 2002) set the first common ruleset; MLG ran Melee from 2004 to 2008 ([SmashWiki](https://www.ssbwiki.com/Super_Smash_Bros._Melee_in_competitive_play)). After Brawl came out in 2008 the scene shrank, until the "Five Gods" era (Armada, Mango, Mew2King, Hungrybox, PPMD) ([Metagame](https://www.metagamedoc.com/smash-history)).
- **Wombo Combo (6 Dec 2008).** Doubles losers' semis at SCSA West Coast Circuit: SilentSpectre (Falcon) and Tang (Fox) take Zhu from 0% to 77% and KO him in seven seconds, ending in shine, up smash, knee. Commentary by HomeMadeWaffles, Phil and Mango ("Happy feet! WOMBO COMBO! That ain't Falco! Where you at?!"). The name comes from a Round Table Pizza menu item, and the combo was rehearsed ahead of time for another opponent. The [original upload](https://www.youtube.com/watch?v=pD_imYhNoQ4) has over 21M views ([SmashWiki](https://www.ssbwiki.com/Wombo_Combo)).
- **2013, the comeback.** Melee won Evo's charity drive for an eighth game with $94,557 for breast cancer research, beating Skullgirls in the final hours. Three days before the event Nintendo blocked the stream, then reversed within hours after the backlash. Evo 2013 drew 696 Melee entrants, more than twice the previous record ([Melee It On Me](https://meleeitonme.wordpress.com/2013/12/31/melee-in-2013-year-in-review/), [Polygon](https://www.polygon.com/2013/7/9/4508826/super-smash-bros-melee-pulled-from-evo-livestream-nintendo/)). *The Smash Brothers* documentary premiered at The Big House 3 in Oct 2013, crowdfunded with $8,910 ([Wikipedia](https://en.wikipedia.org/wiki/The_Smash_Brothers)).
- **2020, #FreeMelee.** Nintendo sent The Big House Online a cease and desist in Nov 2020 because it relied on Slippi, cancelling it ([Esportz Network](https://www.esportznetwork.com/nintendos-controversial-relationship-with-smash-and-freemelee/)).
- **How many inputs?** Rarely measured. A hand count of Isai (Falcon) at MOAST3 in 2005 found 446 actions in 2:33, about 175 APM or 3 per second ([GameFAQs](https://gamefaqs.gamespot.com/boards/516492-super-smash-bros-melee/49551497?page=2)); later write-ups claim 5–8 inputs per second for technical players without a measurement ([Medium](https://medium.com/@jchung.bsd/a-thorough-investigation-of-the-physical-ramifications-of-ssbm-feat-hax-sfat-and-fatgoku-53daa4144fcc)) **[unverified]**. Bursts go much higher, and there is a lot of dead time between them. slippi-js now computes inputs per minute from any replay, so this could be measured properly.

### Mechanics a bot author needs

The game runs at 60 fps, so one frame is 16.7 ms. Every mechanic below has a SmashWiki page at `https://www.ssbwiki.com/<Term>`.

| Concept | Why it matters for bots |
| --- | --- |
| Wavedash (jump, then air-dodge diagonally into the ground) | Needs a trigger in the action space. HAL's original 5-class button head could not do it; MIMIC moved to 7 classes for this reason ([MIMIC card](https://huggingface.co/erickfm/MIMIC)) |
| L-cancel, SHFFL | Pressing a trigger in a narrow window halves landing lag. MIMIC's RLVR raised its L-cancel rate from 94% to 99% |
| Multishine | Frame-perfect Fox/Falco loop. libmelee ships it as the `shine` demo |
| DI / SDI / ASDI, hitlag | Survival inputs given during hitlag. Behaviour cloning learns them from humans |
| Tech chase | Reading a knockdown option and punishing it. SmashBot needed exact speeds to do it ([libmelee](https://github.com/altf4/libmelee)) |
| Ledge, edgeguarding, recovery | A classic bot weakness: Nabla admits it, and the CPU never fights off edgeguards |
| Shield, out-of-shield options, powershield | The level 9 CPU almost never shields attacks |
| Top tier: Fox, Falco, Marth, Sheik, Puff, Peach, Falcon | **Fox ditto on Final Destination or Battlefield is the default benchmark matchup** |

## 2. History of the bots

| Year | Bot | Author | Technique |
| --- | --- | --- | --- |
| 2001 | In-game CPU | HAL Laboratory | Scripted. Level sets reaction and commitment, not strategy |
| 2015–21 | SmashBot | Dan "altf4" Petro | Rule-based behaviour tree |
| 2016 | 20XX "AI Overhaul" | Achilles1515 | Patched CPU scripts |
| 2017 | Phillip v1 | Vlad Firoiu, MIT | Pure deep RL from RAM state |
| 2017 | DRQN with 12-frame delay | Sharma & Friedman, Cooper Union | Recurrent DQN |
| 2018 | "At Human Speed" | Firoiu, Ju, Tenenbaum | RL under action delay, plus a predictive model |
| 2020– | slippi-ai / Phillip II | vladfi1 ("x_pilot") | Behaviour cloning on Slippi ranked replays, then self-play RL |
| 2024 | slippi-ai vs top players | Aklo, Hungrybox, Zain, Moky, Cody, aMSa | First public sets against the delayed agents |
| 2022 | Project Nabla | Bryan Chen | Behaviour cloning (GRU), then PPO |
| 2025–26 | HAL | Eric Gu | Behaviour-cloning transformer, 20M then 247M parameters |
| 2025–26 | MIMIC | erickfm | Behaviour cloning, one transformer per character, plus RLVR |
| Sep 2026 | Jev ("System One") | TypeSafe AI | General decision API, not Melee-specific |
| 2026 | ExPhil | blasphemetheus (Bradley) | Elixir: behaviour cloning, scripted drills, then PPO in melee-sim-light; on stomped.dev |
| Oct 2026 | Faynt | Frisson Labs | Behaviour cloning, winner curriculum, then PPO, all 26 characters |
| Oct 2026 | Humans vs Phillip crew battles | Zain, Cody and other top players | Organised top-player exhibitions on stream |
| Nov 2026 | Reyn | Frisson Labs | Faynt-based policy steered by language commands |

### How bots read state and press buttons

All serious bots read structured state, not pixels: positions, speeds, action state and its frame, percent, stocks.

- **2015–2020:** Dolphin's MemoryWatcher streamed hand-mapped RAM addresses, and inputs went back through a named pipe. altf4 called this "a really kludgey way of doing it" ([SmashBot #115](https://github.com/altf4/SmashBot/issues/115)).
- **Since May 2020:** libmelee reads the **Slippi spectator stream** (ENet on port 51441, base64 SLP events). It works on Dolphin, on a hacked Wii and on `.slp` replays, which is why replays became the training corpus.

### In-game CPU (level 1–9)

**Level 9 is a sanity check, not a strength measure.** Every learned bot 4-stocks it, which our closed-loop results in bots.md confirm.

Level 9 jabs and grabs frame-perfectly, but it:
- dashes only to dash-attack or dash-grab;
- almost never shields physical attacks, though it powershields projectiles;
- has fixed recovery paths and barely edgeguards;
- can be beaten by standing still and spamming one move.

Phillip v1's Q-learner found a trick that made the CPU kill itself. Sources: [SmashWiki AI flaws](https://www.ssbwiki.com/List_of_flaws_in_artificial_intelligence_(SSBM)), [arXiv 1702.06230](https://arxiv.org/abs/1702.06230).

### SmashBot (altf4, 2015–2021)

Still a good design reference for a rule-based or LLM-written bot, which is what our bot-writer track does.

- **Design:** hand-written, with a Goals → Strategies → Tactics → Chains hierarchy. A Chain is an input sequence such as a wavedash or a jump-cancelled upsmash. Exact frame data tells it when the opponent is actionable.
- **First scope:** Fox vs Marth only, on FD or Stadium.
- **Timeline** ([repo](https://github.com/altf4/SmashBot) tags and commits):
  - 1 Nov 2015: repo created (as `cpu-level-11`); altf4 had worked on it in secret for about a year before DEF CON, on a dare from a friend ([Bishop Fox](https://bishopfox.com/blog/reversing-video-games-to-create-smashbot-ai)).
  - Jan 2016: announced on Smashboards as ["Level 11 CPU"](https://smashboards.com/threads/level-11-cpu-the-ai-that-beats-you-at-melee.428232/).
  - 2016: tournament builds for Genesis 3, Battlefield VII and SPC VII, then v1.0 in Sep 2016.
  - Aug 2016: presented at DEF CON 24 ([talk](https://www.youtube.com/watch?v=_0Z_oN_CZyA), [Bishop Fox write-up](https://bishopfox.com/blog/reversing-video-games-to-create-smashbot-ai)).
  - 31 Dec 2016: libmelee split out as "all the SmashBot stuff that is plumbing".
  - 2017: played pros at JV5 ([compilation](https://www.youtube.com/watch?v=6CfPnK76B9A)).
  - Oct 2020: ported to Slippi.
  - Through 2021: matchup work against Sheik, Pikachu and Yoshi. It still plays only Fox; the last commit was in 2024.
- **libmelee handover:** altf4 archived libmelee in 2026, and its README now says it "is being managed by xpilot".
- **Fairness:** the FAQ says it "doesn't cheat": it presses a virtual controller, but with zero reaction time. It also says never to run it online.

### Phillip v1 (Firoiu, Whitney, Tenenbaum, 2016–2019)

Paper: "Beating the World's Best at Super Smash Bros. Melee with Deep Reinforcement Learning" ([arXiv 1702.06230](https://arxiv.org/abs/1702.06230), [repo, archived](https://github.com/vladfi1/phillip), [HN thread](https://news.ycombinator.com/item?id=13710253)).

**Setup:**
- Input was RAM features. There were no projectiles, so it played Captain Falcon.
- It acts at 30 Hz with 54 discrete actions: 9 stick positions × 5 single buttons, or none.
- Reward is ±1 per KO plus a small weight on damage.
- One network per character: training one network on several characters failed (it used only the moves good for all of them), so the paper trained six (Fox, Falco, Sheik, Marth, Peach, Falcon) against each other. Starting a new character from an already-trained one was faster; Fox and Falco transferred best.
- Training: actor-critic with an entropy bonus and TRPO-style steps bounded by KL divergence (Q-learning was also tried, and against the CPU it learned to trick it into suiciding), two 128-unit layers, 50+ parallel Dolphins on the MGHPCC cluster with K20 and TITAN X GPUs ([NVIDIA](https://developer.nvidia.com/blog/self-taught-ai-bot-beat-professional-players-at-super-smash-bros/)).
- New Scientist reports the team built on SmashBot's groundwork ([article](https://www.newscientist.com/article/2122452-ai-beats-professional-players-at-super-smash-bros-video-game/)).

**How it got strong:**
- Firoiu "couldn't train Phillip to be as strong as the in-game bot" until he switched to self-play: "I just sort of forgot about it for a week… I tried playing it and I couldn't beat it."
- He had entered Genesis 4 (San Jose, Jan 2017) as a player. Pros lined up to play the bot on "a clunky, four-year-old HP laptop" away from the main stage.
- Gravy: "The AI is definitely godlike." ([Quartz](https://qz.com/917221/a-super-smash-bros-playing-ai-has-taught-itself-how-to-stomp-professional-players))

**Results** (paper, Table 1): it beat the level 9 CPU within a day. Against ten ranked pros (ranks 16–70) across two major tournaments, every pro lost more stocks than they took.

| Pro | Phillip kills–deaths |
| --- | --- |
| S2J | 4–2 |
| Zhu | 4–1 |
| Gravy | 8–5 |
| Crush | 3–2 |
| Mafia | 4–3 |
| Slox | 6–4 |
| Redd | 12–8 |
| Darkrain | 12–5 |
| Smuckers | 8–5 |
| Kage | 4–1 |

- **Corrected scores:** the paper's first version had Mafia 2–1 and Slox 8–4; v2 corrected them to 4–3 and 6–4.
- **The two events:** both happened before 21 Feb 2017, because all ten pros are already in the paper's first version. One is Genesis 4: the ["Phillip vs. Slox, Mafia"](https://www.youtube.com/watch?v=dXJUlqBsZtE) video (Feb 2017) says "From genesis 4". The other is named nowhere we checked: the paper, the press, the repo history and vladfi1's uploads.
- **Coverage:** [MIT CSAIL](https://www.csail.mit.edu/news/ai-beats-pros-super-smash-bros), [TechCrunch](https://techcrunch.com/2017/02/24/super-smash-borg-melee-ai-takes-on-top-players-of-the-classic-nintendo-fighting-game).

**Caveats:**
- About 33 ms reaction time, against roughly 200 ms for a human.
- Falcon dittos on Battlefield only.
- An exploit: "If the opponent crouches in the corner… it freaks out and eventually suicides."

**Playing it before Slippi** (from the repo's commit log):
- The repo dates from Apr 2016. The [first stream clips](https://www.youtube.com/watch?v=vWjr3338AHQ) date from Jul 2016, with the bot acting every 3 frames.
- From mid-2016 it supported ordinary Dolphin netplay.
- Feb 2017 added a Twitch chat bot that let viewers of [twitch.tv/x_pilot](https://twitch.tv/x_pilot) queue up against it, and a SmashLadder client (Anther's Ladder) that also checked whether the opponent could run Faster Melee.

**Follow-up, "At Human Speed"** ([arXiv 1810.07286](https://arxiv.org/abs/1810.07286), 2018):
- Puts a fixed delay queue on the actions, and calls 12 frames the lowest human-plausible delay.
- Plain deep RL collapses under delay; a learned predictive model, built on IMPALA, recovers.
- Delayed agents followed, e.g. ["Phillip (12 delay, 3 days) vs Professor Pro"](https://www.youtube.com/watch?v=nEpyB0FHoA4) (May 2018). The v1 README calls `delay18/FalcoBF` "the best human-like agent".

**Why imitation learning replaced pure RL:**
- Pure RL from scratch produced an alien style that broke down under human-like delay.
- Slippi replays offered millions of human games. Starting from behaviour cloning "makes it play a lot more like a human" (slippi-ai README).
- Firoiu credits Slippi replays with rekindling his interest "even prior to rollback netcode".

### slippi-ai / Phillip II (vladfi1, 2020–)

[repo](https://github.com/vladfi1/slippi-ai). It is the "phillip" bot in this repo.

**Pipeline:**
1. Behaviour cloning on anonymised Slippi ranked replays, plus pro replays.
2. Self-play RL with a KL penalty that keeps it close to the cloned policy.

**Policy:** a recurrent network with an autoregressive controller head: a 728-way "joint" (buttons, shoulder, C-stick), then an 85-way main stick. Faynt reuses this codec.

**Credits in the README:**
- Fizzi wrote the fast-forward Gecko code and supplied the ranked collections.
- Enzyme built "a decomp-based simulator that runs melee even faster than dolphin", and runs Doubles Phillip.
- "my dad" provided the training hardware.

**Milestones** (from the commit log):

| Date | Milestone |
| --- | --- |
| Nov 2020 | Repo created. The first learner is an MLP predicting the next controller, trained on altf4's public dataset, Fox dittos first |
| Jan 2023 | First RL fine-tuning |
| Feb 2024 | Training with delayed actions (the d18 agents) |
| May 2024 | Self-play RL and a new Twitch bot |
| Nov 2024 | `fox_d18_ditto_v3` |
| Aug 2025 | "Medium" agents added for weaker players |
| Jan 2026 | Port to JAX |
| Sep 2026 | Bronze to gm tiers made weaker |
| Oct 2026 | ONNX export and a Windows GUI launcher (v0.3.4 by 31 Oct) |

**Fairness is delay:**
- Releases act 18–24 frames late. Firoiu describes two setups: 18-frame delay with 7-frame masking of tech actions, or 21-frame delay with 4-frame masking ([Gaming Intelligence](https://gamingintelligence.ai/news/phillip-replay-opt-outs)).
- The delay is also why it plays well over netplay at up to about 300 ms ping.
- A [clip](https://www.youtube.com/watch?v=bXGvyRvLmE0) shows Ginger catching it reacting on exactly frame 18.

**Public access:**
- Type `!play` in the [x_pilot](https://twitch.tv/x_pilot) Twitch chat, then direct-connect to `PHAI#591`. Tiers go basic → medium → gm → auto.
- A second channel, x_pilot_bot, streams Phillip vs Phillip ([about](https://www.twitch.tv/x_pilot/about)).
- Slippi marked "Work with xpilot to detect Phillip bots" as completed. The Slippi team also helped with replay extraction, faster training and lag-free play ([nolt #699](https://project-slippi.nolt.io/699)).

**Against top players:**

| Date | Set | Result |
| --- | --- | --- |
| Jun 2024 | [Aklo](https://www.youtube.com/watch?v=OGOEqhMptq0), [Hungrybox](https://www.youtube.com/watch?v=8B0EuluDnww) | First reactions from top players |
| Oct 2024 | [Wizzrobe](https://www.youtube.com/watch?v=g4DMF1ZFeB8) | Probes habits and weak spots |
| Nov 2024 | [Zain, first to 5](https://www.youtube.com/watch?v=c8nRFAGvr2c) | Zain wins 5–3 |
| Nov 2024 | [Cody and aMSa](https://www.youtube.com/watch?v=WGsN7lWBQPw) | |
| Nov 2024 | [Moky, first to 10 Fox ditto](https://www.youtube.com/watch?v=1kviVflqXc4) | Phillip wins 10–3 |
| Dec 2024 | [Hungrybox, first to 10](https://www.youtube.com/watch?v=Tpo2nq_eOO4), plus [Falcon/Fox vs Puff](https://www.youtube.com/watch?v=OMRP-jZcA4o) | A ditto-trained Falcon fails against Puff: a lesson in matchup generalisation |
| Dec 2024 | [Jmook (Sheik, Fox, Falco, Marth)](https://www.youtube.com/watch?v=HAz4GdG9dFU) | |
| Dec 2024 | Hungrybox, ["AI – The end of Smash Bros."](https://www.youtube.com/watch?v=qRhCvcAXfvY) | A top player's take on what Phillip means |
| 2025 | Salt, [n0ne](https://www.youtube.com/watch?v=-5Y3rNNdufQ), Wizzrobe | Phillip YouTube channel |
| 2026 | 404cray, Fiction, M2K, Goodie, Ginger ("2007 M2K" agent), [Cody vs v6](https://www.youtube.com/watch?v=BBK7qnnOfSs), [Zain vs four agents](https://www.youtube.com/watch?v=HPY94jqrZng), [Wizzrobe vs fox v6, puff v6, super-gm-dk](https://www.youtube.com/watch?v=JY6gRwI5zB0) | Newer agent generations |
| 1 Oct 2026 | [Zain's "Humans vs Robots" crew battle](https://www.youtube.com/watch?v=Szm1y1JrNpQ): Hungrybox, Cody, Mew2King, Wizzrobe, Magi, Moky | **Humans win.** Mew2King anchored a comeback ([his breakdown](https://www.youtube.com/watch?v=9b_2hzdTKNw)) |
| 17 Oct 2026 | [Cody's "Humanity vs AI" rematch](https://www.twitch.tv/videos/2903721139), with new agents | **Humans win again** (see below) |

**The 17 Oct 2026 rematch** (from our transcript of the last 40 minutes of Cody's VOD):
- The humans were down 8 stocks to 11 with Cody and Mew2King left, against Phillip's Falcon, Marth and Sheik.
- Mew2King anchored and won on Dreamland, using Kirby at the end. They apologised for "cheesing" with it.
- They noted vladfi1 had brought new agents for the event, and that Phillip "learned how to fight Kirby while we were doing the crew battle".
- In their words: "The humans did win, yes."

**Scoreboards** (Manifold):
- "[A human beats a plausibly superhuman agent in a best-of-5 in 2025](https://manifold.markets/NBAP/will-a-human-player-defeat-the-ssbm)" resolved **NO**. It lists the qualifying agents and exploit rules, and Firoiu comments there.
- "[Melee AI scandal in a tournament before 2027](https://manifold.markets/NBAP/will-super-smash-bros-melee-have-an)": about 11%.
- "[Hobbyist agent beats Phillip in a Bo5 before 2028](https://manifold.markets/NBAP/before-2028-will-i-be-able-to-train-EQOLpsplq8)": about 45%.

**Data consent (Oct 2026):**
- Opt-outs are enforced when the dataset is loaded. By default an excluded player's own perspective is dropped, but they are kept as an opponent.
- Well-known pros are excluded until they give permission. A 2024 commit excludes Mango's replays.
- Opt-outs had been applied inconsistently to agents that were already trained. After a press query in early Oct 2026, Firoiu removed the affected agents: some Falcon and Puff agents and the -v2 multi-character ranked agents ([Gaming Intelligence](https://gamingintelligence.ai/news/phillip-replay-opt-outs)).
- Pros use Phillip for practice but "do not regard it as a substitute".

**Known exploits:**
- Reacting to lasers with Marth's wavedash f-smash beats the Fox agent (Cody).
- Some Samus agents can be stunlocked into missiles.
- Fox agents have no answer to Puff's Rollout.
- **Kirby:** a Kirby player 4-stocked an agent in early 2025. The [Manifold market](https://manifold.markets/NBAP/will-a-human-player-defeat-the-ssbm) counted it as an exploit, since no agent had been trained against Kirby. Kirby also closed the 17 Oct 2026 rematch.
- **A Dec 2024 human win** posted on r/SSBM came before the 2025 window, so it didn't count for that market.

### Project Nabla (Bryan Chen, Aug 2022)

The original site is gone; these are Wayback copies: [overview](https://web.archive.org/web/20241121073045/https://bycn.github.io/2022/08/19/project-nabla.html), [technical write-up](https://web.archive.org/web/20240814082645/https://bycn.github.io/2022/08/19/project-nabla-writeup.html).

- **Data:** about 100k tournament `.slp` files from altf4's Public SLP Database, plus vladfi1's filtered Fox set.
- **Model:** a 256-unit GRU with an autoregressive head (2 buttons, sticks discretised into 17 parts), running at **2 frames of delay**.
- **Training:** behaviour cloning on an RTX 3070, then PPO with a KL penalty toward the cloned policy, Sebulba-style, on a TPU v3-8 from Google's TRC. The Falco agent went from under 30% to over 80% stock wins against the level 9 CPU.
- **Reception:** hosted on Twitch (@rakkob) for "thousands of plays". iBDW (Cody) and KJH reacted on video. Some testers thought it was a human. Weaknesses were edgeguarding and spamming smash attacks.
- The code was never released.

### HAL (Eric Gu, 2025–2026)

[repo](https://github.com/ericyuegu/hal). It is the "hal" bot in this repo.

**Part 1, Feb 2025** ([blog](https://ericyuegu.com/behavior-cloning-melee/)):
- A 20M decoder-only transformer, trained to predict the next frame's controller from state plus the previous input.
- 3B frames of pro Fox; about $5 of compute (2× 3090, 5 h).
- Wins 95% against the level 9 CPU.
- Lessons: first overfit a synthetic multishine episode, and build closed-loop evaluation early.

**Part 2, Oct 2026** ([blog](https://ericyuegu.com/hillclimbing-melee/)):
- A 247M transformer with 256-frame context, trained in 16 h on one B200 ([weights](https://huggingface.co/ericyuegu/hal-base-250m-rc)).
- Data: [about 1.3M games, 13.5B frames](https://huggingface.co/datasets/ericyuegu/hal-mds-dataset): 821k anonymised ranked plus 474k from 38 pros.
- **Steering:** conditioning on return (ask for the 90th–99th percentile) and on player identity, e.g. "Cody". These are our `return_target` and `identity` knobs.
- **Action chunks:** it replans every few frames, which hides inference latency and netplay delay.
- **Key finding:** "each additional frame of reaction delay hurts performance twice as much as each additional frame of open-loop action execution."
- **Results:** about 2200 Elo on the Slippi ladder (top ~1%) with 3 frames of observation delay. Win rates: 97.4% vs level 9 CPU, 94.8% vs Phillip with behaviour cloning only, 25% vs Phillip with RL.
- He writes: "I do not condone running bots on Slippi without permission."
- **Public play:** [20xx.xyz](https://20xx.xyz/) queues you for a Slippi direct-connect set against a HAL policy, streamed on [twitch.tv/hal_20xx](https://www.twitch.tv/hal_20xx).
- Part 3 (self-play RL) is planned. Compute was sponsored by Modal. Gu now works on VLAs at 1X, and is a co-author of Frisson's Sep 2026 post "Decoder-Only Transformer Optimization 101" ([Frisson blog](https://www.frisson-labs.com/blog)).

### MIMIC (erickfm, 2025–2026)

[repo](https://github.com/erickfm/MIMIC), [HF](https://huggingface.co/erickfm/MIMIC)
- **Models:** about 20M transformers, one per character or rank tier (e.g. `fox-master`, about 97k master-rank Fox perspectives), with a 180-frame window. Bootstrapped from HAL's recipe, with a 7-class button head so it can wavedash.
- **RLVR:** PPO on skill metrics the engine can verify, such as L-cancel rate.
- **Strength:** pure behaviour-cloning `fox-master` wins 29% against hosted Phillip over netplay. That is 4–10, only 14 games.
- **Data:** published [erickfm/melee-ranked-replays](https://huggingface.co/datasets/erickfm/melee-ranked-replays), about 850k ranked replays, 1.43 TB, with about 90% duplication across per-character buckets.

### Faynt (Frisson Labs, Oct 2026)

Paper [arXiv 2610.02144](https://arxiv.org/abs/2610.02144), [site](https://www.frisson-labs.com/faynt), [runtime](https://github.com/Na00s/Faynt-Tournament). Authors include Ali Janati and Nikita Kuzmin. Frisson describes itself as an AI-companions lab.

**Models:** 10M (5×384) and 75M (11×768) transformers; one checkpoint plays all 26 characters. They use GQA, RoPE and the Muon optimiser, with the slippi-ai 728/85 controller codec.

**Training stages:**
1. **Base:** behaviour cloning on about 840k ranked replays.
2. **Expert:** a "winner curriculum" that ends on 90% Master-winning data, plus 75M→10M distillation.
3. **Arena:** PPO on Fox mirrors only, run on 96 Dolphins on one L4 GPU, with a KL penalty toward the supervised policy.

**Results:**
- 240/244 mirror games against 14 frozen slippi-ai releases.
- 68/68 against a private zero-delay slippi-ai checkpoint, 61 of them four-stocks.
- RL took the 75M model from 25 to 58 wins.

**Caveat:** Faynt runs with **zero delay** while the frozen slippi-ai releases keep 21 or 24 frames. The authors say they "have not isolated the effect".

### Reyn (Frisson Labs, 11 Nov 2026)

[site](https://www.frisson-labs.com/reyn), [repo](https://github.com/frisson-labs/Reyn), [HF](https://huggingface.co/frisson-labs/Reyn-26C)

The closest published work to this repo's coach track, an LLM above a learned policy. Our coach is the LLM layer Reyn leaves out.

- **Steering:** builds on Faynt's 10M policy. A small neural router maps an English phrase to one of about 200 learned command tokens, such as "be more aggressive" or "pull a turnip". **There is no LLM in the frame loop.**
- **Command following:** met its target in 81.8% of 1,672 tests. This does not measure fighting strength.
- **Also released:** Reyn-Pair (2v2, trained with MAPPO) and a "wombo combo" experiment.
- **Browser arena:** [frisson-labs.com/arena](https://www.frisson-labs.com/arena).

### TypeSafe Jev (Sep 2026)

- **What it is:** a "System One" model from TypeSafe AI, founded by ex-OpenAI researcher Diogo Almeida ([blog](https://typesafe.ai/blog/introducing-system-one-models-and-jev), [docs](https://docs.typesafe.ai/models)).
- **How it works:** you send `state` and typed questions (Choice, Score, …) to `POST /v1/systemone`. It returns calibrated probabilities in one pass, with no text generation.
- **Speed and price:** 70–500 ms, $42 per billion input tokens.
- **Where it fits:** too slow for frame-level control, but it suits choosing a tactic every 4–30 frames, which is what `jev_live` / `coach_jev` do here.
- **Melee demos:** all community-built. One person self-reports beating the level 9 CPU after 13 games. **TypeSafe itself has published nothing on Melee**: none of its nine blog posts or its site pages mention it (checked 2026-11-14).
- **Related:** Google followed with "Gemini Decisions" in Nov 2026 ([codelab](https://codelabs.developers.google.com/codelabs/discriminative-models)).

### ExPhil (blasphemetheus, 2026)

[repo](https://github.com/blasphemetheus/exphil) (MIT, created Jan 2026, about 2,000 commits by Nov 2026). Author Bradley, Discord "dleie". The only other open-source bot on the stomped.dev ladder we know of. Read on 2026-11-16 at the repo's head.

- **Stack:** all Elixir on the BEAM: Nx/Axon with EXLA on the GPU, replays parsed by peppi through a Rust NIF, and two companion repos: [edifice](https://github.com/blasphemetheus/edifice) (about 90 architectures in Elixir) and [libmelee_ex](https://github.com/blasphemetheus/libmelee_ex) (a libmelee port). Much of the development is done by Claude and Codex agents working from dated handoff files in `docs/planning/`.
- **Goal:** low-tier bots (Mewtwo, Ganondorf, Link, Zelda, Ice Climbers, Game & Watch); Fox is where the recipes get worked out because its data is best.
- **Model:** a learned 288-dim state embedding (action, character and stage embeddings instead of one-hots), a swappable temporal backbone (30+: MLP, GRU, LSTM, Mamba, attention, RWKV, xLSTM…), and a 6-part autoregressive controller head: 8 buttons → main stick x → y → c-stick x → y → shoulder. The deployed Fox is a GRU 512×2 trained with BPTT. Early benchmarks put Mamba as the best speed/accuracy trade-off, but the repo now calls that table historical; a Fox Mamba run hit CUDA illegal-address crashes in Sep 2026.
- **How the strategy evolved** (from `docs/planning/model_lineage_*.json` and the handoffs):
  1. Mar 2026: architecture bake-offs on Mewtwo; a poisoned embedding cache invalidated the comparisons.
  2. Jul 2026: **scripted-expert drills with DAgger** (multishine, Mewtwo fair, Fox recovery). Their verdict: it "taught the button SEQUENCE not the DECISION".
  3. Jul–Aug 2026: exposure bias and a **reaction-delay campaign**: random 0–18 frame delay augmentation, the action queue fed back as an input, one checkpoint served at several delays.
  4. Sep 2026: causal labels (state at F paired with the controller at F+1+k; the earlier labels leaked), then **RL on the imitation prior in melee-sim-light** through a Rust NIF over its C batch API. PPO trains only the autoregressive head on a frozen GRU trunk, with a value MLP on the trunk features and a KL penalty toward the imitation head; reward is stock difference plus 0.01 × damage difference.
  5. "Search as teacher": random-shooting input sequences from sim savestates, scored by conversion detectors, kept as BC labels.
- **Guarding against reward hacking:** a "style fingerprint" (rolls, spot dodges, jumps, aerials per minute) compared with the imitation prior's own fingerprint, and a "degenerate zoo" of strategies RL found. Entry 1: Mewtwo PPO at iteration 300 rolled to the ledge and grab–back-threw 13× more than the prior; it beat a static sim opponent and nothing else.
- **On stomped.dev** as `latency_testing_exphil` (owner `exphil`): Fox, presumably the PPO GRU that its README serves as the example (`0923_ppo`). 3–31 on 16 Nov 2026, rating −9.8, 14th of 14 and just under our `m19182-yoshi` (8–69). Most losses are forfeits from server restarts; its three wins are over `entropy` and `hello-melee`.
- **Their stomped timing findings** (README, measured 15–16 Nov 2026), which apply to our bot too:
  - From a home connection through cloudflared, 52–65 ms round trip, so they serve lead 7 and train at that delay. Per-frame compute 0.6 ms on CPU for the GRU.
  - **Pads land one frame late in regular stretches:** every 1,000 frames, for about 530 frames, every pad field lands one frame after the frame it names, whatever the lead. The arena reuses the previous pad, so its `missed` count stays under 1% and hides it. A probe needs to last past frame ~1,100 to see it. ExPhil puts it on the arena's side, as a beat between 59.94 Hz and a 60.00 Hz clock.
  - **It is more likely Melee's own polling drift**, which SmashBot hit in 2016. altf4's [DEF CON 24 talk](https://www.youtube.com/watch?v=_0Z_oN_CZyA) (around 30:00): SmashBot's frame-perfect multishines failed in a repeating cycle because in vanilla Melee the controller polling and the game engine run on separate threads that drift apart until the engine reads the previous poll. Dan Salvato wrote the Polling Drift Fix Gecko code for it, "a 15-year-old bug in the game that up to this point no one has ever noticed". Kadano's [console measurements](https://kadano.net/SSBM/inputlag/) give the same shape as ExPhil's: in sync for the first ~23 s, then a cycle of about 16.7 s (about 1,000 frames). Slippi normally ships the fix ("Polling drift fix + VB" in Slippi's `GALEXX.ini`), but stomped runs with no Gecko codes, so the drift is back. Inferred from the match in period and onset; not yet confirmed against a stomped replay.
  - The server pins the lead to the delay the checkpoint was trained at and counts frames where they disagree; a lead that grows mid-match silently changes the policy's task.

### Other attempts worth knowing

- **Qwen plays Smash** ([post](https://hgali.sh/reflex), 2026): the closest LLM-in-the-loop prior work.
  - Qwen3-1.7B scores 19 tactic words from a one-line state, and a motor layer executes the chosen tactic.
  - A CUDA-graph rewrite took a decision from 260 ms to 30 ms.
  - He compared it honestly against six if-statements. His verdict: "It is not a good Melee player."
- **Academic and hobby projects:**
  - [Stanford CS224R 2025](https://cs224r.stanford.edu/spring_2025/projects/pdfs/cs224rfinalprojectreport.pdf): behaviour cloning plus IQL or PPO. It couldn't recover or beat the level 9 CPU.
  - [Leiden MSc thesis](https://theses.liacs.nl/pdf/2025-2026-HamelinkJJosef.pdf): fine-tunes HAL's architecture on Fox mirrors.
  - [ExPhil](https://github.com/blasphemetheus/exphil): see [its section](#exphil-blasphemetheus-2026).
  - [BaiShiXi Fox bots](https://baishixi.blog/posts/melee-fox-bots/).
  - [boxxfish smash-RL blog](https://boxxfish.github.io/blog/smash-rl-1).
  - [Athena](https://github.com/Sciguymjm/athena): a 2016 keras-rl stub.
  - [daboy](https://github.com/villinvic/daboy) (villinvic, 2020–21): RL bots, an indirect fork of spxtr's p3; demo videos only.
  - [Melee RL on OpenEnv](https://github.com/mathewrolf1/OpenENV-Hackathon) (Mar 2026 hackathon): PPO in a hand-written physics approximation, then fine-tuned in Dolphin through Meta's OpenEnv.
  - [melee-bot](https://github.com/wong-justin/melee-bot) (2021): a thin framework over libmelee for writing scripted bots.
  - [Sharma & Friedman 2017](https://www.yash-sharma.com/files/learning-play-super%20(3).pdf).
- **[stomped.dev](https://stomped.dev/) ([FAQ](https://stomped.dev/faq)):** a ranked arena for Melee bots only, and a ready-made benchmark venue for this repo.
  - Bots get the raw `.slp` event stream over WebSocket and must answer within 11 ms per frame.
  - Rules: vanilla 1.02 with no UCF, wobbling legal, frozen Stadium; ratings use OpenSkill. It streams on the "stompedlive" Twitch channel.
  - Launch: around 19 Oct 2026, the date of the domain's first TLS certificate.
  - On 14 Nov 2026 the ladder leader was 67–3, and the most active bot had played over 600 games. By developer on 13 Nov: kai 258–86, nescio 35–3, kcho 352–97.
  - 16 Nov 2026 (`GET https://api.stomped.dev/leaderboard`, 14 bots): nescio holds 1, 2, 4 and 8 with one bot per character (`nescio-fox1` 353–5, `-falco1`, `-marth1`, `-falcon1`); then kai's `ligma` 766–165, kcho's `filbot` 830–263, kai's `swaggy c`, procyon's `Lotor-1.5`. None of these publishes code that we found. Ours (`m19182-yoshi`) is 13th and ExPhil's 14th.
- **Simulators:**
  - [melee-sim-light](https://github.com/kyhavlov/melee-sim-light): Melee's gameplay code from the decompilation as a batched C library, with a Python API. It matched 287 of 300 of our Dolphin replays frame for frame (the other 13 were unfinished files) and runs about 100× faster than our headless Dolphin. slippi-ai's `sim_env` is built on it. See [simulator.md](simulator.md).
  - Enzyme's decomp-based simulator, used for slippi-ai training.
  - Others now train on melee-sim-light too: HAL has a native rollout adapter (`docs/native-simulator.md`, `hal.sim.native`), MIMIC's RLVR has `rlvr/sim/` (vectorised envs, batched GPU policy with KV-cache streaming), and ExPhil drives its C batch API from Elixir. [melee-replay-components](https://github.com/briandle00/melee-replay-components) hosts a prebuilt build plus a Training Mode patch.
- **[melee-unlocked](https://github.com/hero88go/melee-unlocked)** (Sep 2026): a native Windows source port compiled from the decompilation, with Slippi rollback. Its training mode has "Fight a pro": play Phillip as Zain's Marth, Cody's Fox or aMSa's Yoshi, with an 18–21 frame reaction delay. Offline only.
- **[No Johns](https://github.com/ScavieFae/nojohns):** agents wagering on bot-vs-bot matches, using Phillip or SmashBot as fighters.
- **The same problems in other real-time games:**
  - [FightingICE](https://www.ice.ci.ritsumei.ac.jp/~ftgaic/) (Ritsumeikan, competition since 2013, now at IEEE CoG): a 2D fighter built for AI research, with 56 actions, 16.67 ms per decision and a built-in 15-frame observation delay to mimic human reaction.
  - [GT Sophy](https://www.theverge.com/2022/2/9/22925420/sony-ai-gran-turismo-driving-gt-sophy-nature-paper) (Sony, Gran Turismo, 2022): pure RL, inputs capped at 10 Hz, and still superhuman when trained with 100–250 ms of added reaction delay.
  - AlphaStar (StarCraft II, 2019): the recipe the Melee bots converged on, supervised learning on 971k human replays, then multi-agent RL with a KL loss toward the supervised policy; Faynt cites it.
- **Adjacent LLM game benchmarks:**
  - [LLM Colosseum](https://github.com/OpenGenerativeAI/llm-colosseum): Street Fighter III from text state. GPT-3.5 beat GPT-4 there, because speed won.
  - [VideoGameBench](https://arxiv.org/abs/2505.18134): its "Lite" mode pauses the game while the model thinks, the same idea as our `paused` mode.
  - Claude and Gemini Plays Pokémon.

## 3. Fairness, the recurring debate

- **Reaction time.** Humans react in about 12–15 frames. Phillip v1 took about 2, SmashBot 0. Fixes so far: fixed action queues (12 frames in Sharma, 18–24 in Phillip II); predictive models; masking early action-state labels such as tech direction; and behaviour cloning, which inherits human timing.
- **Lockstep vs real time.** In local or lockstep play Dolphin waits for the bot, so inference cost is invisible and "0 delay" is superhuman (HAL README, Faynt §F.3). Over netplay a bot must fit in 16.7 ms per frame, or plan in chunks. Slippi rollback adds about 2 frames of buffer.
- **Equal delay.** **Cross-bot results only compare fairly at equal delay.** Faynt's 240/244 is zero delay against 21–24 frames.
- **Precision.** Bots see exact coordinates and action IDs and have no stick noise. Firoiu concedes an "unrealistically precise execution" advantage.
- **Platform rules.** No bots on Slippi Ranked or Unranked: libmelee, slippi-ai, MIMIC and Faynt all say so, and accounts get banned. A bot opt-in is "planned". Use Direct Connect or local play, as [netplay.md](netplay.md) does. Gu's 2200 Elo ladder test sits in tension with this rule. For ranked bot-vs-bot play there is [stomped.dev](https://stomped.dev/).
- **Data consent.** Players can opt out of having their replays used for training. Phillip pulled opted-out agents in Oct 2026.

## 4. Tooling and data

### Slippi (Fizzi / Jas Laferriere)

- **Timeline** ([SmashWiki](https://www.ssbwiki.com/Project_Slippi), [launch post](https://medium.com/project-slippi/project-public-release-4080c81d7205)):
  - Feb 2018 private beta; public release 18 Jun 2018 with replays and stats, as a modified Faster Melee build. Fizzi's pitch: "to date we have lost nearly 17 years of Melee competition data".
  - Sep 2018: SmashLadder makes it the main Dolphin build.
  - Mar 2019: console-to-Dolphin mirroring for tournament streams; slippi.gg launches with tournament replays.
  - Nov 2019: Fizzi leaves his job at smash.gg to work on it full time.
  - 22 Jun 2020: rollback netcode and matchmaking, three months into COVID lockdowns.
  - 12 Dec 2022: Ranked in early access for subscribers (Slippi 3.0.0), later free on some days, with $5/month for unlimited ([Upcomer](https://upcomer.com/what-is-slippi-ranked-how-to-use-the-online-super-smash-bros-melee-tool/)).
- **Netplay:** The in-game parts are PowerPC ASM Gecko codes ([slippi-ssbm-asm](https://github.com/project-slippi/slippi-ssbm-asm)).
- **`.slp` format** ([SPEC.md](https://github.com/project-slippi/slippi-wiki/blob/master/SPEC.md)):
  - The file is UBJSON with two parts: `raw`, a big-endian event stream, and `metadata`.
  - Event 0x35 declares the size of every other event. Fields are only appended, so parsers stay forward-compatible.
  - Main events: Game Start 0x36, Pre-Frame 0x37 (inputs), Post-Frame 0x38 (state after the frame), Game End 0x39, Frame Start 0x3A (RNG), Item Update 0x3B, Frame Bookend 0x3C (`latestFinalizedFrame`).
  - Frames start at **−123**; frame 0 is when the timer starts. Under rollback a frame can be emitted several times, so trust only what is ≤ `latestFinalizedFrame`.
- **Spectator protocol** ([SPECTATOR_PROTOCOL.md](https://github.com/project-slippi/slippi-wiki/blob/master/SPECTATOR_PROTOCOL.md)): ENet/UDP on port 51441, JSON messages: `connect_request` / `connect_reply`, `game_event` (base64 SLP), and `menu_event` (a snapshot of menu state). libmelee reads exactly this stream, and `ConsoleTap` in this repo taps it.
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
- **Viewer:** [Slippi Lab](https://github.com/frankborden/slippilab) (frankborden), a SolidJS viewer that draws characters from per-frame data, not from the game's 3D models. We patch it; see `patches/slippilab.patch`.
- **Datasets:**
  - Fizzi's anonymised ranked collections: distributed through the slippi-ai Discord.
  - [erickfm/melee-ranked-replays](https://huggingface.co/datasets/erickfm/melee-ranked-replays): needs deduplication before use.
  - HAL's 1.3M-game dataset on HF.
  - `erickfm/slippi-public-dataset-v3.7`: about 95k older tournament replays.

### Game internals and frame data

- **[doldecomp/melee](https://github.com/doldecomp/melee):** targets NTSC 1.02. [decomp.dev](https://decomp.dev/doldecomp/melee) reports it 100% decompiled and linked (19,828 functions); current work is naming. The repo dates from Jun 2020; it went from 47% in Nov 2025 to 84% in Aug 2026, then closed the rest in 37 days, reaching 100% on 7 Sep 2026 (PR #3409). Some contributors credit AI help (Claude, and Codex on at least two late PRs), which caused some argument when it was announced ([xenospectrum](https://xenospectrum.com/en/decompilation-match-rate-melee/), [EGamers](https://egamers.io/six-years-later-super-smash-bros-melee-has-been-fully-decompiled-and-it-plays-on-pc/)). It is the authoritative source for player structs, action-state logic and physics.
- **Action states:** IDs 0x000–0x154 are shared by all characters; higher IDs are character-specific. libmelee's `enums.Action` is the practical lookup table; cross-check it against the [ssbm-data](https://docs.rs/ssbm-data/) crate.
- **Frame data** (inputs the bot-writer and LLM prompts could cite):
  - [IKneeData](https://ikneedata.com): hitboxes and a knockback calculator.
  - [Melee Framedata Repository](https://meleeframedata.notion.site/Frying-Pan-b2d7f7a9a78a459aaa2eb2576a789cc7).
  - [SmashWiki](https://www.ssbwiki.com/).
  - [SRK SSBM Technical Data](https://srk.shib.live/w/SSBM/Technical_Data).
  - The Smashboards [hitbox and frame data thread](https://smashboards.com/threads/complete-hitbox-frame-data-for-every-character-now-with-ko-percents.383550/).
  - [The Melee Library](https://www.meleelibrary.com) (guides).
- **How modding got here** ([melee-gci-compiler](https://github.com/dansalvato/melee-gci-compiler)): a save-file buffer overflow giving arbitrary code execution was found by wParam in 2008. Training-focused Gecko codes appeared around 2013 (the 20XX Training Hack Pack, Achilles1515), and 20XX Tournament Edition (2014) was the first memory-card mod aimed at tournaments. Dan Salvato's [Universal Controller Fix](https://www.ssbwiki.com/Universal_Controller_Fix) (8 Aug 2017) widened the dashback window from one frame to two and eased shield drops, so that any controller could do what a lucky one could. Mod authors used to keep their tools private for fear of cheating at majors.
- **TAS:** the first Melee TASes (2005) used an Action Replay to enable the game's hidden debug mode; later, the 20XX pack's display of exact positions and speeds helped. The [Target Test TAS](https://tasvideos.org/7174S) (PracticalTAS, Mario 64 Master, ajp_anton, tauKhan, 2021) is a catalogue of physics exploits such as Samus's super wavedash. PracticalTAS's videos explain mechanics at the frame level. Full page: [tas.md](tas.md).
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
| Blogs | [Eric Gu](https://ericyuegu.com/), [Frisson Labs](https://www.frisson-labs.com/blog) |
| [Hacker News](https://news.ycombinator.com/item?id=13710253) | The 2017 Phillip thread is the main ML-crowd discussion; later Melee AI posts got little traction |

No tournament has run an official AI exhibition since Genesis 4 in 2017 **[unverified absence]**. Pro-vs-bot play moved to streams: x_pilot, the players' own channels, and the Oct 2026 crew battles.

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
| Bradley | blasphemetheus, dleie | ExPhil, edifice, libmelee_ex; the `exphil` bot on stomped.dev |
| Diogo Almeida | TypeSafe AI | Jev and System One models |
| Hareesh Gali | hgali.sh | Qwen plays Smash |
| hohav (now maintained by NickCondron) | hohav | peppi, py-slippi |
| Frank Borden | frankborden | Slippi Lab |
| vinceau | vinceau | slp-realtime, Project Clippi |
| UnclePunch | UnclePunch | Training Mode, Slippi contributions |
| Achilles1515 | Achilles | 20XX Training Pack, including the CPU AI overhaul |
| Enzyme | | Doubles Phillip and the decomp-based simulator |
| Pros vs bots | Cody Schwab, Zain, Hungrybox, Moky, aMSa, Aklo, Wizzrobe, Mew2King, Gravy, S2J | Recorded sets against Phillip |

## 7. What this means for this repo

- **Prior work:** no public LLM-plays-Melee benchmark was found. The closest are Reyn (a language router over a policy, with no LLM), Qwen plays Smash (a small LLM choosing tactics) and Jev community builds. Our coach-over-learned-bot and LLM-writes-bots tracks look new.
- **Benchmark design:**
  - Report results as Fox ditto on FD or Battlefield, and **state the delay and the mode** (lockstep, paused or real time). Otherwise results don't compare with Phillip, HAL or Faynt.
  - Level 9 is only a floor. The ladder above it, roughly by published head-to-heads: MIMIC < HAL < Phillip RL ≈ Faynt (at unequal delay).
- **Play rules:** never put a bot on Slippi online matchmaking. Direct Connect only.
- **Exploits to test:** the known Phillip exploits (Puff Rollout, Marth reacting to lasers) are cheap probes for whether an LLM coach can find and exploit a weakness.
- **Cheap upgrades:**
  - peppi-py over the HF ranked replays for few-shot examples per situation.
  - doldecomp, IKneeData and frame-data tables to make LLM state summaries accurate.
  - TM-CE drills as unit scenarios.

## 8. Best sources

Every link was opened on 2026-11-14.

### Start here

1. [SmashBot DEF CON 24 talk](https://www.youtube.com/watch?v=_0Z_oN_CZyA) (altf4, 2016): how a bot reads Melee's memory and drives a virtual controller.
2. [Phillip paper](https://arxiv.org/abs/1702.06230) (2017) and [Quartz's Genesis 4 story](https://qz.com/917221/a-super-smash-bros-playing-ai-has-taught-itself-how-to-stomp-professional-players): pure RL, and how pros reacted.
3. [At Human Speed](https://arxiv.org/abs/1810.07286) (2018): why delay is the fairness question.
4. [slippi-ai README](https://github.com/vladfi1/slippi-ai): the current reference pipeline and its history.
5. [HAL part 1](https://ericyuegu.com/behavior-cloning-melee/) (2025) and [part 2](https://ericyuegu.com/hillclimbing-melee/) (2026): the clearest modern write-ups on behaviour cloning and scaling.
6. [Faynt](https://www.frisson-labs.com/faynt) and [Reyn](https://www.frisson-labs.com/reyn) (Oct–Nov 2026): the state of the art, and language steering.
7. [Moky vs Phillip](https://www.youtube.com/watch?v=1kviVflqXc4) and [Zain vs Phillip](https://www.youtube.com/watch?v=c8nRFAGvr2c) (2024): what the agents look like against top players.

### Watch

| Date | Video | Why |
| --- | --- | --- |
| 2015-12 | [If a perfect bot entered a tournament (TAS)](https://www.youtube.com/watch?v=WDQS8fymeSQ), Practical TAS | The ceiling of frame-perfect play |
| 2016-08 | [DEF CON 24: Game Over, Man!](https://www.youtube.com/watch?v=_0Z_oN_CZyA), altf4 | The start of Melee bot engineering |
| 2017-02 | [Phillip vs Slox, Mafia](https://www.youtube.com/watch?v=dXJUlqBsZtE), vladfi1 | Pure-RL Phillip at Genesis 4: inhumanly fast and alien |
| 2017-09 | [SmashBot vs pros at JV5](https://www.youtube.com/watch?v=6CfPnK76B9A), altf4 | A hand-written, frame-perfect bot against humans |
| 2018-05 | [Phillip (12 delay) vs Professor Pro](https://www.youtube.com/watch?v=nEpyB0FHoA4), vladfi1 | The first human-speed agents |
| 2024-06 | [I played a new Smash AI](https://www.youtube.com/watch?v=OGOEqhMptq0), Aklo | A top player's first reaction to the imitation-learning Phillip |
| 2024-11 | [Ginger catches Phillip reacting on frame 18](https://www.youtube.com/watch?v=bXGvyRvLmE0) | The delay design, made visible |
| 2024-11 | [Zain, first to 5](https://www.youtube.com/watch?v=c8nRFAGvr2c), BME | The reference human win (5–3) |
| 2024-12 | [Moky, first to 10](https://www.youtube.com/watch?v=1kviVflqXc4), BME | Phillip wins 10–3, the most cited "superhuman" evidence |
| 2024-12 | [Phillip (Falcon, Fox) vs Hungrybox](https://www.youtube.com/watch?v=OMRP-jZcA4o), vladfi1 | Matchup generalisation failing in practice |
| 2024-12 | [AI – The end of Smash Bros.](https://www.youtube.com/watch?v=qRhCvcAXfvY), Hungrybox | A top player's take |
| 2026-10 | [Humans vs Robots crew battle](https://www.youtube.com/watch?v=Szm1y1JrNpQ), Zain, and [How I Saved Humanity from A.I.](https://www.youtube.com/watch?v=9b_2hzdTKNw), Mew2King | The big 2026 exhibition and its anchor comeback |
| 2026-10 | [Humanity vs AI rematch](https://www.twitch.tv/videos/2903721139), Cody | New agents, the same ending: Mew2King and Kirby |
| 2026-11 | [Wizzrobe vs new agents](https://www.youtube.com/watch?v=JY6gRwI5zB0), vladfi1 | The newest generation: v6 agents and super-gm |
| live | [twitch.tv/x_pilot](https://twitch.tv/x_pilot) | Play Phillip yourself |

We found no public talks by Vlad Firoiu or Eric Gu, no podcasts and no documentary about Melee AI.

### Read

| Date | Post | Why |
| --- | --- | --- |
| 2016-08 | [Reversing video games to create SmashBot](https://bishopfox.com/blog/reversing-video-games-to-create-smashbot-ai), Bishop Fox | The written version of the DEF CON talk |
| 2017-02 | [A Smash-playing AI taught itself to stomp pros](https://qz.com/917221/a-super-smash-bros-playing-ai-has-taught-itself-how-to-stomp-professional-players), Quartz | The best account of 2017 |
| 2018-06 | [Project Slippi public release](https://medium.com/project-slippi/project-public-release-4080c81d7205), Fizzi | Why `.slp` replays exist; every dataset descends from this |
| 2019-12 | [Fighting desyncs in Melee replays](https://medium.com/project-slippi/fighting-desyncs-in-melee-replays-370a830bf88b), Fizzi | How replay state and playback really work |
| 2022-08 | [Project Nabla](https://web.archive.org/web/20241121073045/https://bycn.github.io/2022/08/19/project-nabla.html) and [technical post](https://web.archive.org/web/20240814082645/https://bycn.github.io/2022/08/19/project-nabla-writeup.html), Bryan Chen | The first strong imitation-plus-self-play agent (archived copies) |
| 2024-02 | [Playing Smash with neural networks](https://boxxfish.github.io/blog/smash-rl-1), boxxfish | An approachable hobbyist RL write-up |
| 2025-02 | [Training AI to play Melee](https://ericyuegu.com/behavior-cloning-melee/), Eric Gu | Behaviour cloning done carefully, on a small budget |
| 2026-03 | [Human-like Fox v Fox bots](https://baishixi.blog/posts/melee-fox-bots/) | Does a pro-level imitation start beat an amateur one before RL? |
| 2026-07 | [Qwen plays Smash](https://hgali.sh/reflex), Hareesh Gali | An LLM in the frame loop; the closest prior work to this repo |
| 2026-10 | [Scaling pre-training on Melee](https://ericyuegu.com/hillclimbing-melee/), Eric Gu | Scaling, latency-aware inference, results against Phillip |
| 2026-10 | [Faynt](https://www.frisson-labs.com/faynt), Frisson Labs | The current strongest learned policy |
| 2026-10 | [Phillip's creator removed agents trained on opted-out players](https://gamingintelligence.ai/news/phillip-replay-opt-outs), Gaming Intelligence | Data consent for replay training |
| 2026-11 | [Reyn](https://www.frisson-labs.com/reyn), Frisson Labs | Language steering over a policy; closest to our coach track |

### Papers

| Date | Paper | Why |
| --- | --- | --- |
| 2017-02 | [Beating the World's Best at SSBM with Deep RL](https://arxiv.org/abs/1702.06230), Firoiu, Whitney, Tenenbaum | The founding paper |
| 2017-12 | [An "Untouchable" Agent](https://arxiv.org/abs/1712.03280), Parr, Dilipkumar, Liu | A small student project; its [HN thread](https://news.ycombinator.com/item?id=15919175) compares 20XX, SmashBot and Phillip |
| 2018 | [Learning to Play SSBM with Delayed Actions](https://www.yash-sharma.com/files/learning-play-super%20(3).pdf), Sharma, Friedman | Early work on reaction delay |
| 2018-10 | [At Human Speed](https://arxiv.org/abs/1810.07286), Firoiu, Ju, Tenenbaum | What made Phillip fair |
| 2025 | [Stanford CS224R report](https://cs224r.stanford.edu/spring_2025/projects/pdfs/cs224rfinalprojectreport.pdf) | Small-compute baseline; good on failure modes such as recovery |
| 2025 | [Transfer learning on matchups (Leiden MSc)](https://theses.liacs.nl/pdf/2025-2026-HamelinkJJosef.pdf), Hamelink | How agents transfer across matchups |
| 2026-10 | [Faynt](https://arxiv.org/abs/2610.02144), Janati, Kuzmin, Swamy, Niu | The state of the art in scaling learned policies |

### Code to read first

- [SmashBot](https://github.com/altf4/SmashBot): the strategy → tactic → chain structure. The model for an LLM-written bot.
- [slippi-ai](https://github.com/vladfi1/slippi-ai): the full pipeline, imitation learning then RL.
- [hal](https://github.com/ericyuegu/hal): clean transformer behaviour cloning.
- [MIMIC](https://github.com/erickfm/MIMIC): HAL with a fixed action head, and evaluation against Phillip.
- [vladfi1/libmelee](https://github.com/vladfi1/libmelee): the bot API.
- [ExPhil `lib/exphil/stomped/`](https://github.com/blasphemetheus/exphil/tree/main/lib/exphil/stomped) and its README's stomped section: another stomped.dev client, with measured arena timing.
- [peppi](https://github.com/hohav/peppi): replay parsing.
- [SPEC.md](https://github.com/project-slippi/slippi-wiki/blob/master/SPEC.md): the replay format.
- [doldecomp/melee](https://github.com/doldecomp/melee): ground truth for game mechanics.

### Melee for newcomers

- [The Smash Brothers, episode 1](https://www.youtube.com/watch?v=NSf2mgkRm7Q) (2013): the scene's history. [Metagame](https://www.ssbwiki.com/Metagame_(documentary)) (2020) covers the Five Gods era.
- [Competitive mechanics explained](https://www.youtube.com/watch?v=YT1917eRGFw), False Swipe Gaming: wavedash, L-cancel, shine and the rest, in one video.
- [Absolute beginner guide](https://www.youtube.com/watch?v=5307wx4fnTg), Ludvix: Slippi, controllers and getting started.
- [Making Sense of Melee](https://planetbanatt.net/articles/ambistats.html), planetbanatt: a data-driven look at what wins games. Useful intuition for rewards and evaluation.

## Questions closed on 2026-11-14

Details are in the sections above; this lists only the answers.

- **The crew battles against Phillip:** two, on 1 Oct (hosted by Zain) and 17 Oct (rematch on Cody's stream, settled by transcribing the VOD). The humans won both, with Mew2King anchoring each time.
- **Hungrybox:** has played Phillip many times (2024–2026).
- **Mang0:** no public set against Phillip, and his replays are excluded from the training data.
- **TypeSafe:** has published no Melee material of its own.
- **Melee at Evo:** absent since 2018, including 2025 and 2026.
- **stomped.dev:** live since about 19 Oct 2026.
- **The second 2017 tournament:** narrowed to between Genesis 4 (Jan) and 21 Feb 2017; its name is in no source we found.
- **The 2024–25 Reddit threads:** settled through the Manifold market. The Dec 2024 win fell outside the 2025 window, and the Kirby 4-stock counted as an exploit.
