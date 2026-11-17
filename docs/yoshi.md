# How top Yoshis play

What makes Yoshi strong in Melee, how aMSa plays him, and what that means for a bot with about 10 frames of input delay on stomped. Compiled on 2026-11-18 from the Yoshi community guide, SmashWiki, interviews and analysis articles; sources are at the end. Lines marked *inference* are our own reasoning, not a source's.

Not found: published per-game statistics for aMSa, and the armour break percent for every move (the community keeps them in a spreadsheet we could not read). aMSa's 2022 matchup chart is known here only from a news summary.

## 1. The rules we play under

stomped ([docs](https://docs.stomped.dev/llms-full.txt)): 1v1, 4 stocks, 8 minutes, no items, no UCF or other gameplay codes, blind character pick. The stage is drawn at random from the six legal ones before the pick, with no bans. When the timer runs out, more stocks wins, then the lower percent; there is no sudden death.

Who we meet there, from the 95 games in our log that ended on stocks or time (2026-11-16 and 17):

| Opponent's character | Bots | Our record with HAL as aMSa |
|---|---|---|
| Fox | filbot, ligma, Lotor, entropy | 10 of 47 (all 10 against entropy) |
| Falco | bingbong | 11 of 14 |
| Jigglypuff | hello-melee | 12 of 13 |
| Captain Falcon | swaggy c | 0 of 12 |
| Marth | baby | 7 of 9 |

Fox is half of the games. The top of the ladder is nescio's four bots, named for Fox, Falco, Marth and Falcon, which are not in this table.

## 2. The character

- **Physics:** weight 108, fall speed 1.93 (2.93 fast-falling), air speed 1.2, 5-frame jumpsquat, long wavedash.
- **Double-jump armour.** The double jump subtracts 120 from the knockback of anything that hits Yoshi during its 70 frames, and ends when the jump is cancelled. It is active from frame 1 in the air and from frame 8 off the ground. It does not wear down per hit; it fails at higher percent because knockback grows. Verified break points: Marth's down-air at 82%, Sheik's back-air at 70%, Puff's offstage hits from about 60%; Falco's shine breaks it at 0%; Falcon's stomp usually beats it.
- **Shield.** No jump out of shield, no shield stun, cannot be shield-poked, 16 frames to drop it.
- **Parry.** The first 6 frames of shield are invincible and can be jump-cancelled on frames 2 to 6. The attacker freezes in hitlag and Yoshi does not. In practice the window is about 2 frames, wider when crouching first.
- **Recovery.** There is no up-B, so losing the double jump offstage usually means losing the stock. Low recoveries survive through armour until it breaks.
- **What kills him early:** hits that eat the jump offstage (Sheik's needles, Puff at the ledge, Peach's float), Falcon's grab combos, Sheik's chain grab (true from 0 to about 55%), Fox's drill into shine and up-throw up-air.

Frame data used below (hit frame or startup; landing lag normal / L-cancelled):

| Move | Hits on | Notes |
|---|---|---|
| Neutral air | 3 | landing lag 15 / 7 |
| Up air | 5 | landing lag 19 / 9 |
| Forward air | 19–21 | meteor; landing lag 21 / 10 |
| Down air | 18 | autocancels before frame 15 |
| Down smash | 6–8 (front) | 49 frames in all; sends low and out |
| Up smash | 11–15 | head intangible |
| Egg lay (neutral B) | grabs from 17 | |
| Egg throw (up B) | egg leaves on 18 | 12%, flies 55 frames |
| Grab | 18 standing, 11 dashing | |

## 3. The techniques

| Technique | What it does | Needs a fast reaction? |
|---|---|---|
| Double-jump cancel aerials | Cancelling the double jump with an aerial: faster and more adjustable than short-hop aerials. The base of his combos and pressure | No |
| Armour trade | Take a hit below the threshold and hit back with neutral air or up air | Works as a read or by jumping early |
| Parry | Turns pressure that is safe on shield into a punish | Yes, except against slow, multi-hit or rhythmic moves |
| Double-jump land | Lands on a platform with no landing lag, armoured until it can act | No (2-frame window on the rising version) |
| Egg throw | Covers recoveries, fills combos, stalls at the ledge | No |
| Down tilt, down smash | Down tilt opens at low percent and edgeguards from the ledge; down smash ends combos low and offstage | No |
| Crouch cancel | Into down smash or tilts; the standard answer to Marth's up-B | No |
| Tech chase | Wavedash to the landing spot, jab a missed tech, grab a roll | About 20 frames to decide |
| Shield-drop punishes | Among the best in the game because he has no shield stun | Yes |

## 4. aMSa

- **Style:** technical and punish-heavy, built on double-jump cancels and parries. At the ledge he baits with egg stalls and ledgedashes. Known for platform movement and for aiming eggs and forward airs precisely. He keeps his own chart of kill percents.
- **Armour as tempo:** he trades through hits to keep stage control, and grabs the ledge off an egg throw to force opponents to recover high.
- **Where he struggles:** patient players who neutralise eggs, and Falcon and Sheik.
- **2022, when he won The Big House 10 without dropping a set:** he had moved to Canada for North American events and online practice, prepared specifically for Puff, and credits composure. Reporting describes him betting on his punish game, including taking Fox to Final Destination. We found no interview that lists technique changes.

## 5. Matchups

**Ratings.** aMSa's December 2022 chart has Fox, Falcon, Sheik and Peach as losing and Marth, Falco and Puff as even or better (from a news summary). Older community numbers are worse across the board.

**Fox**
- Open with wavedash down tilt and egg lay at low percent; add up air from 18% and neutral air from 23%.
- Up-air chains into down smash between 40 and 80%; above 80% play for a neutral air offstage. Up-throw up-air kills from about 140% on Final Destination.
- Armour through his short-hop drill and neutral air. Up air under a full-hop drill.
- Edgeguard by zone: grab the ledge off an egg throw, trade neutral air with Firefox, forward air on his side-B.
- He wins with drill into shine, run-and-gun, and down tilt on ledge stalls.

**Captain Falcon**
- Get close and get a knockdown. Armour his neutral air, back air his stomp, fade-back forward air against run-up grab.
- Push him offstage with an early down smash. Edgeguards decide the matchup.
- Below 30% his throw follow-ups are not guaranteed if Yoshi holds away and jumps.

**Falco**
- Parry or armour every committed aerial; tilt lasers thrown from too close.
- Punish as against Fox, a few percent later. His shine always breaks armour, so avoid being shined offstage.

**Marth**
- Read his aerial with armour or a parry, depending on the kind of hop. Egg lay or back air his landings.
- Down throw into forward air is guaranteed unless he holds away. Up airs end in a forward air.
- Crouch at the ledge and down smash his up-B (works from 20 to 147%).

**Jigglypuff**
- Never contest her back-air wall. Stay just outside it and hit her landing or her double jump. Get above her.
- Rest kills Yoshi mid-stage at 19% on Yoshi's Story, 25% on Battlefield, 33% on Dream Land. Never armour into her while recovering.
- Yoshi does well in timeouts against her: eggs hold a lead.

**Sheik** and **Peach** (not on stomped yet)
- Sheik: offstage is the win condition; do not get grabbed; do not shield on platforms.
- Peach: short combos ending in one hard hit, then eggs while she lands; never jump into her on a platform.

**Stages.** Final Destination is the worst for Yoshi (no platform movement, no shield drops), and stomped draws it one game in six. Yoshi's Story gives early down-smash kills and early deaths alike. Dream Land delays Puff's and Peach's kills.

## 6. What this means for a delayed bot

*Inference from the frame data above.*

- **No UCF costs a bot nothing.** UCF widens input windows for human hands. A bot sends exact stick values.
- **A percent lead is a full win.** With no sudden death, holding a lead to the timer is a real plan, and Yoshi's weight, armour and eggs suit it. Risky against Fox at the ledge.
- **Survives 10 frames of delay:** double-jump cancel combos by percent, down-smash enders, all egg work, ledge stalls, crouch-cancel edgeguards, double-jump lands, the zone edgeguard on Fox. Tech chasing too: its decisions take about 20 frames.
- **Survives as prediction:** armour. It lasts 70 frames, so the bot can jump 10 frames early into an aerial it expects. Armouring at the last possible moment does not survive, so expect to take more damage per trade than aMSa.
- **Mostly lost:** 2-frame parries against fast or mixed timings, and shield-drop punishes. Parry remains against committed falling aerials, Firefox and laser rhythm.

## 7. What we can measure

Computable from game frames, to compare a bot with aMSa's own games:

- share of aerials that are double-jump cancelled; double-jump lands per minute
- armour trades per minute, and the damage dealt and taken in each
- parries per minute, and how often a punish follows
- eggs per minute, their hit rate, and the share thrown from the ledge
- share of combos that end in down smash or offstage
- edgeguard conversion rate
- deaths with the double jump unused, and deaths below the stage
- grabs taken per game
- openings per kill, damage per opening, and kill percent, by matchup and stage
- games won on a percent lead at the timer

The only published benchmark we found is generic: top players need about 2 to 3 openings per kill.

## Sources

- The Yoshi Guide (Sashimi and Daniel): https://www.theyoshiguide.com/ (mechanics pages for armour, double-jump cancel, parry, shield, eggs, edgeguarding and tech chasing; one section per matchup)
- SmashWiki: [Yoshi (SSBM)](https://www.ssbwiki.com/Yoshi_(SSBM)), [Parry (Yoshi)](https://www.ssbwiki.com/Parry_(Yoshi)), [aMSa](https://www.ssbwiki.com/Smasher:AMSa), [Final Destination](https://www.ssbwiki.com/Final_Destination_(SSBM))
- Dignitas, "Analyzing Yoshi's competitive viability": https://dignitas.gg/articles/analyzing-yoshis-competitive-viability
- Upcomer: [three techniques that make aMSa's Yoshi deadly](https://www.upcomer.com/three-techniques-that-make-amsas-yoshi-so-deadly-in-smash/), [aMSa wins The Big House 10](https://upcomer.com/amsa-makes-melee-history-with-the-big-house-10-win/)
- Red Bull, "aMSa, player to watch": https://www.redbull.com/ca-en/amsa-smash-melee-player-to-watch
- EventHubs on aMSa's matchup chart: https://www.eventhubs.com/news/2022/dec/23/amsa-yoshi-matchup-melee-tier/
- Smashboards: [knockback values](https://smashboards.com/threads/melee-knockback-values.334245/), [UCF guide](https://smashboards.com/guides/universal-controller-fix-ucf.1283/), [edgeguarding Captain Falcon](https://smashboards.com/threads/edgeguarding-captain-falcon.398459)
- Generic punish benchmarks: https://ssbmstats.com/metrics
