# Coach deep-dive: why coaching Reyn helps, and why Jev coaches best

As of 2026-11-14. Real-time track, Fox ditto on Battlefield and Final Destination, Elo relative to CPU 9 = 1500, ± the 95% half-width.

## The questions

The final bench put uncoached Reyn at 1765 ±110, the random coach at 2096 ±122, the four LLM coaches at 2147-2275 (±130-145) and the Jev coach at 2371 ±132. So:

1. Why does any coaching help, even random? Is it the perturbation of changing commands, or specific commands?
2. Why does Jev beat random when the LLM coaches don't clearly do so?
3. What matters: the interval, the command menu, extra features, model speed, consistency?

## Method

**Log mining** (`uv run python scripts/coach_deepdive.py logs|windows|games`). Every bench coach game writes `<replay>.p<port>.coach.jsonl`: one record per call with the state text, the chosen command, whether it changed, the latency, and Reyn's router reply. The *effective* command is the router's row after each call (an abstained phrase keeps the previous command). A *window* is the span between two calls (5 s at `interval=300`); its outcome is the change in percent and stocks between the two states the coach saw. The random coach assigns commands at random, so its windows are a randomised experiment: the command → next-5-s outcome association there is causal, if noisy (about 25 windows per command).

**Ablations** (`bench run --out data/bench-deepdive --context data/bench/results.jsonl --only ...`). New entrants in `entrants.ablations()` (inactive in the main bench) were played by the bench scheduler under the bench rules (`realtime` mode on :98, ports 52000-52099, games under 50 fps not rated), against the same anchors (HAL, Phillip gm/plat, MIMIC, Reyn, the random and Jev coaches, Haiku coach). The main bench's games join the fit as context, so the new ratings are on the same scale. `scripts/coach_deepdive.py ablations data/bench-deepdive/results.jsonl` refits everything and prints each entrant's difference from the random coach and from the Jev coach, with a Laplace 95% interval from the joint fit (shared anchor uncertainty cancels, so these are tighter than the per-entrant ±).

New coach options used (`melee_llm/agents/coach.py`): `p_change` (random coach keeps its command with probability 1 − p; 0 = one random command all game), `menu=id|id` (restrict the menu), `features=1` (named features computed in code, below).

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

**Jev's favourite command is a router accident.** Jev's most chosen id is `kill_now` (21% of calls), whose phrase "Cause your opponent to lose a stock." Reyn's router maps to **Stock protection** ("Don't die.") every time (160 of 160 accepted sends; 200 across all coaches). With its explicit `stock_protection` picks (18%), Jev holds "Don't die." 41% of the time. Its other frequent pick, `approach`, is always abstained by the router (160 of 160), as are `holding_position`, `ground_play` and `far_spacing`, so those picks act as "keep". The command menu says one thing; Reyn does another.

**Command effects, from the random coach's randomised windows** (net damage = % dealt − % taken in the next ~5 s; random-coach mean +8.3, n = 2,595 windows; ± is the 95% interval):

- Best: "Don't die." +25 ±12 (n = 52), punish landing +19 ±13, edgeguard from the stage +19 ±15, ledgedash +17 ±12. By menu section, Play style +18 ±6 is best.
- Worst: "Don't start any attacks." −19 ±6, the half-second-pause rule −15 ±10, down tilt −11 ±17; by section, Fox techniques +1 ±4 and Attacks +4 ±3.
- No command at all: +7.5 ±10 (n = 35), about average. So inside random-coach games, an empty command is not worse than a random one over the next 5 s.

**A coach's mix predicts its rating.** Weighting each coach's held commands by those random-window effects (shrunk toward the mean) gives an implied value per window of Jev +14.2, Haiku +11.9, Sonnet +11.7, Luna +10.2, Sol +9.4, random +8.2. That is the bench order except Luna vs Haiku/Sonnet, which are within noise of each other on the board too. The LLM coaches pick sensible commands (edgeguard, punish landing, aggressive); Jev mostly holds the single best one.

**Game-level associations are flat.** Across coach games, the result relative to the Elo expectation does not depend on change rate (low half +0.06 ±0.05, high half −0.04 ±0.05), time with no command or distinct commands. Windows right after a change do worse than held windows for every LLM and Jev, but that is selection (coaches change when losing).

**Head to head**, Jev's edge is clearest: Jev beat the LLM coaches 25-3 (Haiku 8-0, Sonnet 6-0, Luna 8-1, Sol 3-2) and the random coach 9-2; the random coach beat uncoached Reyn 9-0. On the fitted scale Jev is +273 ±130 over random; the LLM coaches are +49 to +177 (±132-145) over random and −96 to −224 (±130-138) under Jev (Laplace intervals on the difference).
