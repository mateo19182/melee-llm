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
- **Two cracks in the standoff, both in the Fox ditto.** [sim] Holding shield next to a Fox who can act is a trap: every way out loses 5–18%, and the shield breaks by itself after 196 frames. And a Fox in the air beats a Fox on the ground in the shine war: he out-reaches him from above, and his double jump lets him shine again 2 frames sooner. Neither is a forced win from neutral yet; see [section 9](#9-two-cracks-in-the-fox-ditto-standoff-sim).
- **The Fox-ditto standoff as a playable defence: not a fortress yet, and not broken.** [sim] A Fox who only stands and answers what he sees must guess after 183 frames: the other walks to 13.2 and flicks his stick away, worth 25% of a clean first hit, or the defender shields into the trap above. A defender who gives ground at 13.7 and remembers every position where he had to guess was not cracked again in our samples and lands the first hit on nearly every approach, but each retreat costs 21 units of a finite stage. See [section 14](#14-the-fortress-a-fox-who-is-never-hit-first-as-a-policy-that-is-played-sim).
- **Even banned glitches don't change it.** [sim] Ness's yo-yo glitch reproduces in the simulator: his jab hits Fox from 35 units on frame 3. Fox still escapes on reaction, and setting it up needs a hit on Fox first. The freeze glitch and Soul Breaker need a grab, or items. [web]
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
| force | `force --gap 9 --ledge 12 --frames 10 --trap` | whether the attacking Fox can force the first hit against every defender answer (section 10) |
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

### 4c. Glitches, even banned ones: Ness's yo-yo "Deathline" reaches 35 units but is still answered on reaction [sim, web]

**Every game-deciding glitch needs a first hit, a grab or items:**

| Glitch | Effect | What it needs first |
| --- | --- | --- |
| Ice Climbers' [freeze glitch](https://www.ssbwiki.com/Freeze_glitch) | the opponent is frozen for good | Nana grabs Fox |
| Mewtwo's [Soul Breaker](https://www.ssbwiki.com/Soul_breaker) | the opponent is stuck to Mewtwo, unable to act | a grab while reflecting a too-strong projectile, in practice an item |
| [Black hole glitch](https://www.ssbwiki.com/List_of_glitches_(SSBM)) | a spot with endless hitboxes | turnips plus a Super Scope |

The [yo-yo glitch](https://www.ssbwiki.com/Yo-yo_glitch) is the one that attacks the question directly: it gives Ness near-limitless range. It is legal at the organizer's discretion.

**The setup reproduces in the simulator** (`python -m melee_llm.solver.yoyo`):
- Ness's up smash hits Fox (at 60% or 100%) once, on frame 11, and A is released on frames 23–28.
- Later, Fox walking past an idle Ness takes 4.6% from an invisible hitbox left behind Ness, where the yo-yo was on release. Other release frames leave nothing.
- The cause is in `ftNs_AttackHi4`: the yo-yo's rehit refresh never schedules the hitbox's removal.

**The Deathline also reproduces:**
- With Fox standing between Ness and the dropped hitbox, Ness's jab hits him **32–35 units away on frame 3**, and forward smash on frame 16.
- Without the glitch, neither connects from there.

**It still doesn't beat a reacting Fox:**
- Answering on the next frame with shine, shield, spotdodge, dash away, roll, jab, up smash or grab all escape the frame-3 jab. Only a short hop or down smash is still hit.
- Setting the glitch up needs a free up smash on Fox, which a perfect Fox never gives (section 2).

[inferred] Once it's set, a standing Fox caught in the line has to react every time Ness jabs. That costs a perfect player nothing, but it takes away his option to simply wait in that spot.

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

### 9. Two cracks in the Fox-ditto standoff [sim]

Probes: `scripts/solver_probes/` (run with `PYTHONPATH=. python scripts/solver_probes/<name>.py`). Both Foxes at 0% on Final Destination.

**The shield is a trap** (`shield_trap.py`). P2 holds shield; P1 stands 9.1 units away, able to act, and answers one frame after P2 moves. For each way out of shield, P1's best answer:

| P2 leaves shield by | P1's answer | P1 nets |
| --- | --- | --- |
| dropping it, jumping, jump then shine or nair, wavedash back, up smash out of shield | up smash (or shine for a sure 5%) | +18% |
| spotdodge | up smash timed for its end | +18% |
| roll in or away | chase and jab | +7% |
| shield grab | shine | +5% |
| holding on | nothing | 0%, until the shield breaks |

- One answer covers every exit that starts with a jump, which all look the same on frame 1: a shine 1–3 frames later always hits (+5%), and an up smash 11 frames later hits all six (+18%).
- An untouched shield shrinks to nothing and breaks after **196 frames** (3.3 s); under a multishine it breaks after 177.
- Grabbing the shield is worse for P1: a roll or spotdodge on reaction escapes it.
- So shielding is safe for a few frames, as the 9-frame trees say, but not as a place to stay. [inferred] A Fox who shields when the other walks up has already lost at least 5%.

**The Fox in the air wins the shine war** (`air_ground_reach.py`, `air_shine_race.py`, `facing_reach.py`).
- **Reach is one-sided from above.** During a short hop from 11.5 units, on 7 straight airborne frames (heights 5.6–10.6, horizontal distance 7.8–10.3) the air Fox's shine hits the standing Fox and the standing Fox's shine cannot hit back. The reverse happens on one frame only, as the hopper lands.
- **Same-frame shines favour the air Fox.** He cancels his shine with the double jump, which has no jumpsquat, and shines again on frame 5. The grounded Fox needs his 3-frame jumpsquat first and can't shine again before frame 7 ([frame data](https://www.ssbwiki.com/Reflector_(Fox))). Measured with the air Fox 7.9 units away:

| Air Fox shines on hop frame | Ground Fox waits | Ground Fox shines the same frame | Ground Fox shines one frame earlier | Ground Fox shields |
| --- | --- | --- | --- | --- |
| 5–6 (low: both reach) | air +5% | **air +5%** (double-jump re-shine) | ground +5% | 0 |
| 7–8 | air +5% | ground +5% against this follow-up (the re-shine is now too high and misses) | ground +5% | 0 |
| 9 | air +5% | ground +5% against this follow-up | **air +5%** (the early shine can't reach and is punished) | 0 |
| 10–12 (high: only air reaches) | air +5% | 0 | **air +5%** | 0 |

- From hop frame 9 on, the grounded Fox's shine no longer works as a defence: too early or too late loses 5%, and only the exact frame breaks even. His other safe answers are to shield, which leads to the trap above once the hopper lands next to him, or to back away.
- **Facing changes reach but not who wins:** face to face the shine reaches 10.7 units, with one Fox turned away 12.0, back to back 13.3. It is the same for both in every case (to our 0.4-unit resolution).

**What this does and doesn't show.** [inferred]
- In a symmetric position these cancel out: both Foxes have the same options, and re-shining as fast as possible is each one's best reply. Petro's ground deadlock survives.
- In an asymmetric position they don't. A Fox who gets above and beside the other with his double jump, or who walks up to a shield, is ahead.
- We haven't shown the attacker can force either position. The hop takes 5 or more frames to reach the one-sided zone, and the defender can back away on reaction. That turns the question into cornering: Final Destination is 171 units wide, and a Fox backed up to the ledge can no longer retreat. Solving that game needs frame-by-frame decisions over 15+ frames, which the 9-frame trees don't cover.

### 10. Forced-win search: can the attacker win without guessing? [sim]

`python -m melee_llm.solver.force --gap 9 --ledge 12 --frames 10 --trap` asks a stricter question than the equilibrium trees: does the attacking Fox have a line that lands the first hit whatever the defender does, even a defender who sees each input before answering? Both sides pick almost every frame from state-dependent menus (11 moves standing, 6 airborne, 7 in shield, 3 in the shine).

- **Result:** with the defender cornered 10 units from the ledge and the attacker at point-blank range (7.8 units), there is **no forced win within 10 frames** (372,172 positions, 61 s), even counting the shield trap of section 9 as a win. Every attacker move has an answer; the shine is answered only by a shine or a shield.
- **Why a forced win can't exist at close range:** [inferred] a defender who sees the attacker's shine can always shine on the same frame, and same-frame shines hit nobody. So a guaranteed hit would have to come from outside the shine exchange, and the search found none in this horizon. Any real edge for the attacker has to be a guessing edge: a mixed-strategy value above 0, which is what the equilibrium trees measure.
- **Speed, and why the language doesn't matter:** every branch copies the simulator's 1 MB match state inside its C library.

| Operation, one core | Cost |
| --- | --- |
| step one frame | 34 µs |
| save or restore a state (the equilibrium trees) | 2,400–2,600 µs |
| copy a state between lanes of one batch (this search) | about 300 µs |

  Profiled, the lane copy is 60% of the time, the step 30% and Python about 5%. One process searches about 2,700 positions/s; 8, 16 and 28 processes all reach about 10,500/s in total, because the copies saturate memory bandwidth. A faster search needs a smaller state copy inside the simulator, not a faster language around it. Section 11 does that.

### 11. A patched simulator, and the first position where the defender has to guess [sim]

**The patch.** An in-place checkpoint and rollback of one match, added to melee-sim-light. It now lives in our fork [melee-brute](https://github.com/mateo19182/melee-brute), which melee-llm installs instead of upstream (`melee_brute/rollback.py`).
- A frame changes about 3 KB of the match's 3.2 MB of memory, in a few dozen 4 KiB pages, always the same ones (71 pages after 3,000 frames of random inputs). The library's own lane copy moves everything and re-links every pointer; a rollback copies back only those pages.
- **Rollback 8.7 µs and checkpoint 8.3 µs, against about 300 µs for the lane copy.** A rollback followed by the same inputs reproduced the same savestate byte for byte in 200 of 200 random trials.
- Exactness is checked on every run: a rollback never restores the other pages, so a page that changed unexpectedly stays changed, and a final comparison with the starting state finds it. No run below reported one.
- The search of section 10 now plays on one match per process and takes moves back. It no longer saturates memory, so it scales with cores: **67,000–113,000 positions/s on 28 processes, against a ceiling of 10,500 before.** 14 frames from the corner take 3.4 minutes (13.8 million positions).

**Published as its own repo.** The patch, the rollback wrapper and the searches are also available standalone as [melee-brute](https://github.com/mateo19182/melee-brute), a fork of melee-sim-light that anyone can install without this project. It adds `best` (every line for one player) and `improve` (random changes to a long line, the method of TMInterface for Trackmania and of the SM64 bruteforcers). We found no such tool for Melee: TASes there are made by hand with Dolphin's Lua tools.

**Two questions bracket the truth.** `force` asks whether the attacker can force the first hit against a defender who sees his inputs. `force --safe` asks the mirror: does the defender have a defence that holds against an attacker who sees *his* inputs? If the first is yes the attacker wins outright; if the second is yes the position is a draw; if both are no, the defender has to guess and the equilibrium is mixed.

| Position (defender cornered about 10 units from the ledge) | Attacker can force a hit | Defender has a safe defence |
| --- | --- | --- |
| Both standing, 7.8 units apart, 14 frames | no | yes: shine, or shield (12 frames) |
| Both standing, 10.2 units apart, 12 frames | not run | yes: shine, or shield |
| **Attacker 9 frames into a short hop, 7.8 units away and 9.2 up**, 16 frames | not run | **only shield** |
| Attacker 11 frames into the hop, 6.9 away and 10.4 up, 10 frames | not run | only shield |

- **Standing at close range is a proven draw at this depth**: neither side needs to guess. This is Petro's deadlock, now with both bounds.
- **With the attacker in the air, the defender's shine stops being safe.** It is beaten by the attacker simply drifting or waiting: the shine misses upward and is punished. Every other move except shield also loses to some attacker reply. 22 million positions, 16 frames.
- **Shield is the trap of section 9.** [inferred] Once the hopper lands next to a shielding, cornered Fox, every exit measured there loses 5–18%. The 16-frame search ends about when the attacker lands, so it doesn't yet show the trap closing; that needs about 22 frames and is the next run.
- **What is still missing for "the attacker wins":** these air positions were set up with the defender standing still during the first 9 frames of the hop. Whether a cornered defender can stop the attacker from getting there (by hitting the jumpsquat, or by jumping himself) is a search from a standing start outside shine range, 25 or more frames deep.

### 12. Standing just outside shine range: a cycle with no safe move but shield [sim]

`force --gap 14 --frames 14 --trap --safe` (the defender cornered 12 units from the ledge, the attacker standing
12.59 away, 72 million positions). Against an attacker who sees his input, the defender's moves fare like this:

| Defender | Beaten by |
|---|---|
| wait | jab |
| shine | wait, step back (the shine misses and is punished) |
| jab | shine |
| walk in | wait, step back, shine, jab |
| any jump | wait, shine, jab |
| shield | nothing within 14 frames |

So without shield the position is a cycle (jab beats waiting, shine beats jab, waiting beats shine): standing still
is not safe, and the standoff of section 1 only holds if shield does. Whether shield holds past 14 frames is the
open question: a defender who sees the attacker walk in leaves his shield before the trap of section 9 closes
(12 frames: no forced win), so the searches now running start with him already in shield, 20 frames deep.

**Running long searches.** The first 22-frame run took the machine out of memory: every process kept every
position it had decided, about 1.2 KB each. The table is now two dictionaries keyed by a hash (140 bytes per
position), capped by `--tt-mb` and emptied when full; the process count is cut to fit the free memory; finished
jobs are appended to `--out` and skipped on a rerun; and `scripts/search.sh` starts the run as a user service with
a hard memory limit, so the search is what gets killed. The simulator library is now built with upstream's
`python-release` profile instead of the unoptimised default: identical play over 60,000 frames, 1.47 times the
search speed (14,000 positions a second per process).

### 13. The real game: both pick at once, one frame late [sim]

`melee_llm/solver/nash.py` solves the game without giving anyone the other's input: every frame both players
pick at the same time, knowing everything up to the previous frame. Each position is a matrix game solved exactly
(`matrix.py`); pure strategies that hold even when read settle a position without a matrix. All moves last one
frame. The payoff is the chance that the attacker lands a clean first hit.

Animated, frame by frame, from simulator traces: [animations/optimal-play.html](animations/optimal-play.html)
(regenerate with `scripts/optimal_play_animations.py`).

**Two menu bugs found on the way, which weaken sections 9 to 12 for the defender.** (1) The "jump" out of shield
in `force.py` and in the shield-trap probe was X alone, which only drops the shield; a jump out of shield needs
the shield button held. (2) Nobody could shine on the first airborne frame out of a jumpsquat. Both are fixed
(`jump_oos`, `shine` in the jumpsquat menu); the earlier tables were not rerun.

| Position (defender cornered 12 units from the ledge) | Horizon | Attacker's chance of a clean first hit | Optimal play |
| --- | --- | --- | --- |
| Both standing, 12.59 apart | 8 frames | **0** | both wait; the defender needs no shield |
| Same, defender never shields | 8 | **0** | both wait |
| Defender in shield and must leave it; attacker standing 7.8 or 10.2 away | 10 | **1** | every exit is hit |
| Same, 12.59 away | 10 | 1 for release, jump, both rolls, shield grab; the spotdodge outlasts 10 frames and is hit for 18% on frame 16 to 22 of its 22 (direct check) | attacker waits, then shines the exit on its second frame (jabs a roll in or a shield grab) |
| Same, 16.8 away | 10 | 0 within the horizon for release and jump; the rolls and the spotdodge are hit at their end (Verification) | |
| **Attacker 9 frames into a short hop, 7.8 away and 9.2 up; defender never shields** | 8 | **0.5** | attacker: wait or shine, half each. Defender: step back or shine, half each |
| Same, defender may shield | 8 | 0 | defender shields |

- **The cycle of section 12 was an artefact.** One frame late, the defender simply waits and answers what he sees:
  the standoff holds at 12.59, with or without shield.
- **Shield is a one-way door.** Within 14.4 units of a standing Fox, a shielding Fox cannot leave: the attacker
  waits, sees the exit a frame late and shines or jabs it. The shine reaches a Fox in jumpsquat or starting a roll
  from 12.6, further than it reaches one standing (10.7); the jab reaches further still.
- **Against an airborne attacker the corner is a coin flip unless the defender shields**, and the shield is the
  one-way door once the attacker has landed. Whether the defender can get out while the attacker is still landing
  is the open question (`nash --hop 9 --trap --frames 16`, running).

**The standoff needs a one-frame reaction.** `nash --grain 2` makes every input last two frames, so an answer
comes up to two frames late. Standing 12.59 apart without shield, the value jumps from 0 to **0.382** (8 and 12
frames, cornered or mid-stage): the attacker plays wait 38%, shine 38%, jab 24%, the defender wait 38%, jab 38%,
shine 24%. So the draw of section 1 belongs to a player who answers on the very next frame; one frame slower and
neutral is rock-paper-scissors. With shield allowed the two-frame game is 0 again over 12 frames, but only
because the shield's cost (the one-way door) lies beyond the horizon.

#### Verification

An independent pass over this section (probes in `scripts/solver_probes/verify13/`, run with `PYTHONPATH=.`;
solves with `scripts/search.sh`, 4 or 5 processes). "Ran" is a solve or a replay in the raw simulator (`game.Sim`, no search class); everything else is
marked inferred.

**Bugs found and fixed first; every number below is from the fixed solver.**

| Bug | Effect | Fix |
| --- | --- | --- |
| The position key left out the previous frame's inputs (a held button is not a new press) | Wrong cell values: `out` against `hop` at 12.59 was 0.75 with 4 or more frames left, 0.6667 with the fixed key and with the table switched off. No value in the table above changed | Previous inputs are in the key (about twice the positions) |
| A grab moved no percent, so it never counted as a hit | Fox's standing grab catches a standing Fox from 12.59 on its 7th frame; the grab row was all 0 | A held fighter is a first hit |
| Dropping a shield was treated as 15 locked frames | It can be cut short by a jump or a spotdodge from its 2nd frame | New `release` menu |
| The jumpsquat menu lacked up-B, up smash and grab; the ground menu lacked the spotdodge (R and down, no shield first) | The up-B out of shield dodges the reaction shine at 12.59 (the jab still hits it) | Added to the default menus |
| `values` and the yes/no tables each took the whole `--tt-mb` | Memory above the budget | Each gets a third |
| `corner()` ignored `--ledge` above 25.6 | No mid-stage positions | P2 walks either way |

Soundness (claim D), ran: the old key against no table agrees at 4 frames on three positions and disagrees from
4 frames on in the cell above; a key made of every observed field, unrounded, changes nothing over 7 frames
(three positions); `forced` and `value` against a plain recursion on save and restore agree in 1,240 comparisons
over five positions (horizons 1 and 2). RNG, ECB and intangibility timers are not in the key: no difference seen.

**A. One-way door: confirmed, and wider than stated (14.4, not 12.6); it ends between 14.4 and 16.8.**

- Ran, raw replay at 12.59: against release, jump and roll away the shine one frame after the exit deals 5% and
  takes 0; a roll in and a shield grab are missed by that shine and hit by a jab on the same frame (4%); against
  release and jump the up smash on reaction also works (18%).
- Ran, the spotdodge: 22 frames, hittable on the first and on the last 7, nothing cuts it short. At every gap from
  7.2 to 16.8 a waiting attacker up-smashes its end for 18%, and so does one who had already shined at it; an
  attacker who up-smashed on reaction is the one who gets punished. `--dodge` counts such a dodge as hit.
- Ran, rolls: free again on frame 31, intangible on 4 to 19. A waiting attacker has a clean punish at every gap
  from 12.6 to 21, cornered and mid-stage. Beyond the door only release and jump can be exits.
- Ran, `nash --shield 12 --must-exit --frames 10 --dodge`, attacker waiting on the first frame:

| Gap | release | jump | roll in | roll away | spotdodge | shield grab | Value |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 7.79, 11.99, 12.59, 13.79, 14.39 | 1 | 1 | 1 | 1 | 1 | 1 | **1** |
| 14.99 | 0.93 | 1 | 0 in 10 frames, hit later | 1 | 1 | 1 | 0.5 in 10 frames |
| 15.59 | 0 | 1 | 0, hit later | 1 | 1 | 1 | 0.17 |
| 16.19 | 0 | 1 | 0, hit later | 0, hit later | 1 | 1 | 0 |
| 16.79 | 0 | 0 | 0, hit later | 0, hit later | 1 | 1 | 0 |

  So the plain release is the first way out (from 15, partly) and the jump the second (from 16.8). Past 14.4 the
  zeros for release are lower bounds for the attacker: the dodge rule only covers a standing or shining attacker,
  not one who has dashed in.
- Ran at 12.59, all value 1: shield held 2, 4, 12, 60 and 150 frames; defender mid-stage (12.71); defender facing
  away; attacker walking (12.28), dashing (12.23), turned round.
- Ran, exits outside the old menus, now in them: up smash and up-B out of shield, jump-cancelled grab, release
  then jump or spotdodge. Traced in the raw simulator and found to be one of the above on their first frames:
  wavedash, full hop and double jump (all jumpsquat), light shield and shield angling (still shield).
- Not run: an attacker in the middle of an attack or in the air.

**B. Standing 12.59 apart is a draw: confirmed** (ran, 8 frames, value 0, both wait, with grabs counted and the
spotdodge in both menus). The grab is answered on reaction. Ran with wide menus for both (three smashes, two tilts,
walking, crouch, full hop, wavedash; `standoff_wide.py`): over 8 frames the defender has a defence that holds
even when read, without shield; waiting is one. 10 frames with the wide menus did not finish in 25 minutes on
one process.

**C. Coin flip from hop frame 9: confirmed, 0.5** (ran, 8 frames). Raw replay of the four cells: wait against
shine and shine against step back end with the defender at 5%; wait against step back and shine against shine
end unhit. Adding spotdodge, up smash, down smash, crouch and a turn to the defender leaves 0.5 with the same
mix: the smashes lose to everything, and spotdodge, crouch and turn do no better than the step back. Rolls need
the shield and were not tried.

**Hop frame 5 (attacker 9.42 away, 4.0 up, defender never shields): confirmed, value 1.** Ran: with spotdodge, up
smash, down smash, crouch, walking either way and a turn added, the attacker still has a forced win (`forced`,
10 frames). His strategy replayed in the raw simulator: the shine on the first frame hits every answer at once
for 5% and takes 0, except a shine on the same frame, which he beats by jumping out of his shine on frame 8 and
shining again on frame 9. 300 of 300 random defenders were hit cleanly. A shield stops it, as section 13 says.

### 14. The fortress: a Fox who is never hit first, as a policy that is played [sim]

Section 13 solved single positions. Here the candidate defence is built as a policy, played from the match start
(`sim.start()`, both at their spawns, 120 apart) and attacked. `melee_llm/solver/fortress.py`; long runs with
`scripts/fortress.sh` (one systemd unit, 6 or 7 processes, 12 GB limit, resumable); tables with
`scripts/solver_probes/fortress/report.py`.

**The policy.** Each frame the defender (P2) takes the first input, in the order wait, step away, step in, hop,
shine, jab, grab, spotdodge, shield, such that whatever the attacker (P1) presses on that frame, P2 still has a
defence that holds for a lookahead of H frames even if P1 sees every input (`Nash.forced(..., attacking=False)`).
The rules are section 13's menus and position key (previous inputs included, grabs count), made stricter for the
defender:

- no new shield while P1 is free to act within 15 units, and a shield with a free P1 within 14.4 counts as hit (the
  one-way door);
- an early spotdodge beside a standing or shining P1 counts as hit (`--dodge`);
- leaving the stage counts as hit.

A position with no such input is a **crack**. **A crack is never a false alarm at its own horizon:** a matrix game
with payoffs between 0 and 1 is worth 0 only if one column is all zeros, so a position is worth 0 to H frames
exactly when the defender has a defence that holds when read. No safe input means the attacker has a positive
chance of a clean first hit within H frames. What a crack can be is avoidable: the defender got there by a choice
that looked safe H frames earlier.

Two ways of going on at a crack: (a) save it, play the exact mixed strategy of 6 frames until safe again, then
solve the crack exactly at 4 to 10 frames; (b) **learn**: mark the position in a file shared by all games, take
the game back frame by frame, marking every earlier position that has no safe input once marked positions count
as lost, and resume from the first position that still has one. The marked set is the outside of the fortress as
far as the attackers found it. By the same argument every marked position has a positive value at some horizon.

**Cost decides the horizon.** One uncached frame near contact costs 1 to 4 s at H = 6 and 30 to 60 s at H = 8
(12,000 simulator steps a second). Games are played at H = 6; H = 8 is used for the map of standing positions
and the exact solves, and for a few games that got 1 to 55 frames far. Far apart nothing is searched: a
standing defender further than 23 + 2.6 per remaining frame from an attacker who is not rolling cannot be hit in
that time (`Fortress.far`; measured by `scripts/solver_probes/fortress/reach.py` over every attacker line of 8
frames from 11 starts: the longest reach one frame before a hit is 21.9, **a jab**, which hits a standing Fox
from 20.5 on its third frame; the fastest movement outside a roll is 2.4 a frame).

**Proven to a horizon: the map of standing positions.** Both standing, facing each other. "Safe inputs" are the
defender's first inputs that hold for 8 frames against an attacker who reads them (a proof for these menus and
8 frames); the value is the exact chance of a clean first hit for the attacker.

| Gap | Mid-stage | 12 from the ledge | 6 from the ledge | On the ledge |
| --- | --- | --- | --- | --- |
| 6.7 | none, value 0.5 | none | none | none |
| 7.2 to 10.9 | shine only (value 0 at 9.7, 10.3, 10.9) | shine only (wait too at 10.8) | shine only | **none** (value 0.5 at 7.3 and 10.3) |
| 11.5 to 12.0 | **none, value 0.29** (11.51) | **none, value 0.29** (11.99) | none (12.0) | none (11.5) |
| 12.6 to 12.7 | wait, step away (value 0 to 10 frames) | wait, step away | wait, step away | wait only |
| 14.5 to 15.0 | wait, step away, jab | same | same | wait, step away (a turn: he is on the ledge) |
| 18.6 | wait, step away, jab, spotdodge, shield | same | same | wait, step away, spotdodge, shield |
| 24.6 | those and step in, hop, shine | same | same | same |

- Standing still is a fortress only from 12.6 outwards. Between 11.5 and 12.0 a standing defender has no defence
  that holds when read, and the attacker gets a clean first hit 29% of the time within 8 frames (25% within 6).
  Inside 11 the only safe input is to shine first; at 6.7 it is a coin flip.
- **The ledge takes the shine away.** A defender standing on the ledge has no safe input at any gap up to 11.5
  (why: under "The ledge" below). Six units of room are enough to get the mid-stage row back.

**The line from the opening that makes a waiting defender guess** (exact, replayed in the raw simulator by
`scripts/solver_probes/fortress/opening_line.py`). P1 walks in for 182 frames (stick at 30) and on frame 183
flicks the stick away, the defender waiting throughout. Position: 13.19 apart, P1 in the first frame of a turn,
P2 standing. P2 has no safe input at 6 or 8 frames. Exact value **0.25** at 6 and at 8 frames: both play wait
50%, step away 25%, shine 25%. With `nash.py`'s own rules the value is 0, but only by shielding, and a shield
13.19 from a free Fox is the one-way door of section 13. So the policy "stand and answer what you see" is not a
fortress: an attacker reaches a position where it must guess, in 183 frames, without ever being in danger
himself (at lookahead 6 and with the defender allowed to take any hit he can force within 3 frames, no hit on
the walking attacker was forced).

What the defender has to do instead, against the same walk (P1 walking in from the opening, P2 standing; inputs
that hold for 8 frames when read, the marked positions of the learning games counted as lost;
`scripts/solver_probes/fortress/walk_in.py`):

| P1 walking, gap | 16.7 | 16.1 | 15.5 | 14.9 | 14.3 | 13.7 |
| --- | --- | --- | --- | --- | --- | --- |
| P2's safe inputs | wait, step away, jab | same | same | same | wait, step away | **step away only** |

Against a walking Fox the fortress ends at 13.7: the defender has to give ground, and one dash back carries him
21 units. From his spawn (25.6 from the ledge) the first retreat leaves him 3.95 from it.

**Games (samples).** One game is one run from the match start (or from a placed position where said) until the
first hit, the end of the attacker's plan, or its time limit. "Punish": the defender also takes any clean first
hit he can force within 3 or 4 frames. All at lookahead 6 unless said; no crack-free game is a proof of
anything beyond its own frames.

| Attacker | Games | Frames | Nobody hit | Defender hit | Attacker hit | Trade | Cracks (guess / forced) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Dash in and let go at 30 to 8; run through; crowd at 17 with hops; dash-dance at 12, 16, 22; in and out; shield next to him. Punish 3 | 15 | 904 | 5 | 0 | 10 | 0 | 0 (0 / 0) |
| Walk in and stop at 30, 26, ... 6, stand 40 frames. Punish 3 | 7 | 1,490 | 5 | 0 | 2 | 0 | 0 (0 / 0) |
| Walk in to 10, 12, ... 30, stand, short hop (stick in, neutral or away; shine or nair in the air, shine on landing, or nothing). Punish 3 | 18 | 3,696 | 3 | 0 | 15 | 0 | 0 (0 / 0) |
| The same hops, and full hops, from a standing start 10 to 30 apart mid-stage; defender only defends | 28 | 1,602 | 14 | 0 | 14 | 0 | 2 (1 / 1) |
| Walk in to 12 to 16, then the adversary (two games with punish 3) | 7 | 1,663 | 2 | 4 | 1 | 0 | 5 (4 / 1) |
| Dash in, then the adversary | 1 | 68 | 0 | 0 | 1 | 0 | 0 (0 / 0) |
| Random held inputs | 16 | 1,321 | 1 | 0 | 15 | 0 | 1 (1 / 0) |
| Random held inputs. Punish 4 | 9 | 623 | 0 | 0 | 9 | 0 | 0 (0 / 0) |
| Defender placed 0 or 4 to 6 from the ledge, attacker 16 to 20 away: hop, dash in, crowd, adversary, random | 10 | 1,324 | 4 | 1 | 5 | 0 | 5 (1 / 4) |
| Three of those at lookahead 8 (400 s each) | 3 | 60 | 2 | 0 | 1 | 0 | 0 (0 / 0) |
| **All** | **114** | **12,751** | 36 | **5** | **73** | 0 | 13 |

- **The mirror: the fortress hits first far more often than it is hit** (73 games to 5). A dash in to 12 or
  closer, or through him, is shined as it arrives (frame 51), and a run that brakes slides 25 units into the same
  shine; a walk to 12.5 or closer is shined; a hop from 16 or 18 is jabbed in its jumpsquat; a dash-dance at 12
  to 22 is jabbed or shined on a turn; 24 of 25 random attackers were hit. Fox's jab reaches
  21, so any committed state 14 to 21 from the defender is inside his punish range. Dashing in and stopping at
  14.6 or further, walking in and stopping at 12.75 or further, and 17 of the 46 hop games (mostly the stick
  away or neutral, or a hop from 26 or more) ended with nobody hit.
- **The attackers that get through are the ones that walk to 13 to 15 and then do very little.** Every clean hit
  on the defender from the opening came from "walk in, then the adversary", which is section 13's standoff
  distance entered with the initiative.

**Cracks, solved exactly** (fortress rules, 4 to 10 frames as far as 2 minutes allowed; none is a false alarm,
by the argument above):

| Crack (attacker / defender) | Where it came up | Value at 6, 8, 10 frames | Class | Avoidable earlier? |
| --- | --- | --- | --- | --- |
| 13.19 apart, P1 first frame of a turn after walking in, P2 standing (and the same at 12.84, second frame) | 4 of 7 walk-in games, frame 183 to 194 | 0.25, 0.25, not reached | **guess** | Yes, at lookahead 6: in the learning games the walk back stopped one frame earlier (P2 steps away at 13.7 instead of waiting) |
| 10.71, P1 in jumpsquat, P2 first frame of a ground shine | walk-in game, frame 192 | 0.5, 1, 1 | **forced** | Yes at lookahead 6: the same kind of crack (his ground shine answered by a roll, its release animation punished) was walked back 14 to 18 frames in the learning games |
| P2 in shield or spotdodge under a hopping P1 (9.5 apart and 7 up; 1.9 apart) | hop from 14 with a shine on landing, placed start | 0.17, 0.17; then 1, 1, 1 | guess, then forced | Yes at lookahead 6: the learning game from this start marked 10 positions (walk back 4 frames) and then hit the hopper on frame 17 every time |
| 11.50, P2 landing from a hop, P1 near the end of a spotdodge | one random game, frame 100 | 0.5, 0.5, 0.5 | **guess** | Yes: replayed from 10, 20 and 40 frames earlier at lookahead 8 (18 to 40 frames each), no crack |
| On or near the ledge: P2 in a jab, a shine's end lag, a spotdodge or teetering, P1 2 to 6 away | 5 games started 0 to 6 from the ledge | 1, 1, 1 (four) and 0.17 (one) | **forced** (4), guess (1) | Only with room: see the ledge below |

The replays asked for in the plan (the same game from 10, 20 and 40 frames before the crack at lookahead 8)
finished only for the random game; against the adversary they got 1 to 14 frames far in their time and showed
nothing. The exact values 10 and 20 frames before three walk-in cracks are 0 at 6 and 8 frames (one to 10, one
to 12), as they must be that far from the crack. The learning games are the walk back that fits the machine.

**Learning games (samples, lookahead 6).** Game after game from the opening against the same kind of attacker
with a new seed, all sharing the marked positions.

| Attacker | Different rounds | Frames | Cracks, round by round | Positions marked | Deepest walk back | Closest to the ledge |
| --- | --- | --- | --- | --- | --- | --- |
| Walk in to 16, then the adversary | 6 | 1,384 | 0, 2, 1, 1, 0, 0 | 13 | 7 | 0.8 |
| Walk in to 14, then the adversary | 5 | 1,247 | 2, 0, 0, 0, 0 | 15 | 14 | 23.2 |
| Walk in to 13, then the adversary | 5 | 1,198 | 1, 1, 0, 1, 0 | 50 | 18 | 0.5 |
| Walk in to 15, then the adversary, punish 3 | 7 | 1,630 | 0, 0, 2, 15, 0, 0, 0 | 54 | 14 | 14.0 |
| Dash in, then the adversary | 5 | 725 | 0, 60, 3, 1, 0 | 253 | 18 | 11.0 |
| Walk in to 12 (the same game 1,619 times: P1 walks into a shine on frame 221) | 1 | 221 | 0 | 0 | 0 | 4.0 |
| Stalk: walk in to 13.2, 13.7 or 14.3, flick the stick away every other frame, follow (8 jobs, each one game repeated 155 to 1,759 times: P1 shined on frame 184 or 244 to 245) | 3 | 673 | 0 | 0 | 0 | 4.0 |
| **After those marks, new seeds:** walk in to 13, 14, 14 (punish 3), 15 (punish 3), 16, then the adversary | 10 | 2,116 | 0, 0; 0, 3; 0, 0; 0, 1; 0, 0 | 24 | 18 | 12.3 |
| After the marks: dash in, then the adversary | 3 | 254 | 0, 4, 0 | 60 | 16 | 11.0 |
| After the marks: hop from 14 with a shine on landing, placed start (then the same game 3,328 times: P1 hit on frame 17) | 2 | 34 | 4, 0 | 10 | 4 | 62.4 |
| After the marks: the adversary against a defender placed 4 from the ledge, and on it | 6 | 242 | 0, 1, 0; 0, 0, 0 | 13 | 13 | 0.0 |

In all 508 positions marked. A defender who backs out of every crack cannot be hit, so what counts is the cracks
and how far back they reach.

- Every walk back ended within 18 frames: no crack was unavoidable from more than 18 frames earlier, at this
  lookahead and against these attackers. None reached back to the opening; the earliest marked frame is 51.
- **It has not converged.** With new seeds and starts after the marks, 5 of 21 rounds still found cracks (13
  cracks, 107 more positions marked). The marked set grows by a few positions per new line; nothing bounds it yet.
- The 11 marked positions with the defender standing are of one kind: P1 is 12.0 to 14.9 away in the first
  frames of a turn, a dash, a crouch or a jump. The other 497 are his own committed moves (a shine and its
  release, an air shine, a spotdodge, an up smash) with P1 next to him.

**The ledge.** Placed 0 or 4 to 6 from the ledge with the attacker 16 to 20 away, the plain policy at lookahead
6 cracked in 5 of 10 games, four of the cracks forced (value 1 at 6, 8 and 10 frames), and was hit once: with no
room, the move it picks as safe for 6 frames (a jab, a shine, a spotdodge) is punished in its end lag. On the
ledge itself the reason there is no safe input inside 11.5 was traced at 8.5: the attacker shields the
defender's shine and the pushback slides the defender off the stage on the fourth frame (x 85.85), which the
rules count as lost without playing it out. From the opening the defender gets there by his own retreat: one
dash back from his spawn leaves him 3.95 from the ledge, and in three learning games he ended 0.5 to 0.8 from
it. He was not cracked there in the samples: the stalking attackers were shined when they walked in again (a
walk that stops slides 1.5 units, into shine range), and against a defender placed on the ledge or 4 from it
the adversary found one crack in six short rounds (walk back 13 frames). Those rounds are 2 to 81 frames each:
this is the thinnest part of the evidence.

#### Is it a stalemate?

**Not proven either way; what was built is not yet a fortress, and no forced line from the opening was found.**

Proven, for these menus and rules, to the horizon stated:

- Standing 12.6 or more apart, the defender has a defence that holds when read: 8 frames with safe inputs
  listed above, value 0 to 10 frames at 12.71 mid-stage.
- "Stand and answer what you see" is **not** a fortress. From the opening, in 183 frames of plain walking and one
  flick of the stick, the attacker reaches a position worth 0.25 to him (6 and 8 frames) unless the defender
  shields into the one-way door. The same goes for standing 11.5 to 12.0 apart (0.29) and for standing on the
  ledge with the attacker inside 11.5 (0.5 at 7.3 and at 10.3).
- A crack found by the policy always has a positive value at its own horizon; so has every marked position at
  some horizon.
- Against a walking attacker the defender's last safe distance is 13.7 (8 frames), where his only safe input is
  to step away.

Sampled (lookahead 6, the attackers above):

- Every crack found (116 over all games) was avoidable from at most 18 frames earlier; none reached back to
  the opening. The defender who gives ground at 13.7 and never plays into a marked position is still being
  cracked by new lines, at a falling rate (508 marks so far).
- The fortress lands the first hit on almost every scripted or random approach (73 games to 5 in the plain
  games; every stalking game).

Open:

- **The ledge is the question.** Each forced retreat costs about 21 units and the stage is finite; on the ledge
  itself there is no safe input inside 11.5. Whether an attacker can make him retreat twice without walking into a shine or a jab himself was
not found either way: the scripted stalkers could not, and the adversary only looks one frame ahead.
- Everything in the games is lookahead 6. At 8 a frame near contact costs 30 to 60 s, and the plan's deeper
  horizons (10 to 12) were only reached for single positions.
- The attackers are scripts, random inputs and a one-ply adversary. A search over attacker lines against the
  learning defender (the same marking, for the other side) is the next step, with the menus widened (wavedash,
  the reverse and turnaround moves, lasers, platform-less ledge options: none are in the menus).
- The payoff is the attacker's clean first hit. A crack says the defender must guess, not that the attacker is
  ahead: in the positions found the defender's own guesses hit too, and the game is symmetric.

## What this says about Petro's claim

- **"Two perfect Foxes walk in and shine on the same frame":** not optimal. Walking into shine range loses to a jab from 12 or more, and on the ground the same-frame shines clank rather than whiff.
- **"Deadlock":** yes, in a stronger form. Outside shine range, no committed move from either side gets through a frame-1 reaction, so neither side can move first.
- **"Fox is the best":** weakly supported. The frame-1 shine gives Fox a 10–16-unit disc no opponent can stand in, and nobody has the equivalent against him. The short-horizon equilibrium values lean his way at close range, but only by up to 2%. Neutral at range is a standoff for everyone we tested.

## Open next steps

- The cornering game, now concrete (section 14): the defender must step away from a walking Fox at 13.7, a dash back is 21 units, and on the ledge he has no safe input inside 11.5. Search the attacker's lines against the learning defender there, at a lookahead of 8 or more.
- Deeper trees with a better leaf: a small matrix game over continuation policies instead of a fixed idle or shield play-out.
- Wavedash, crouch cancel and DI in the menus.
- Yoshi's armored double jump and a frame-picked Judge as tree options.
- The powershield and reflector ping-pong for lasers.
- A ledge-stall cycle measured in the simulator.
