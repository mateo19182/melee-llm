# Acting under delay

How reinforcement learning and Melee bots deal with a gap between seeing the game and acting on it, and what that means for our Yoshi. Compiled on 2026-11-17 from papers, HAL's write-up, slippi-ai's code and our own experiments. **[ours]** marks our measurements and inferences; the rest is linked.

## 1. The problem

- A bot with delay d picks, at frame t, the action that the game will read at frame t + d + 1. It does not know what the game will look like by then.
- **Action delay and observation delay are the same problem.** Acting d frames late on a fresh view is equivalent to acting at once on a view that is d frames old, and when both are present they add up (Katsikopoulos & Engelbrecht 2003, restated in [Liotet's thesis](https://arxiv.org/abs/2309.11096)). So "lead 11 on stomped", "10 frames of input delay" and "the bot sees the game 10 frames late" describe one task.
- **Where our delay comes from.** stomped's round trip from this server is about 135 ms, so a pad has to be sent 11 frames ahead ([bots.md](bots.md)). Humans sit at 12 to 15 frames of reaction time or more; [Firoiu](https://arxiv.org/abs/1810.07286) calls 12 the lowest plausible.
- **Why Melee is harsh under delay.** The state has discrete parts (each character is in one of several hundred animation states) that change what the right action is, and hits are discontinuous in position: a spacing that is right for one state whiffs or gets punished in the next (Firoiu 2018, §3.4).

## 2. What the theory says

**The delayed problem is an ordinary one on a bigger state.** The last state seen plus the d actions already sent is everything the agent can know, and an optimal policy on that "augmented state" is optimal for the delayed task (Walsh et al. 2008, "Learning and planning in environments with delayed feedback"; [Nath et al. 2021](https://arxiv.org/abs/2108.07555)). The state space grows by a factor of |A|^d, which is why learning gets slower and worse as d grows, not impossible.

Four families of methods follow from this:

| Family | Idea | Known for | Weakness |
|---|---|---|---|
| Augmented state, model-free | Feed the pending actions (or a memory that has seen them) and run ordinary RL | Phillip today; [DCAC](https://arxiv.org/abs/2010.02966) for random delays | Slow; value learning degrades with d |
| Predict the present | A learned model rolls the old state forward through the pending actions; the policy acts on the prediction | Walsh 2008, [Firoiu 2018](https://arxiv.org/abs/1810.07286), [DFBT 2025](https://proceedings.mlr.press/v267/wu25ag.html), [DT-CORL 2026](https://arxiv.org/abs/2506.00131) | Model errors compound; the opponent is unpredictable |
| Imitate an undelayed expert | Play with delay, and label every step with what a no-delay expert would do in the true present state (DAgger) | [DIDA, Liotet et al. 2022](https://proceedings.mlr.press/v162/liotet22a.html) | Learns the expert averaged over what might be happening, not the best delayed policy |
| Shorter delays as a ladder | Learn at a short delay and bootstrap the long one from it | [AD-RL, Wu et al. 2024](https://arxiv.org/abs/2402.03141); [VDPO](https://arxiv.org/abs/2405.14226) | More machinery |

Details that matter when implementing any of them:

- **Credit.** The action chosen at t does nothing until t + d, so it is reinforced with the return from t + d on, not from t (Firoiu 2018 §4.4; slippi-ai does `advantages[skip_delay:]`).
- **The critic may cheat.** The value function is only used in training, where the true present state is known, so it can be given that state even though the policy cannot (Firoiu 2018 §4.4; slippi-ai's value function pairs state t with the action applied at t).
- **DIDA's bound.** The gap between the delayed imitator and the undelayed expert grows linearly with d and with how sharply the expert's action changes with the state. A twitchy, reaction-heavy expert is a poor teacher for a delayed student.
- **DIDA's schedule.** First batch from the expert, every later batch from the learner, all labelled by the expert; retrain on the aggregate. It converged several times faster than delayed RL baselines on control tasks at 5 steps of delay, but stayed well below the expert on the harder ones.
- **Random delay.** Networks jitter. The standard answers are to train over a range of delays with the pending actions as input, and to pin the delay at serving time to one the model was trained at ([ExPhil](research.md#exphil-blasphemetheus-2026)).

## 3. What Melee bots do

**Firoiu, Ju & Tenenbaum 2018, "At Human Speed"** ([paper](https://arxiv.org/abs/1810.07286)):
- A queue of d actions between agent and game, and the queue given to the agent as input.
- Plain IMPALA lost most of its performance as delay grew, in Melee and in five of six Atari games.
- Adding a learned model that predicts the present state helped only when it predicted all d steps, and only showed against learning opponents: against the built-in CPU the plain agent was as good.
- Best result: 6 and 7 steps of delay (about 12 to 14 frames with their frame skip), 3 wins to 5 and 2 to 5 against a top-50 professional; the agent without the model went 0 to 6.
- V-trace off-policy correction mattered. The model made the policy more sensitive to parameter changes.

**slippi-ai (Phillip) today** (code in `vendor/slippi-ai`, commit `5ada33e`):
- No predictive model any more. One alignment rule everywhere: at step t the network sees state t and the last action it committed (for t + D) and predicts the action for t + D + 1 (`slippi_ai/data.py:267-327`). Earlier pending actions reach it through its recurrent memory.
- Stage 1, imitation at that alignment, with D = 18 or 21. The README calls the result "ok, but makes a lot of mistakes".
- Stage 2, PPO in Dolphin with the delay as a queue on the agent's output. Advantages are shifted by the delay; the value function sees the undelayed pairing (`slippi_ai/jax/rl/learner.py:285-350, 600-699`).
- **A KL penalty toward the frozen imitation policy** is in every RL launch (weight 0.01 in both directions in `launch_rl.py`, 0.1 as the config default). The teacher is trained at the same delay.
- Opponents: the CPU, a frozen or live copy of itself, or other agents trained alongside. No rating-based league.
- Fairness extras: the opponent's tech direction is hidden for the first 4 to 7 frames.

**HAL** ([write-up](https://ericyuegu.com/hillclimbing-melee/), code in `vendor/hal`):
- No delay in training at all. The model predicts a chunk of future actions; at play time the first d are forced to the actions already sent and the rest are sampled ("real-time chunking", from robotics: [Black et al. 2025](https://arxiv.org/abs/2506.07339), with a [training-time variant](https://arxiv.org/abs/2512.05964) that beats it at larger delays).
- Gu: "The model works well with observation delay despite not explicitly being trained for it", and also "the cost of observation delay is high": each frame of delay costs about twice as much as a frame of open-loop execution, and his larger models lost more to slower reactions than they gained in capacity.
- The 2200-rating ladder run used 3 frames of delay. Against Phillip, HAL won 94.8% against the imitation-only agent and 25% against the RL agent.

**ExPhil** ([notes](research.md#exphil-blasphemetheus-2026)): random 0 to 18 frames of delay in training with the action queue as input, one checkpoint served at several delays; then PPO on the imitation prior with a KL penalty, and a "style fingerprint" to catch degenerate strategies RL finds.

## 4. Our measurements [ours]

| Experiment | Finding |
|---|---|
| [E16](experiments/E16-hal-delay.md) | HAL as aMSa drops from about 400 to 90–180 with 3 to 10 frames of delay |
| [E18](experiments/E18-league-opponents.md) | Phillip's Yoshi, trained with RL at 18 frames, rates 688; ours with no delay 402 |
| [E22](experiments/E22-hal-delay-offsets.md) | At 10 frames HAL wins 10 of 30 where it wins 23 with none. Giving its far-ahead outputs more weight in an imitation fine-tune changed nothing (8 of 30); they already imitated as well as the near ones |

## 5. What this means for us [ours]

1. **Imitation at the right alignment is necessary and we have it.** HAL's far-ahead outputs are the same thing as Phillip's stage 1, and E22 shows there is nothing left to gain there.
2. **The gap between "ok" and strong under delay is on-policy learning.** In Gu's test Phillip's imitation agent lost to HAL 5 to 95 and its RL agent won 75 to 25 (he does not state the delays; Phillip's releases play at 18 or more). Every strong delayed Melee agent got there by playing with the delay and learning from the result.
3. **Stay close to the human prior.** Both projects that do RL on an imitation policy keep a penalty toward it, and ExPhil documents the degenerate strategies RL finds even with one.
4. **Skip the predictive model.** It helped a 2018 recurrent agent trained from scratch; slippi-ai dropped it, and a 256-frame transformer that is fed its own pending actions already has what it needs to form that prediction internally.
5. **Train at the delay we serve, and across a small range around it.** stomped's pads land one frame late in regular stretches, so 10 is really 10 to 11.
6. **Give the value function the present.** Cheap, standard, and it removes delay from the half of the problem that does not need it.

Three ways to do the on-policy part with HAL's model, all needing the same pipeline (play games with delay, convert the replays to HAL's training format):

| Route | Training signal | For | Against |
|---|---|---|---|
| A. Imitate the no-delay model (DIDA) | Every frame of our delayed games, labelled with what the released model would do seeing the present | A label on every frame, so the fewest games; no reward or value needed; a clear ceiling (no-delay strength, 410) | Aims at "react like the no-delay bot", which delay makes partly impossible; cannot exceed the teacher |
| B. Advantage-weighted on own games | HAL's own loss on our delayed games: copy what we did, weighted by how well it went | No new loss code; can in principle exceed the teacher; same code serves no-delay improvement | Weak signal per game; only as good as the variety in our own play |
| C. PPO with a penalty toward the released model | Phillip's recipe | The method with a track record at 18 frames | Needs far more games than Dolphin gives us at real-time speed; most new code |

Recommended order: A, then B on top of A's result, with C held until we know our games-per-hour. Judge every model at 10 frames and at none, against the E18 yardstick.
