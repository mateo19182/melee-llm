---
title: LLMs vs Melee
date: 2026-11-14
draft: true
tags:
  - writing
  - computers
---

<!-- Source: writeup/melee-bench.template.md. Numbers and figures come from writeup/make_figures.py; edit prose here, then re-run it. -->

> **TL;DR.** I put LLMs inside Super Smash Bros. Melee in five different ways and rated all of them, along with Melee's CPUs and the best published learned bots, on one Elo scale. In real time, every LLM that presses the buttons itself plays about as well as a level 4-5 CPU. Untimed, the best one beats CPU 9. Letting an LLM coach a fast learned bot works well, but a coach that picks commands at random gets you most of the way there. Bots that LLMs wrote in 30 minutes land around CPU 9. The learned bots are in a different league. Numbers as of {{as_of}}, with the benchmark still running.

Most game benchmarks for LLMs are turn-based: chess, Pokémon, [Slay the Spire](https://arxiv.org/abs/2610.12596). The model can take as long as it wants, and the game waits. I wanted the opposite: a real game at 60 frames per second that doesn't wait for anyone, where a one-second thought costs you 60 frames in which you can get hit, grabbed and thrown off the stage.

Melee is the obvious candidate. It's 25 years old, still played competitively, and has absurdly good open tooling thanks to a community that refuses to let it die: [Slippi](https://slippi.gg) for netplay and replays, [libmelee](https://github.com/vladfi1/libmelee) to read the game state and drive a virtual controller from Python, and a line of learned bots going back to [Phillip](https://arxiv.org/abs/1702.06230) in 2017 that beat pros. I couldn't find anyone benchmarking LLMs on it, so I did.

---

## The setup

Everything runs on my home server: Slippi's Dolphin with a Melee ISO dumped from my own disc, headless and unthrottled for bot games, or capped at 60 fps for the real-time ones. libmelee (vladfi1's maintained fork) reads the state every frame and writes controller inputs. Up to a dozen or so Dolphins run in parallel, each with its own port and replay folder.

The opponents and reference points are Melee's built-in CPUs (levels 1-9), three small scripted bots, and five learned bots, all published with weights:

- [HAL](https://github.com/ericyuegu/hal) (Eric Gu): a 250M transformer trained by behaviour cloning on ranked replays.
- [Phillip / slippi-ai](https://github.com/vladfi1/slippi-ai) (vladfi1): imitation plus RL, in skill tiers from silver to gm, with a built-in human-like reaction delay of 18-24 frames.
- [MIMIC](https://github.com/erickfm/MIMIC) (erickfm): a 20M transformer, one checkpoint per character.
- [Faynt](https://github.com/Na00s/Faynt-Tournament) ([paper](https://arxiv.org/abs/2610.02144)): a 10M transformer with RL fine-tuning on Fox.
- [Reyn](https://huggingface.co/frisson-labs/Reyn-26C), from the same lab as Faynt: a 33M policy that takes **English commands** ("be more aggressive", "edgeguard from the stage", about 100 of them for Fox). This one turned out to be the most interesting body to put an LLM on top of.

Each bot runs in its own process and venv and gets the raw Slippi event stream, so it sees exactly the game state it was trained on. Reyn's upstream inference was too slow for real time on a loaded CPU, so I rewrote its step as a single CUDA graph (about 2 ms per frame, identical actions).

---

## Five ways to put an LLM in the loop

LLMs are far too slow to press buttons every frame (16.7 ms), so in every setup the model makes higher-level choices and something else handles the frames.

1. **LLM plays, untimed.** The model reads a short text rendering of the state and picks a macro (`laser`, `shine`, `wavedash`, `nair toward`, `recover`, `grab then up-throw`...), which a frame-level executor turns into inputs. The game pauses while it thinks, so this measures decision quality only.
2. **LLM plays, live.** Same thing at 60 fps. While the model thinks, the executor keeps running the last macro or a default (dash dance, or shield when the opponent is close), and a few reflexes (DI, tech, mash, recover) never wait for the model. A reply that arrives more than 120 frames (2 s) after the state it was based on is thrown away.
3. **Jev plays.** [Jev](https://typesafe.ai/blog/introducing-system-one-models-and-jev) is TypeSafe's "System One" model: structured state and a multiple-choice question in, calibrated probabilities out, no text. It answers in about 150 ms instead of 1-3 s.
4. **LLM coaches Reyn.** Reyn plays every frame. Every 5 seconds the coach sees the state, what happened since its last call and how its last commands went, and picks one of Reyn's commands (or keeps the current one). Controls: Reyn with no coach, a coach that picks uniformly at random, and Jev as the coach.
5. **LLM writes a bot.** A coding agent gets a sandbox with a bot template, libmelee docs, frame data and a tool to play practice games against CPUs and scripted bots, and 30 minutes to write a single-file Python bot. The bot then plays like any other entrant, with a 16 ms per-frame budget.

This is what the model sees in modes 1-4, about 100-170 tokens per state on top of a ~900-token system prompt:

```
f1370 time 7:38
YOU FALCO 58% 4stk | pos (-36,38) vel (+0.0,-2.0) face L air | nair f19 [ACTIVE] | jumps 1, busy | 33 from edge
OPP SAMUS 60% 4stk | pos (-25,0) vel (+0.9,+0.0) face R ground | walk_fast f15 | jumps 2, actionable | 44 from edge
REL opp is right+below: dx +11 dy -38 dist 40; you face AWAY from opp; opp faces away from you
EVENTS you hit opp 10x +27%
RECENT DECISIONS:
f1230 laser(short,1) → laser: fired 1, landed
```

The models were Claude Haiku 4.5 and Sonnet 5.5, and GPT-6 Luna and GPT-6.1 Sol, with reasoning off (with reasoning on, Haiku spent its whole token budget thinking and never answered).

---

## The bench

Every entrant plays the same game: Fox vs Fox, Battlefield or Final Destination, 4 stocks, 8 minutes, a full game. Each game is fed to a Bradley-Terry fit, which gives one Elo-style rating per entrant with **CPU 9 pinned at 1500**, and a 95% interval from bootstrapping the games.

There are two boards, because "LLM plays" means two different things:

- **Real time**: the game runs at 60 fps and never waits. Live LLMs, live Jev and all the coaches play here.
- **Untimed**: the game waits for every decision. Paused LLMs and paused Jev play here.

CPUs, learned bots and written bots don't spend wall-clock time thinking, so they play identically in both modes and count on both boards. They're the bridge: a live and a paused LLM never meet, but both play CPU 9, Phillip and the rest.

Games aren't scheduled round robin. A scheduler picks, every few seconds, the pairing that shrinks the widest intervals the most per expected token, so cheap bot games are played a lot and expensive LLM games go where they're most informative. It runs under a budget of {{budget_m}}M tokens. At the snapshot it had run {{games_bench}} games over {{hours}} hours and imported {{games_imported}} older ones (bot-writer ladders, pilots) that met the same rules, with {{tokens_m}}M tokens spent and {{n_entrants}} entrants.

---

## Results

![Real-time board: every entrant's Elo with 95% interval, colored by kind](figures/leaderboard-realtime.svg)

Reading it from the top:

- **Faynt never lost.** {{rec rt faynt}} at the snapshot, most of those games against Phillip gm. A perfect record means the fit can only say "a lot better than everyone else", so its rating ({{elo rt faynt}}) is really a lower bound, and its arrow runs off the chart. Then Phillip gm ({{elo rt phillip:gm}}) and HAL ({{elo rt hal:MASTER}}). Keep in mind that Phillip carries an 18-24 frame reaction delay by design and the others react on the next frame.
- **Coached Reyn** sits around HAL, above Phillip plat and MIMIC, whoever the coach is. More on that below.
- **The written bots** cluster around CPU 9 and the best scripted bot.
- **CPU levels are barely ordered in a Fox ditto.** CPU 9 is 1500 and CPU 8 is {{elo rt cpu:8}}, but levels 1-7 all sit between {{elo rt cpu:4}} and {{elo rt cpu:7}} in no useful order: CPU 1 ({{elo rt cpu:1}}) is above CPU 5 ({{elo rt cpu:5}}), and CPU 4 is the weakest. Melee's CPU Fox self-destructs a lot, and how often seems to matter more than its level.
- **At the bottom: every LLM playing live**, between {{live_min}} and {{live_max}}, around CPU 4-5, together with live Jev.

### Speed beats smarts in real time

![Untimed vs real-time Elo for each model, with the share of live replies dropped for being too stale](figures/latency-tax.svg)

Untimed, the models are spread out: GPT-6.1 Sol is above CPU 9 ({{elo ut llm_paused:gpt-6.1-sol}}, {{ci ut llm_paused:gpt-6.1-sol}}), the other three between {{paused_rest_min}} and {{paused_rest_max}}, and all of them above Jev ({{elo ut jev_paused}}). Give them time and the bigger models make better choices than the 150 ms classifier.

Live, all of that collapses: every model loses {{tax_min}} to {{tax_max}} points and they end up indistinguishable from each other and from Jev. The right column shows why. Sol's best untimed result turns into its worst problem live: its replies take about 2-3 s, so **{{drop llm_live:gpt-6.1-sol}}** of them arrive after the 2-second cutoff and are thrown away. Live Sol is basically the default dash dance plus reflexes, with an LLM occasionally getting a word in, and it is still rated as high as any other live LLM ({{elo rt llm_live:gpt-6.1-sol}}). Put differently: at this latency the live LLMs add nothing measurable over the scripted fallback they're wrapped in. Haiku is fast enough that only {{drop llm_live:claude-haiku-4-5-20251001}} of its replies are dropped, but each one is still about 70 frames old when it starts executing, and in Melee 70 frames is several exchanges ago.

None of this is new in spirit ([LLM Colosseum](https://github.com/OpenGenerativeAI/llm-colosseum) found GPT-3.5 beating GPT-4 at Street Fighter because it was faster), but it's nice to have it on a scale with error bars.

### Coaching works, but not because of the coach

![Reyn's rating uncoached, with a random coach, and with each LLM and Jev as coach](figures/coaching.svg)

Uncoached, Reyn is rated {{elo rt reyn}}. With *any* coach it jumps by 300+ points, to roughly HAL's level. The catch is that most of that jump comes from the random coach ({{elo rt coach:random}}), which changes Reyn's command every 5 seconds to something uniformly random from the menu and has no idea what's happening in the game.

The four LLM coaches land {{coach_delta_min}} to {{coach_delta_max}} points above random, and every one of their intervals overlaps the random coach's. The only coach clearly better than random is Jev ({{elo rt coach_jev}}, {{ci rt coach_jev}}, {{delta rt coach_jev coach:random}} over random), which is also the fastest and, in the pilot, the most conservative: it changed command on about 1 call in 7, where Haiku changed on about half.

My best guess is that uncoached Reyn gets stuck in habits that CPUs and bots punish, and any perturbation unsticks it. The LLMs do understand the game (their stated reasons are sensible), but at one call per 5 seconds, and 1-3 seconds stale, understanding doesn't buy much over noise. This is the result I'm least sure how to read, and the obvious ablations (fixed commands, a "change less often" random coach, faster coach intervals) are next.

### LLM-written bots: about CPU 9 for under $2

![Bench rating of the bots written by LLMs in 30 minutes, next to CPUs, scripted bots and Phillip's low tiers](figures/bot-writer.svg)

One 30-minute Claude Code session per model (the round was paused after the first wave to save subscription usage, so **n = 1 per model**):

- **Sonnet 5.5** wrote a compact 135-line bot that shines, jump-cancels the shine, grabs shielding opponents and fires lasers at range: {{elo rt written:sonnet-5.5/run1}}, just above CPU 9 and the best scripted bot. It declared itself done after 21 minutes and ignored about 25 "keep improving" nudges.
- **Haiku 4.5** wrote the simplest bot, 108 lines that mostly call libmelee's built-in multishine: {{elo rt written:haiku-4.5/run1}}, and the only written bot to take a game off a learned bot (one win against MIMIC on the ladder).
- **Opus 5.5** wrote the most engineered one, 303 lines with a macro queue, frame-data-based defence and punish combos: {{elo rt written:opus-5.5/run1}}, the weakest of the three. More machinery didn't pay off in 30 minutes.
- An earlier **Sonnet pilot** run, with the same skeleton but holding B instead of tapping it (so the shine rarely comes out) and a recovery that falls off the bottom about twice a game, is the lowest-rated entrant on the whole board ({{elo rt written:sonnet/pilot1}}).

The spread between two runs of the same model is much bigger than the spread between models, which is exactly what [StarSkirmish](https://starskirmish.com/bench/v0-1/) (LLMs writing StarCraft bots) warns about. A few lines of input timing decide everything. With one run per model, this ranks nothing.

### Images didn't help

A side experiment: give the untimed player a screenshot instead of (or alongside) the text state. With Haiku against CPU 5, 2-minute games, {{perc_text_n}} games each: text only went {{perc_text}}, screenshot only {{perc_image}}, both {{perc_both}}. On image alone the model mostly doesn't notice it's hanging from the ledge and keeps choosing dash dance. A probe on 100 frames found all models read the damage percentages almost perfectly, but get facing and left/right order at about chance, and Haiku got every frame where someone was offstage wrong. Two Foxes at 512x384 are just hard to read, and the text state is better for the decisions that matter.

---

## Costs

Claude and GPT tokens went through my subscriptions, so the real bill is the subscriptions. At the snapshot the bench had spent {{tokens_m}}M tokens: {{tokens_claude_m}}M on Claude models and {{tokens_gpt_m}}M on GPT models. At list prices the Claude part would be roughly ${{usd_claude}} (I don't have a price for the GPT models). Jev is billed per token on its own key and cost ${{usd_jev}} in total, which is a different universe.

Per game, from the bench:

{{table_tokens}}

The live rows include an estimate for replies that were thrown away for being stale: the bench only counted tokens of replies that were used, which misses about {{uncounted_m}}M tokens, mostly Sol's and Sonnet's. A coach costs 5-10x fewer tokens per game than a player, since it's called every 5 seconds instead of every half second, and it plays far better.

---

## Limitations

- **One matchup.** Fox vs Fox on two stages. Everything here could change with other characters, and the CPU numbers in particular are specific to Fox dittos.
- **The intervals are real.** Neighbours on the board usually overlap, and the coaching and bot-writer results rest on 40-70 games and one run per model respectively. The headline gaps (learned bots vs everything, live vs untimed, coached vs uncoached Reyn) are well outside the noise; most orderings inside a group are not.
- **The harness is part of the result.** The macros, reflexes, prompt and 2-second staleness cutoff are mine, and a better harness would score higher. The live players are, to a large degree, a measure of my executor.
- **Model versions and billing.** Models were called through a local proxy on subscriptions; providers can change what's behind a name.
- **No public infrastructure.** The web UI with live games, replays and decision logs is private for now.

---

## What's next

- **Coach ablations**, to find out what the coach is actually contributing: fixed commands, random coaches that change less often, faster LLM coaches.
- **Janky entrants**: live LLMs with a shorter leash (deciding every 10 frames, dropping anything older than 40), to see whether frequency beats quality.
- **Bot-writer round 2**: the remaining 12 runs (3 per model, plus GPT models through a tool loop), and 60-minute sessions.
- **A local fast brain**: a small model on the 3090 at ~0.5 s per decision, or a distilled classifier, since speed is what matters live.
- **Me**, over Slippi netplay, against the bots. The bench has a reserved slot for `human:mateo`. I'm not expecting a good number.

---

Built on [Slippi](https://slippi.gg), [libmelee](https://github.com/vladfi1/libmelee) and [Slippi Lab](https://github.com/frankborden/slippilab), with the bots of Eric Gu (HAL), vladfi1 (Phillip), erickfm (MIMIC) and Frisson Labs (Faynt, Reyn), and [TypeSafe's Jev](https://typesafe.ai/blog/introducing-system-one-models-and-jev). Related work I leaned on: [StarSkirmish](https://starskirmish.com/bench/v0-1/) for the bot-writer track, [SpireBench](https://arxiv.org/abs/2610.12596) and [VideoGameBench](https://arxiv.org/abs/2505.18134) for how other people benchmark LLMs in games, and [Qwen plays Smash](https://hgali.sh/reflex), the closest thing to this I found.
