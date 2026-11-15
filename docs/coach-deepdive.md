# Coach deep-dive: why coaching Reyn helps, and why Jev coaches best

As of 2026-11-14 (wrapped up at 15:10 with 183 ablation games; no further runs planned). Real-time track, Fox ditto on Battlefield and Final Destination, Elo relative to CPU 9 = 1500, ± the 95% half-width.

Ratings on this page are from the joint fit of the main bench's games and the ablation games ([table](#ablation-results)). The bench-only fit, shown on the Bench page and in [status.md](status.md), differs by a few points.

## Answer

**Reyn needs a command, and the best one is "Don't die."; the coach matters less than that.**

**Follow-up, 2026-11-15.** The numbers below are from the deep-dive's own games. Afterwards the four LLM coaches and the random coach played 300 direct games against each other (24.6M CLIProxy tokens, all rated). Against the random coach, Sonnet 5.5 went 29-7, Haiku 4.5 28-9 and GPT-6 Luna 30-15 (all games between each pair, older ones included; the 95% intervals on those win rates exclude 50%), and GPT-6.1 Sol 15-20. On the board the first three are at 2303-2324, level with each other, the random coach at 2141 ±100 and Sol at 2130. So three LLM coaches do beat random, by about 170 Elo; Sol, the slowest at 3.1 s a call, does not. The order matches the "implied value per window" below (Haiku and Sonnet above Luna, Sol at random's level).

1. **Most of the gain is having any command at all.** Reyn with no command rates 1746. One random command held all game reaches 2018, and a random coach switching every 5 s only 2068, within noise of it. So the gain is not the perturbation of changing commands.
2. **Holding "Don't die." all game, with no coach, rates 2398**: level with the Jev coach (2346) and above every LLM coach (2132-2259).
3. **Jev coaches best because it ends up holding "Don't die."** 41% of the time, mostly through a router accident (its "kill now" pick is routed to "Don't die."). The LLM coaches pick sensible-sounding commands (edgeguard, aggressive play) that are worth less.
4. **Interval, computed features and the menu don't measurably matter** at ~25 games per variant: all those variants are within ±175 of each other.

To make a stronger coached Reyn, start from "Don't die." as the default and switch away only for a clear reason, and fix the router's `kill_now` mapping (or keep it, knowingly).

## The questions

On the bench, a random coach lifted Reyn by about 320 Elo, the four LLM coaches did not clearly beat it, and the Jev coach did. So:

1. Why does any coaching help, even random? Is it the perturbation of changing commands, or specific commands?
2. Why does Jev beat random when the LLM coaches don't clearly do so?
3. What matters: the interval, the command menu, extra features, model speed, consistency?

## Method

**Log mining** (`uv run python scripts/coach_deepdive.py logs|windows|games`) over every bench coach game's `<replay>.p<port>.coach.jsonl` (format in [coach.md](coach.md#design)).

- The *effective* command is the one Reyn's router holds after each call (an abstained phrase keeps the previous command).
- A *window* is the span between two calls (5 s at `interval=300`). Its outcome is the change in percent and stocks.
- The random coach assigns commands at random, so its windows are a randomised experiment: the effect of a command on the next 5 s is causal there, if noisy (about 25 windows per command).

**Ablations** (`bench run --out data/bench-deepdive --context data/bench/results.jsonl --only ...`). New entrants in `entrants.ablations()` (inactive in the main bench) played under the bench rules (`realtime` mode on :98, ports 52000-52099, games under 50 fps not rated) against the same anchors, and the main bench's games join the fit as context, so the ratings are on the same scale. `scripts/coach_deepdive.py ablations data/bench-deepdive/results.jsonl` refits everything and prints each entrant's difference from the random coach and from the Jev coach. Those differences have tighter intervals than the per-entrant ±, because shared anchor uncertainty cancels.

New coach options (`melee_llm/agents/coach.py`): `p_change` (random coach keeps its command with probability 1 − p; 0 = one random command all game), `menu=id|id` (restrict the menu), `features=1` (named features computed in code).

## What the coaches do (log mining, 392 bench coach games)

| Coach | Games | Change rate | Effective change rate | Router abstains | Time with no command | Distinct commands / game | Latency |
|---|---|---|---|---|---|---|---|
| Random | 106 | 99% | 94% | 4.8% | 1% | 20 | 0 |
| Jev | 72 | 39% | 24% | 12.8% | 11% | 4.2 | 0.17 s (11 frames) |
| Haiku 4.5 | 50 | 58% | 56% | 0.9% | 2% | 6.4 | 1.3 s (76 f) |
| Sonnet 5.5 | 43 | 59% | 60% | 1.9% | 10% | 8.5 | 2.2 s (133 f); 22% of replies unparseable (= keep) |
| GPT-6 Luna | 50 | 24% | 22% | 7.7% | 10% | 4.4 | 1.7 s (103 f) |
| GPT-6.1 Sol | 71 | 27% | 28% | 0.6% | **42%** | 4.4 | 3.1 s (185 f) |

*Change rate* is the share of calls that set a new command; *effective* counts changes of the command Reyn actually holds.

What they hold (share of calls, effective command):

- **Jev:** "Don't die." 41%, edgeguard from the stage 14%, nothing 10%, defensive 9%, left side 7%, landing punish 7%.
- **Haiku:** edgeguard from the stage 33%, aggressive play 23%, ledgedash 12%, low recovery 11%.
- **Sonnet:** edgeguard 27%, "Don't die." 12%, low recovery 12%, aggressive 10%, nothing 10%.
- **Luna:** low recovery 31%, edgeguard 28%, nothing 10%, centre of the stage 7%.
- **Sol:** nothing 44%, whiff punish 17%, centre of the stage 16%.

**Jev's favourite command is a router accident.** Jev's most chosen id is `kill_now` (21% of calls), whose phrase "Cause your opponent to lose a stock." Reyn's router maps to **Stock protection** ("Don't die.") every time (160 of 160 accepted sends; 200 across all coaches). With its explicit `stock_protection` picks (18%), Jev holds "Don't die." 41% of the time. Its other frequent pick, `approach`, is always abstained by the router (160 of 160), as are `holding_position`, `ground_play` and `far_spacing`, so those picks act as "keep".

**Command effects, from the random coach's randomised windows** (net damage = % dealt − % taken in the next ~5 s; random-coach mean +8.3, n = 2,595 windows; ± is the 95% interval):

- Best: "Don't die." +25 ±12 (n = 52), punish landing +19 ±13, edgeguard from the stage +19 ±15, ledgedash +17 ±12. By menu section, Play style +18 ±6 is best.
- Worst: "Don't start any attacks." −19 ±6, the half-second-pause rule −15 ±10, down tilt −11 ±17; by section, Fox techniques +1 ±4 and Attacks +4 ±3.
- No command at all: +7.5 ±10 (n = 35), about average.

**A coach's mix predicts its rating.** Weighting each coach's held commands by those effects (shrunk toward the mean) gives an implied value per window of Jev +14.2, Haiku +11.9, Sonnet +11.7, Luna +10.2, Sol +9.4, random +8.2. That is the bench order except Luna vs Haiku/Sonnet, which are within noise of each other on the board too.

**Game-level associations are flat.** The result relative to the Elo expectation does not depend on change rate (low half +0.06 ±0.05, high half −0.04 ±0.05), time with no command or distinct commands. Windows right after a change do worse than held windows, but that is selection (coaches change when losing).

**Head to head**, Jev beat the LLM coaches 25-3 (Haiku 8-0, Sonnet 6-0, Luna 8-1, Sol 3-2) and the random coach 9-2; the random coach beat uncoached Reyn 9-0.

## Ablation results

183 games (133 rated, 47 ran under 50 fps on a loaded machine and were not rated, 3 errors), fitted jointly with the main bench's games. ± is the 95% Laplace interval; the last two columns are differences from the random coach and the Jev coach.

| Entrant | Elo | ± | Games (new) | vs random | vs Jev |
|---|---|---|---|---|---|
| Reyn, fixed "Don't die." | 2398 | 165 | 32 (32) | +330 ±168 | +52 ±164 |
| Jev coach (5 s) | 2346 | 126 | 79 (5) | +278 ±122 | 0 |
| Jev coach, 1 s | 2278 | 177 | 26 (26) | +210 ±173 | −67 ±176 |
| GPT-6 Luna coach | 2259 | 138 | 50 | +191 ±133 | −86 ±128 |
| Sonnet 5.5 coach | 2238 | 143 | 43 | +170 ±140 | −108 ±137 |
| Haiku 4.5 coach | 2236 | 139 | 50 | +167 ±135 | −110 ±132 |
| Jev coach + features | 2189 | 179 | 25 (25) | +121 ±172 | −157 ±186 |
| Haiku coach + features | 2183 | 208 | 15 (15) | +115 ±203 | −163 ±207 |
| Random coach, Jev's top 6 | 2169 | 182 | 23 (23) | +101 ±178 | −176 ±189 |
| Jev coach, 15 s | 2154 | 177 | 24 (24) | +85 ±173 | −192 ±184 |
| GPT-6.1 Sol coach | 2132 | 128 | 71 | +64 ±128 | −213 ±135 |
| Random coach | 2068 | 111 | 122 (16) | 0 | −278 ±122 |
| Random coach, one command | 2018 | 178 | 23 (23) | −50 ±174 | −328 ±188 |
| Random coach, sticky (p_change 0.25) | 2003 | 182 | 22 (22) | −65 ±181 | −342 ±192 |
| Reyn, no command | 1746 | 106 | 103 (10) | −322 ±131 | −600 ±143 |

Anchors in the same fit: Phillip gm 2488, HAL MASTER 2234, Phillip plat 1945, MIMIC 1919. MIMIC was dropped from the run partway (too slow to rate under load). No ablation game reached the 8-minute timer, so the Sudden Death scoring fix (PR #5, deployed mid-run) changed no result.

**Limits.** ~25 games per variant leaves ±175: enough to see that "Don't die." and Jev are well above random and that fixed/sticky random are not better than switching, not enough to rank interval or feature variants. The window analysis is short-horizon (5 s) and the bench is whole games; they agree on "Don't die." being best.
