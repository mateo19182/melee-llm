---
title: "Melee bots are getting really good"
subtitle: "…and what we can learn from them"
date: 2026-11-15
draft: true
tags:
  - writing
  - computers
---

<!-- Source: writeup/melee-bench.template.md. Numbers and figures come from writeup/make_figures.py; edit prose here, then re-run it. -->

> **TL;DR.** People have been building bots for Super Smash Bros. Melee for ten years, and the last two months were the busiest of all: the strongest bot yet, a bot you steer with English commands, top players beating an AI crew on stream, a ranked ladder for bots only, and a simulator that runs the game 100 times faster. Over two days I put all of it on one Elo scale: Melee's own CPUs, the published learned bots, and frontier LLMs in five different roles. The learned bots are far ahead. LLMs pressing the buttons in real time play below a level 1 CPU, no better than their autopilot with no model behind it; given unlimited time to think, the best one beats the hardest CPU, and so do bots that LLMs wrote in 30 minutes. The surprise came from coaching: a small bot coached by four frontier LLMs did best with no coach at all, just the words "Don't die."

[Slides from the 5-minute talk](slides.html)

Melee came out in 2001 and people still play it competitively. It runs at 60 frames per second and waits for nobody: one second of thinking is 60 frames in which you can get hit, grabbed and thrown off the stage. That makes it a hard target for AI, and its community has built absurdly good open tooling around it: [Slippi](https://slippi.gg) for online play and replays, [libmelee](https://github.com/vladfi1/libmelee) to read the game and press buttons from Python, and a decompilation of the game's own code.

I came to it with a question about LLMs. Most game benchmarks for them are turn-based (chess, Pokémon, [Slay the Spire](https://arxiv.org/abs/2610.12596)), where the game waits while the model thinks. I wanted a game that doesn't. The LLMs turned out to be the smaller part of the story, so this post starts with the bots.

---

## Melee in 30 seconds

Two characters fight on a small floating stage. Every hit raises the other player's damage percentage, and the higher it is, the further they fly. Knock them off the screen and they lose a life (a "stock"). Four stocks each, eight minutes, last one standing wins. It sounds simple, but at a high level it is about reactions measured in single frames and reading what your opponent will do next.

![A bench game redrawn from its replay file: Faynt (blue) takes a stock from Phillip gm (red), both playing Fox on Final Destination](media/replay-2d.webp)

*14 seconds of a bench game, redrawn from the replay file: Faynt (blue) takes a stock off Phillip (red), both playing Fox.*

Every game in this post is Fox against Fox, a staple of top-level play, on two standard tournament stages.

---

## Ten years of Melee bots, and why now

- **2001, the built-in CPUs.** Scripted, levels 1 to 9. Level 9 jabs and grabs on the exact frame, but it almost never shields, always recovers the same way, and loses to one move repeated.
- **2015, SmashBot.** Dan "altf4" Petro wrote a Fox bot by hand: goals, tactics and exact input sequences, driven by the game's frame data and with zero reaction time. He presented it at [DEF CON 24](https://www.youtube.com/watch?v=_0Z_oN_CZyA) and it played pros in 2017. Its plumbing became libmelee, which almost every bot since is built on.
- **2017, Phillip.** Vlad Firoiu at MIT trained a neural network by [reinforcement learning alone](https://arxiv.org/abs/1702.06230): no human games, just playing itself. It beat professional players, but it reacted in about 2 frames where a human needs 12 to 15. The [follow-up](https://arxiv.org/abs/1810.07286) made it play at human speed.
- **2018-2022, Slippi.** Replay files in 2018, rollback netplay in 2020, a ranked ladder in 2022. Suddenly there were hundreds of thousands of recorded human games to learn from.
- **2020-2024, Phillip again.** [slippi-ai](https://github.com/vladfi1/slippi-ai) set the recipe everyone uses now: first copy humans from replays (behaviour cloning), then improve by self-play while staying close to human play, with a human-like reaction delay of 18 to 24 frames built in. In late 2024 it played top players in public: Zain [won a first-to-5](https://www.youtube.com/watch?v=c8nRFAGvr2c) 5-3, and Moky [lost a first-to-10](https://www.youtube.com/watch?v=1kviVflqXc4) 3-10.
- **2025, cheap and open.** Eric Gu's [HAL](https://ericyuegu.com/behavior-cloning-melee/) cloned pro Fox games into a 20M-parameter transformer for about $5 of compute, and it beat the level 9 CPU 95% of the time. [MIMIC](https://github.com/erickfm/MIMIC) followed with one model per character. Both published their weights.
- **October 2026, humans against robots, on stream.** Top players took on Phillip in two crew battles, on [1 October](https://www.youtube.com/watch?v=Szm1y1JrNpQ) and [17 October](https://www.twitch.tv/videos/2903721139). The humans won both, with Mew2King as the last player standing each time.
- **October 2026, [Faynt](https://www.frisson-labs.com/faynt).** Frisson Labs released one 10M-parameter model that plays all 26 characters and won 240 of 244 games against Phillip's public releases. It reacts instantly while those keep their delay, so the comparison is not a fair one, but it is the strongest bot with public weights.
- **October 2026, HAL scaled up.** A 247M-parameter version [reached about 2200 Elo](https://ericyuegu.com/hillclimbing-melee/), the top 1% of the human ladder.
- **October 2026, [stomped.dev](https://stomped.dev).** A ranked ladder for bots only. Your bot gets 11 ms per frame to answer.
- **11 November 2026, [Reyn](https://www.frisson-labs.com/reyn).** Three days before this post, Frisson Labs released a bot you steer with a set of English commands.
- **And a simulator.** [melee-sim-light](https://github.com/kyhavlov/melee-sim-light) runs the decompiled game without an emulator, about 100 times faster.

The last six weeks alone changed the picture. The strongest bots can be downloaded and run on one home GPU. One of them has a language interface that an LLM can talk to. The game can be simulated far faster than real time. Cloning a decent bot costs a few dollars, and there is a public ladder to test it on. Nobody had put these bots on one scale, or asked where an LLM fits among them. So that is what I built, along with a website to watch it, an AI commentary booth, and a bot of my own.

## How the best bots work

None of them look at the screen. Through libmelee they read the game's memory every frame (positions, speeds, the current animation and how far into it, damage, stocks) and answer with a full controller state: both sticks, the triggers and every button. And almost all of them follow slippi-ai's recipe: copy humans first, then get better by playing against themselves. That is AlphaGo's recipe minus the search: AlphaGo also looked moves ahead, which a bot with 16 ms per frame and no way to rewind the game can't. The closest cousin is DeepMind's AlphaStar for StarCraft II, also real time, also cloned from human replays, then self-play with a penalty for drifting away from human play.

- **[Faynt](https://arxiv.org/abs/2610.02144)** (Frisson Labs) is a small transformer: 10M parameters in 5 layers of width 384, with a 75M sibling (11 × 768). It keeps a cache of the last 256 frames and takes one step per frame. Training has three stages: behaviour cloning on about 840,000 ranked replays; a "winner curriculum" that ends on 90% games won by Master-ranked players, with the 75M model distilled into the 10M one; then reinforcement learning (PPO) by self-play in Fox mirrors, 96 emulators on one GPU, with a penalty for drifting away from the human-like policy. RL took the 75M model from 25 to 58 wins in their test. It runs with zero reaction delay.
- **[Phillip](https://github.com/vladfi1/slippi-ai)** (slippi-ai, vladfi1) is a recurrent network rather than a transformer. Its output head picks the controller in two steps: one of 728 combinations of buttons, triggers and C-stick, then one of 85 main-stick positions given the first choice; Faynt reuses this encoding. It is cloned from ranked and pro replays, then trained by self-play with the same pull back toward human play. Its trademark is the delay: it sees the game 18 to 24 frames late, like a human reacting, which also makes it play well online.
- **[HAL](https://ericyuegu.com/hillclimbing-melee/)** (Eric Gu) is the biggest: a 247M decoder-only transformer with 256 frames of context, trained in 16 hours on one B200 on about 1.3M games (13.5 billion frames) from ranked play and 38 pros. It predicts 4 frames of inputs at a time and replans every 2, which hides its compute time. It is pure behaviour cloning, steered by asking for a given level of play (a "return target") or a given player's style, like "play like Cody". Gu's key finding: a frame of reaction delay hurts twice as much as a frame of acting without new information.
- **[MIMIC](https://github.com/erickfm/MIMIC)** (erickfm) takes HAL's recipe per character: about 20M parameters, a 180-frame window, a dedicated button head so it can wavedash, and a little RL on skills the game can check, such as L-cancel rate.
- **[Reyn](https://www.frisson-labs.com/reyn)** (Frisson Labs) is Faynt plus language steering, but not a vision-language-action model: there is no LLM and no image inside. Frisson labelled human replays with instructions using rules ("this is a grab", "this goes to the top platform") and trained Faynt's policy to play conditioned on them; then they froze the 10M policy and trained about 2.2M parameters of adapters with RL, penalised for drifting from unsteered play. At play time a small router maps your phrase onto one of a fixed set of learned commands, or rejects it. So it follows a menu of English commands rather than understanding English, which matters later.

The numbers that matter: these networks are tiny next to an LLM (10M to 247M parameters), they answer in 2 to 8 milliseconds a frame on one home GPU or even a CPU, and their strength comes from human replays plus self-play, not from reasoning. That is the gap the rest of this post measures.

---

## The benchmark

Everything runs on my home server: the real game, from my own disc, in the Slippi version of the Dolphin emulator. A Python library reads the game state every frame and drives a virtual controller. A dozen games can run side by side.

The opponents and yardsticks:

- **Melee's built-in CPUs**, levels 1 to 9.
- **Three small scripted bots** (one runs in, one shoots lasers, one spams Fox's "shine" move).
- **Five learned bots**, neural networks trained on human replays, all published with weights:
  [Phillip](https://github.com/vladfi1/slippi-ai) (vladfi1, in skill tiers from silver to gm, with a human-like reaction delay built in),
  [HAL](https://github.com/ericyuegu/hal) (Eric Gu),
  [MIMIC](https://github.com/erickfm/MIMIC) (erickfm),
  [Faynt](https://github.com/Na00s/Faynt-Tournament) (Frisson Labs) and
  [Reyn](https://huggingface.co/frisson-labs/Reyn-26C), from the same lab as Faynt: a small bot steered by **English commands** from a fixed set, like "be more aggressive" or "edgeguard from the stage", about 100 of them for Fox.

LLMs are far too slow to press buttons every frame (a frame is 16.7 ms; a reply takes 1-3 seconds), so every setup gives the LLM a higher-level job and lets something faster handle the frames:

1. **The LLM plays, untimed.** It reads a short text description of the game and picks a move (`laser`, `shine`, `wavedash`, `recover`, `grab then up-throw`...), which my code turns into button presses. The game pauses while it thinks, so this only measures how good its choices are.
2. **The LLM plays, live.** The same, at full speed. While the model thinks, the character keeps doing the last move or a safe default, and a few reflexes never wait for the model. A reply older than 2 seconds is thrown away.
3. **Jev plays.** [Jev](https://typesafe.ai/blog/introducing-system-one-models-and-jev) is TypeSafe's fast decision model: it answers multiple-choice questions in about 0.15 seconds instead of 1-3, but it can't write text.
4. **The LLM coaches Reyn.** Reyn plays every frame, and every 5 seconds the coach looks at the game and picks one of Reyn's English commands.
5. **The LLM writes a bot.** A coding agent gets 30 minutes, a sandbox, the docs and a practice tool, and has to write a Python bot that then plays like any other entrant.

Here is what the model sees, about 150 words per moment:

```
f1370 time 7:38
YOU FALCO 58% 4stk | pos (-36,38) vel (+0.0,-2.0) face L air | nair f19 [ACTIVE] | jumps 1, busy | 33 from edge
OPP SAMUS 60% 4stk | pos (-25,0) vel (+0.9,+0.0) face R ground | walk_fast f15 | jumps 2, actionable | 44 from edge
REL opp is right+below: dx +11 dy -38 dist 40; you face AWAY from opp; opp faces away from you
EVENTS you hit opp 10x +27%
RECENT DECISIONS:
f1230 laser(short,1) → laser: fired 1, landed
```

The models were Claude Haiku 4.5, Claude Sonnet 5.5, GPT-6 Luna and GPT-6.1 Sol, with reasoning turned off (with it on, Haiku spent its whole budget thinking and never answered).

### One scale for everyone

Every entrant plays the same game: Fox vs Fox, Battlefield or Final Destination, 4 stocks, 8 minutes. All the results go into one Elo fit, the rating system from chess: 400 points of difference means the stronger side wins about 10 games out of 11. The hardest CPU, level 9, is pinned at **1500**, and every rating comes with a 95% interval.

There is one board with two clocks, because "LLM plays" means two things: in **real time** the game never waits, and **untimed** it waits for every decision. CPUs and bots act on every frame and play the same either way, so they tie the two together.

Nobody picked the games by hand. A scheduler chooses the next game every few seconds, favouring games that would tighten the widest intervals for the fewest tokens. Cheap bot games get played a lot; expensive LLM games go where they teach the most. With older games that met the same rules, the board holds {{games_board}} games.

---

## What I found

![Real-time board: every entrant's Elo with its 95% interval, coloured by kind](figures/leaderboard-realtime.svg)

From the top:

- **Faynt never lost**: {{rec rt faynt}}, most of it against Phillip gm. With a perfect record the fit can only say "much better than everyone", so its {{elo rt faynt}} is really a floor. Then Phillip gm ({{elo rt phillip:gm}}) and HAL ({{elo rt hal:MASTER}}).
- **Reyn being coached** sits around HAL, whoever the coach is. And right near the top, **Reyn with no coach, holding "Don't die."** More on that below.
- **The bots LLMs wrote** run from {{written_min}} to {{written_max}}: {{n_written_above_cpu9}} of {{n_written}} beat the level 9 CPU, and the best is level with MIMIC.
- **The CPU levels rise in order**, from {{elo rt cpu:1}} for level 1 to {{elo rt cpu:8}} for level 8 and 1500 for level 9. That is a 20:1 gap in odds between the weakest and the hardest, small next to the 1,000 points between level 9 and Phillip gm.
- **At the bottom: every LLM playing live**, {{live_min}} to {{live_max}}, below even the level 1 CPU, together with live Jev and two players that use no model at all.

### 1. In real time, speed beats smarts

![Untimed vs real-time Elo for each model, with the share of live replies thrown away for arriving too late](figures/latency-tax.svg)

Given time to think, the models spread out: GPT-6.1 Sol beats the level 9 CPU ({{elo ut llm_paused:gpt-6.1-sol}}), the other three land between {{paused_rest_min}} and {{paused_rest_max}}, and all of them beat Jev ({{elo ut jev_paused}}). Bigger models make better choices than the fast one.

Live, all of that disappears. Every model loses {{tax_min}} to {{tax_max}} points, and they end up level with each other and with Jev. Sol, the best thinker, is the clearest case: its replies take 2-3 seconds, so **{{drop llm_live:gpt-6.1-sol}}** of them arrive too late and get thrown away. Live Sol is basically my default behaviour with an LLM occasionally getting a word in, and it still rates as high as any other live LLM ({{elo rt llm_live:gpt-6.1-sol}}). I checked that with two controls. The autopilot alone, never asking a model, rates {{elo rt llm_live:none}}, and a player that picks a random action at every decision rates {{elo rt llm_live:random}}. Every live LLM is inside the autopilot's interval: at this speed, the LLMs add nothing measurable over the simple autopilot they're wrapped in. Untimed, the same random player rates {{elo ut llm_paused:random}}, far below every model, so there the thinking does count. Even Haiku, fast enough that only {{drop llm_live:claude-haiku-4-5-20251001}} of its replies are dropped, acts on a game state about 70 frames old, and in Melee that's several exchanges ago.

[LLM Colosseum](https://github.com/OpenGenerativeAI/llm-colosseum) found the same thing in Street Fighter (GPT-3.5 beat GPT-4 by being faster); this puts it on a scale with error bars.

### 2. The best coach is two words

![Reyn's rating with no command, with random commands, with each LLM and Jev as coach, and holding "Don't die." all game](figures/coaching.svg)

Reyn with no orders rates {{elo rt reyn}}. With any coach it jumps by about 300 points, to HAL's level. But the obvious control, a "coach" that picks a random command every 5 seconds without looking at the game, gets most of that jump ({{elo rt coach:random}}). The four LLM coaches land {{coach_delta_min}} to {{coach_delta_max}} above random, and each of their intervals overlaps the random coach's. Only Jev is clearly better ({{elo rt coach_jev}}).

So I dug in, with about 25 extra games per variant:

- **Reyn mostly needs *any* command.** One random command held for the whole game already gets it to {{elo rt coach:random,fixed}}. Changing it every 5 seconds adds little on top.
- **Holding "Don't die." all game, with no coach at all, rates {{elo rt reyn:stock_protection}}**: level with the Jev coach, above every LLM coach, and about 330 above the random one.
- **Jev wins by accident.** Its favourite pick is "kill now", and Reyn's language layer maps that, every single time, to "Don't die." Counting that, Jev holds "Don't die." 41% of the time. The LLMs pick sensible-sounding plans (edgeguard, play aggressively) that turn out to be worth less.
- How often the coach speaks (every 1, 5 or 15 seconds) and giving it extra computed features made no measurable difference.

The lesson is less about LLMs than about the bot: the instruction that matters most is the boring one, and a language interface can quietly turn your coach's words into something else.

### 3. An LLM can write a level 9 CPU in 30 minutes, sometimes

![Bench rating of every bot an LLM wrote in a 30-minute session, next to CPUs, MIMIC and Phillip silver](figures/bot-writer.svg)

A coding agent gets a folder with a starter bot, docs and a practice tool, and 30 minutes. I ran {{n_written}} sessions with Claude Opus, Sonnet and Haiku, in three batches:

- **First try, one run each.** Sonnet's 135-line bot (shine, grab, lasers) rates {{elo rt written:sonnet-5.5/run1}}, Haiku 4.5's 108 lines {{elo rt written:haiku-4.5/run1}}, and Opus's 303 lines, the most engineered, {{elo rt written:opus-5.5/run1}}.
- **Three runs each at medium effort.** Opus was clearly ahead: {{w_opus_medium_min}} to {{w_opus_medium_max}}, all above the level 9 CPU. Sonnet ({{w_sonnet_medium_min}} to {{w_sonnet_medium_max}}) and Haiku ({{w_haiku_medium_min}} to {{w_haiku_medium_max}}) stayed below it.
- **Five runs each at high effort, with a better starter bot.** The three models came out level: Opus {{w_opus_high_mean}} on average, Haiku {{w_haiku_high_mean}}, Sonnet {{w_sonnet_high_mean}}.

That tie says more about the starter than about the models. The new starter was 60 lines that run at the opponent and up-smash, and I had not checked how strong it was before the batch. One Haiku session handed it in unchanged, and it rates {{elo rt written:haiku-5.5-high/run1}}: above the level 9 CPU. Haiku only ever edited it. Opus and Sonnet mostly rewrote it, into as many as 450 lines, and on average ended where they started. Two sessions clearly improved on it (the best reached {{written_max}}), and two made it clearly worse.

So: runs of one model differ by hundreds of points, a few lines of input timing decide more than the model does, and 60 lines of the right idea beat most of what 30 minutes of a strong model adds.

### 4. Screenshots don't help

Given a screenshot instead of (or with) the text description, Haiku did worse: against a level 5 CPU, text only went {{perc_text}}, screenshot only {{perc_image}}, both {{perc_both}} ({{perc_text_n}} games each). On images alone it mostly didn't notice it was hanging off the ledge. In a test on 100 frames, every model read the damage numbers almost perfectly but got left/right and facing at about chance.

---

## What else I built

### A website to watch it all

The [website](https://melee.m19182.dev) shows the boards with a page per entrant (record, recent games, sample decisions), every game running on the server drawn live in 2D, a launcher to set up any matchup, every replay with the AI's decisions on a timeline, and these docs. The **Live** page streams the real game with a broadcast-style score bar and a feed of what each AI is thinking, timed to the video.

### An AI commentary booth

The Live page has two AI casters: Charlie on play-by-play ("loud, fast, loses his mind on big moments") and Laura on colour ("quick, dry wit, teases Charlie"). A fast LLM watches the game's events (combos, stocks lost, zero-to-deaths, self-destructs) and writes a line or two every few seconds, and ElevenLabs voices them. To keep costs down, voices are only made while someone is listening. A real exchange from a Faynt vs HAL game:

> **Charlie:** HAL MASTER's Fox is in the air and Faynt's Marth is waiting for him!
> **Laura:** Waiting is the right word. Faynt doesn't chase, Charlie, he collects.

### Our own bot: m19182-yoshi

On the second day I trained a bot of my own, the way HAL did: a small transformer that copies human play, trained on 23,000 ranked online Yoshi games. It reads the last 4 seconds of the game and predicts the next controller input.

- **The first version** (6M parameters) lost all 12 of its games against the level 9 CPU. It took less than one stock per game.
- **A 20M version** won 1 of 12 and took about twice as many stocks per game.

That is still clearly below the level 9 CPU. The published bots got strong in the second stage, self-play, and that is where this one goes next.

### A simulator

Melee's community has decompiled the game's code back into C, and [melee-sim-light](https://github.com/kyhavlov/melee-sim-light) runs it without an emulator. I hooked all our players into it, including the learned bots, and checked it against real games: 287 of 300 replays matched frame for frame (the other 13 were unfinished files), and the game itself runs about 100 times faster than in the emulator. Its catch: there are no built-in CPUs.

### Playing the bots yourself

You can play the bots yourself, on a laptop with a controller (Phillip at any skill tier, Faynt or Reyn with a command of your choice) or from home over Slippi's online direct connect. The board has a slot waiting for human results. Come try.

---

Built on [Slippi](https://slippi.gg), [libmelee](https://github.com/vladfi1/libmelee), [Slippi Lab](https://github.com/frankborden/slippilab) and [melee-sim-light](https://github.com/kyhavlov/melee-sim-light), with the bots of vladfi1 (Phillip), Eric Gu (HAL), erickfm (MIMIC) and Frisson Labs (Faynt, Reyn), [TypeSafe's Jev](https://typesafe.ai/blog/introducing-system-one-models-and-jev) and [ElevenLabs](https://elevenlabs.io) voices. Related work I leaned on: [StarSkirmish](https://starskirmish.com/bench/v0-1/), [SpireBench](https://arxiv.org/abs/2610.12596), [VideoGameBench](https://arxiv.org/abs/2505.18134) and [Qwen plays Smash](https://hgali.sh/reflex). Technical details for every part are in the [docs](https://melee.m19182.dev/docs/status).
