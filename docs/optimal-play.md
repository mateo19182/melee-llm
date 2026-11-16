# Optimal play: can anyone beat a perfect Fox?

Dan Petro claimed at DEF CON 24 ([talk](https://www.youtube.com/watch?v=_0Z_oN_CZyA), [abstract](https://infocondb.org/con/def-con/def-con-24/game-over-man-reversing-video-games-to-create-an-unbeatable-ai-player)) that with perfect play Fox is the best character, and that two perfect Foxes walk in, shine on the same frame and deadlock. This page tests that claim and asks the follow-up questions on [melee-sim-light](simulator.md), the decompiled game:
- Can any character hit a TAS-perfect Fox before he can shine?
- Can anyone take a lead and then run out the clock?

Measured on 2026-11-16 on Final Destination, everyone at 0% unless stated, UCF on. **[sim]** marks a result measured in the simulator; **[web]** marks frame data or community knowledge, with a link; **[inferred]** marks reasoning we haven't measured.

## Short answer

- **Nobody's first move gets through Fox.** [sim] Every character, every grounded move on our menu, standing start, gaps 12–40: Fox reacting on the next frame never lost the first hit (1,085 cases). Petro's deadlock is real, but its mechanism is "nobody can act first", not "both shine on the same frame".
- **The exception is Fox's own shine.** [sim] Its hitbox is out on frame 1, so it can't be answered. Depending on the opponent's hurtbox it reaches 10 (Peach) to 16 (Yoshi) units, and inside that disc it gets through every reaction. Everything else Fox does is answered on reaction, like everyone else's moves. This frame-1 disc is the measured part of "Fox is best".
- **The shine is not what wins.** [sim] Its reach is short, about 9–11 units between the two fighters' centres. Ordinary moves out-range it: Fox's own jab hits at 21, Marth's jab at 30, and most of the cast lands a jab at 12 on frame 2. What saves Fox is the shine's **frame 1**: it is intangible, and on the ground its hitbox **clanks** with the attacker's grounded hitbox.
- **Same-frame shines:** [sim] on the ground they **clank** (0% to both, 4 frames of hitlag each, both stay in the shine). In the air they truly whiff: no hitlag, because the intangible hurtboxes skip the hit check. Shining one frame earlier deals 5%, on the ground or in the air.
- **Yoshi's armor and Game & Watch's Judge 9 beat the shine itself, but not Fox.** [sim] Yoshi's double-jump armor absorbs the shine at every percent. A frame-picked Judge 9 lands for 32% through a shine just out of its range. Fox jabs, shields or punishes both on reaction.
- **Equilibrium values are about 0 against every character tested**, from the solver below: within ±2.2% damage per exchange over a short horizon, leaning slightly to Fox at close range. Petro's own plan, "walk in, then shine", loses to a best response in every matchup, by 2–38%.
- **Running out the clock:** a timeout goes to the lower percent ([rules](https://www.ssbwiki.com/Tournament_rulesets_(SSBM))). With no ledge-grab limit, Fox, Falco, Sheik, Captain Falcon and Ganondorf have **fully intangible ledge stalls** ([SmashWiki](https://www.ssbwiki.com/Ledgestall)), so a lead could be held forever. Current rules cap cliff grabs at 40–60 per game and ban the known air stalls. Since nobody can force the first hit anyway, the clock rarely gets that far: a perfect game should time out at 0–0 and go to a 1-stock tiebreak that deadlocks the same way. [inferred]

## How it's measured

Code: `melee_llm/solver/`.
- `game.py` drives two fighters with raw inputs and holds a 30-move menu that is the same for every character: dash in or away, shield, spotdodge, roll, short hop, grab, jab, tilts, smashes, the four B moves, dash attack and dash grab, short-hop aerials, crouch, and pulling and throwing an item.
- Both fighters walk in from their spawns and stop, standing and facing each other, `gap` units apart (centre to centre).
- Hits are read from percent, or from the grabbed action states; clanks from both fighters entering hitlag with nobody damaged.

| Probe | Command (`python -m melee_llm.solver.…`) | What it measures |
| --- | --- | --- |
| reach | `probe reach --chars MARTH` | the farthest gap each move hits a standing, idle Fox from, and on which frame |
| duel | `probe duel --chars MARTH --gaps 12 20 30` | the attacker starts a move; Fox answers on frame d ≥ 1 with each of 10 reactions (shine, shield, spotdodge, dash away, roll, short hop, jab, up and down smash, grab). Outcomes: through, traded, blocked or punished |
| shine_vs | `probe shine_vs --chars JIGGLYPUFF --moves down_b [--air 8]` | Fox shines 2 frames before, on, or 2 frames after the attacker's input, grounded or with both airborne |
| reflect | `probe reflect --gaps 40 --chars SAMUS --moves side_b` | Fox holds the reflector up from frame d, for every d before the projectile would hit |
| tree | `neutral --char MARTH --moves … --fox-moves … --depth 2` | exact Nash equilibrium of 2 simultaneous 3-frame picks from a 15-move menu, then a 25-frame play-out |

"Frame 1 reaction" means Fox sees the attacker's new action state on the frame it starts and inputs his answer on the next frame. A TAS can't do better without reading the opponent's inputs in advance.

## Findings

### 1. Reach: plenty of moves hit Fox from outside shine range [sim]

The farthest gap at which a move hits a standing, idle Fox, with the hit frame there:

| Character | jab | best tilt | fsmash | grab / dash grab | notable |
| --- | --- | --- | --- | --- | --- |
| Fox | 21 (f3) | dtilt 24 (f8) | 32 (f20) | 15 / 39 | shine 9–11 (f1) |
| Marth | 30 (f5) | ftilt / dtilt 30 | 35 (f11) | 23 / 40 | |
| Roy | 29 (f7) | ftilt 30 | 33 (f13) | 20 / 38 | |
| DK | 24 (f5) | ftilt / dtilt 31 | 32 (f22) | 21 / 26 | |
| Sheik | 23 (f3) | ftilt 25 | 36 (f27) | 17 / 33 | chain 46 (f34) |
| Falco | 25 (f3) | ftilt 26 | 35 (f20) | 16 / 30 | shine 8 (f1) |
| Samus | 21 (f3) | ftilt 28 | 26 (f12) | grapple 44 (f44) | |
| Captain Falcon | 18 (f3) | dtilt 26 | 29 (f21) | 14 / 41 | |
| Jigglypuff | 18 (f5) | dtilt 23 | 27 (f18) | 17 / 26 | Rest only on overlap |
| Peach | 20 (f2) | ftilt 18 | 20 (f22) | 15 / 26 | |
| Ice Climbers | 20 (f4) | dtilt 23 | 23 (f14) | 14 / 26 | |

The full table for all 26 characters comes from `probe reach`. Most of the cast hits at a gap of about 12 on frame 2–5, just beyond the shine. Petro's plan, walking into shine range, walks into these moves.

**Caveat:** the gap is between centres along x. Fox's jab reaching 21 on frame 3 surprised us, but it reproduces frame by frame in the simulator; we haven't cross-checked it against Dolphin.

### 2. Duels: no move gets through a Fox who reacts on the next frame [sim]

Across 26 characters, 13 moves (jab, ftilt, dtilt, fsmash, dsmash, grab, neutral-B, side-B, down-B, dash attack, dash grab, short-hop nair and fair) and gaps 12–40, the duel probe found 1,085 cases where the move hits an idle Fox:

- Fox's best answer: **punished** in 1,002 cases, **blocked** in 83.
- **Through: 0. Traded: 0.**
- His best answer was the shine in 765 cases and jab in 288; grab, up smash, shield, spotdodge, down smash and dashing away cover the rest.

The 83 blocked cases are where the shine's frame 1 matters:
- **52 clanks:** Fox shines on frame 1 after the attacker's input. His grounded shine hitbox meets the attacker's grounded hitbox (a jab's fist, for example) and the hitboxes clank (`ftColl_80078C70` checks hitbox against hitbox before hitbox against hurtbox).
- **20 whiffs** into the shine's frame-1 intangibility.
- **11** shields, spotdodges or retreats.

Frame-2 jabs at gap 12 fall into this group: Fox cannot shield in time, but a frame-1 shine survives them.

Grabs, including the Ice Climbers' grab into a [hand-off or wobble](https://www.ssbwiki.com/Ice_Climbers_(SSBM)/Grab) zero-to-death, never connected. Fox shines, jabs or spotdodges first, because every grab starts on frame 7 or later. A guaranteed stock off a grab is only worth something if the grab can land.

### 2b. The other way round: Fox's frame-1 shine is the one move nobody can react to [sim]

The same duel with Fox attacking and each opponent reacting: 9 targets (Marth, Sheik, Puff, Peach, Falco, Ice Climbers, Falcon, Samus, Yoshi), the same 13 moves, plus tilts and short-hop nair among the defender's answers.

Of 386 cases, 354 were punished and 26 blocked, and **6 got through**. All 6 are the shine at gap 12–16, against Sheik, Puff, Falcon, Samus and Yoshi. Its hitbox is out on frame 1, before any reaction exists, and how far it reaches depends on the target's hurtbox:

| Peach | Fox | Marth | Falco | Ice Climbers | Samus | Falcon | Sheik | Puff | Yoshi |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 10.0 | 10.3 | 11.0 | 11.3 | 11.3 | 12.3 | 12.7 | 13.2 | 14.1 | 15.9 |

No other character has anything that lands on frame 1 at these gaps. So every opponent has a disc around Fox (10–16 units) that they must never stand in, while Fox has no matching no-go zone in the other direction: a frame-2 jab is beaten by the shine's frame 1. This is the real, measured core of Petro's "Fox is best". It shows up as the small Fox-leaning values in section 7, not as a winning strategy: outside that disc, everyone is back to the standoff.

### 3. Jigglypuff's Rest [sim, web]

Rest has a hitbox on frame 1 only and intangibility on frames 1–26 ([Smashboards frame data](https://smashboards.com/threads/jigglypuff-hitbox-and-frame-data-nsf56k.303202/), [FightCore](https://www.fightcore.gg/characters/214/jigglypuff/moves/2015/adownb/)). In the simulator:
- **Standing next to Fox,** at the closest two standing fighters get (gap about 7), grounded Rest never connects. The shine reaches Puff out to 13 on the ground and 11.5 in the air: Puff's hurtbox is wide and Rest's hitbox is tiny.
- **Shine against Rest on the same frame:** no clank, no hit. Rest's intangibility eats the shine and Rest misses. Puff then sleeps for 249 frames.
- **A jump-in Rest timed through Fox's body** does connect on an idle Fox (28%, from gaps 8–20). A reacting Fox always beats it: he shines Puff during her jumpsquat (gaps 8–12) or as she arrives, before she overlaps him (gap 20).

### 4. Yoshi's double-jump armor eats the shine, but Yoshi still can't get in [sim]

Yoshi's double jump has heavy armor ([theyoshiguide.com](https://theyoshiguide.com), the double-jump-armor page: −120 knockback). The shine has set knockback, so it never beats the armor:
- **Every percent we can set (0, 20, 40, 60, 80, 100%):** shines landing on frames 7–21 of the jump deal 5% with no hitstun, and Yoshi stays in his double jump. Only shines before the double jump starts launch him.
- **Since the knockback is set, percent can't change this** at any value. [inferred]

The armor ends when Yoshi attacks, so he still has to cross the gap and hit Fox:
- Of the jump, double-jump-toward-Fox and aerial sequences we tried (nair, fair, dair, bair, timed 1–20 frames after the double jump, from gaps 8–25), 7 connect with an idle Fox.
- Fox punishes all 7 on reaction: he shines Yoshi before the double jump, or after the aerial has ended the armor.
- The armor is still the one thing we found that the shine simply cannot move. A fuller search of Yoshi's options (double jump into landing, egg throw, grab, waiting in the armor) is open.

### 4b. Mr. Game & Watch's Judge 9: picked by frame, still answered on reaction [sim, code]

This result comes from the parent research thread; we reran its script and got the same numbers.

**The number is chosen when G&W presses the button.** `ftGw_SpecialS_Enter` calls `ftGw_SpecialS_GetRandomInt` (`ftGw_SpecialS.c:119`), which draws from the game's RNG once. It also leaves the last two results out of the draw, so a 9 can come up at most once every three Judges.

A TAS sees the seed, so it knows each frame's result in advance:
- A given result holds for windows of 10–60 frames.
- From a neutral start, a 9 window opened within 44–105 frames, depending on what Fox was doing.
- Fox's inputs advance the RNG too, so he moves the windows around. Petro's "RNG war" is real here, at frame resolution.

**A 9 hits for 32%. Here is what Fox does, reacting one frame after the press:**

| Gap | Fox does nothing | Shine | Shield | Jab | Grab | Short hop |
| --- | --- | --- | --- | --- | --- | --- |
| 9.2 | Fox takes 32% | G&W takes 5% | blocked | G&W takes 4% | nothing | Fox takes 32% |
| 13.6 | Fox takes 32% | **Fox takes 32%** (shine out of range) | blocked | G&W takes 4% | nothing | Fox takes 32% |
| 17.5 | misses | misses | blocked | G&W takes 4% | Fox takes 32% | Fox takes 32% |
| 21.5 | misses | misses | blocked | G&W takes 4% | misses | misses |

So a Judge 9 just outside shine range beats a Fox who answers with the shine. Jab one frame later interrupts it at every gap, and shield blocks it. It's tournament-legal (no rule forbids picking the number by timing), but like everything else it's answered on reaction.

Peach's turnip pull and Luigi's misfire are drawn the same way, at the moment of input, so a TAS could pick them too. [inferred from the code; not measured]

### 5. Projectiles are reflected or stopped [sim, web]

Fox held his reflector up from frame d, for every d before the projectile would hit an idle Fox at gap 40. The shine reflects (the shooter takes damage) or stops (nobody hit) nearly every timing for every real projectile we fired:
- Mario's, Luigi's and Dr. Mario's fireballs; Fox's and Falco's lasers; Sheik's needles; Samus's missiles and charge shot; Mewtwo's Shadow Ball.
- Link's and Young Link's arrows, boomerangs and bombs; Peach's turnips; Pikachu's and Pichu's thunder jolts; Ice Climbers' ice shot; Mr. Game & Watch's Chef; Ness's PK Fire; Kirby's Final Cutter wave; Bowser's fire breath.

The "hit" timings are only those where the reflector came up too late. Sheik's chain (side-B) is not a projectile: it hits Fox at 46 whatever the reflector does, but it lands on frame 34, so Fox shields it on reaction. Melee's reflector shatters if a projectile is too strong ([SmashWiki](https://www.ssbwiki.com/Reflection)); we saw no shatters.

### 6. Fox's laser against everyone [sim]

A grounded laser hits every standing character out to the largest gap tested (about 110 units, landing on frame 25–26). The exception is Link, hit only out to 50; his idle shield probably blocks it from farther. [inferred]

Lasers deal 3% with no hitstun ([SmashWiki](https://www.ssbwiki.com/Fox_(SSBM))), so against a reacting opponent they are chip damage, which can be shielded or powershielded back. **They are the cleanest way to take a lead from range.** That makes the clock question below matter.

**Crouching ducks the standing laser entirely** for Jigglypuff, Kirby, Sheik and Mr. Game & Watch: no hit at any gap. [sim] Dignitas lists the first three ([Dignitas](https://dignitas.gg/articles/blogs/smash/12567/get-low-the-science-of-crouching)); Game & Watch is new to us. Pichu is hit only out to 91. Everyone else is hit crouching too.

### 7. Equilibria by matchup [sim]

Both sides pick from the same 15 moves:
- Challenger: wait, dash in, dash away, shield, hop, grab, jab, ftilt, dtilt, fsmash, dsmash, neutral-B, side-B, down-B, short-hop nair.
- Fox: the same, with the laser and the shine as his neutral-B and down-B.

The tree is two simultaneous 3-frame picks, then 25 frames of play-out. The value is the challenger's expected damage dealt minus taken.

| P1 vs Fox | gap ≈ 12, idle leaf | ≈ 20, idle | ≈ 30, idle | ≈ 12, shield leaf | ≈ 20, shield | ≈ 30, shield | Fox's Petro plan loses (idle / shield leaf) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Fox (ditto) | 0.00 | −0.10 | 0.00 | 0.00 | 0.00 | 0.00 | 15 / 9–15 |
| Marth | −1.71 | 0.00 | 0.00 | −0.92 | 0.00 | 0.00 | 14–21 / 11 |
| Sheik | −0.70 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 14–22 / 13–22 |
| Jigglypuff | −2.14 | −1.38 | 0.00 | −0.91 | 0.00 | 0.00 | 13–28 / 3–28 |
| Peach | −0.55 | −0.29 | 0.00 | 0.00 | 0.00 | 0.00 | 27–38 / 3–38 |
| Falco | −0.39 | **+1.42** | 0.00 | 0.00 | 0.00 | 0.00 | 16–17 / 16 |
| Ice Climbers (Popo + Nana) | −2.02 | −1.90 | 0.00 | 0.00 | 0.00 | 0.00 | 23 / 2–23 |
| Captain Falcon | −1.33 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 16–20 / 2 |
| Samus | −1.37 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 16 / 16 |

Negative favours Fox. The equilibria at gap 12 are mixed: the challenger shields 50–80% of the time, and Fox mixes wait, jab, hop and shine. At gap 30 both wait. JSON with every matrix: `--out`.

Every value is within ±2.2% damage per exchange.
- **The sign leans to Fox at close range:** 8 of 9 matchups at gap 12 with the idle leaf, and Marth and Puff with the shield leaf. That is the frame-1 shine of section 2b.
- **The one positive entry** is Falco at gap 20 with the idle leaf (+1.4); it disappears under the shield leaf.
- **The Fox ditto's −0.10** at gap 21 is port asymmetry, not a real edge.

**Limits:**
- 6 frames of decisions is short.
- The play-out leaf sets both fighters idle ("wait") or shielding, so a move started late lands on an idle defender in the first case and gets blocked in the second. The two leaves bracket the truth.
- No wavedash, crouch cancel, DI or SDI in the menus.

### 8. Running out the clock [web, inferred]

- **Rules:** a timeout goes to stocks, then lower percent; a tie in both means a 1-stock, 3-minute tiebreak ([SmashWiki ruleset](https://www.ssbwiki.com/Tournament_rulesets_(SSBM)), [Panda Cup 2022](https://pandacup.com/files/melee-ruleset.pdf)).
- **Ledge-grab limit:** 40 cliff grabs on a timeout (50 regardless), or 45–60 depending on the event. Wobbling is banned at most events since 2020.
- **Banned stalls:** repeated rising Pound, Peach Bomber against a wall, the Luigi ladder. Jigglypuff's Sing at the ledge is a true infinite and is banned ([SmashWiki: Stalling](https://www.ssbwiki.com/Stalling)).
- **Ledge stalls:** grabbing the ledge gives 30 frames of intangibility after the 7-frame catch; the regrab lockout after letting go is 29 frames ([SmashWiki: Ledgestall](https://www.ssbwiki.com/Ledgestall), [Liquipedia](https://liquipedia.net/smash/Intangibility)).
  - Fully intangible ledge stalls exist for Fox and Falco (up-B, or shine and jump cancel), Sheik (Vanish: the Shino and Sami stalls), and Captain Falcon and Ganondorf (fast-fall double jump, Haxdash).
  - Every character can stall indefinitely at the ledge with some gaps.
  - With no grab limit, as in 2016, one of these characters with a lead could stay intangible until time runs out. Under a limit they get at most 40–60 grabs: roughly 40 × 37 frames, about 25 seconds of an 8-minute game.
- **Running away:** [sim] distance covered in the first 40 frames of running:

  | Captain Falcon | Yoshi | Mewtwo | DK | Young Link | Fox |
  | --- | --- | --- | --- | --- | --- |
  | 56.6 | 52.2 | 49.4 | 48.2 | 47.8 | 47.7 |

  Final Destination is bounded, so running alone cannot avoid being cornered. A cornered player escapes past the chaser by jumping over or rolling, or by going to the ledge, which brings back the grab limit.
- **Putting it together:** [inferred] the duel results say the first committed attack loses. Perfect players therefore never get hit in neutral, and the score stays 0–0. The only lead available is chip damage that can't be fully blocked; Fox's 3% no-hitstun laser is the obvious candidate if the opponent mistimes a powershield. A TAS opponent powershields every laser, reflecting each one back at half damage ([SmashWiki: Reflection](https://www.ssbwiki.com/Reflection)), and Fox shines the reflection back. We haven't simulated that ping-pong.

## What this says about Petro's claim

- **"Two perfect Foxes walk in and shine on the same frame":** not optimal. Walking into shine range loses to a jab from 12 or more, and on the ground the same-frame shines clank rather than whiff.
- **"Deadlock":** yes, in a stronger form. Outside shine range, no committed move from either side gets through a frame-1 reaction, so neither side can move first.
- **"Fox is the best":** weakly supported. The frame-1 shine gives Fox a 10–16-unit disc no opponent can stand in, and nobody has the equivalent against him. The short-horizon equilibrium values lean his way at close range, but only by up to 2%. Neutral at range is a standoff for everyone we tested.

## Open next steps

- Deeper trees with a better leaf: a small matrix game over continuation policies instead of a fixed idle or shield play-out.
- Wavedash, crouch cancel and DI in the menus.
- Yoshi's armored double jump and a frame-picked Judge as tree options.
- The powershield and reflector ping-pong for lasers.
- A ledge-stall cycle measured in the simulator.
