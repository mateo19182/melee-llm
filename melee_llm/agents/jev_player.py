"""Jev players: TypeSafe's System One model picks the next macro instead of an LLM. See docs/jev.md.

Same executor, state rendering, history, reflexes and JSONL log as the LLM players (they subclass them); only
`think` changes. One request per decision: the rendered state, plus typed questions asked in parallel ("speculative
fan-out"): `action`, a Choice over every macro, and one question per macro parameter (dir, jump, throw, then,
ledge, frames as buckets, fastfall as a Noul). Only the parameters the chosen action takes are used. Jev has no free
text, so `reason` holds the action's probability, and the log carries the top-k probabilities of every question.

match.py specs: jev_live[:<model>][,interval=15,max_stale=60,top_k=5,params=all|none,shuffle=1,timeout=1.5]
                jev_paused[:<model>][,interval=30,...]
"""
from __future__ import annotations

import random
from types import SimpleNamespace

import melee

from melee_llm import jev as J
from melee_llm.actions import ACTIONS, DIRS, SCHEMA_FIELDS
from melee_llm.agents.llm_common import TIPS, DecisionLog, parse_spec
from melee_llm.agents.llm_live import LiveLLM
from melee_llm.agents.llm_paused import PausedLLM
from melee_llm.llm import Reply
from melee_llm.state import stage_text

# Per-macro meanings for the Choice criteria. Jev reads options literally and can't see the shared ACTIONS
# descriptions as distinct, so each move says what it is for. Missing names fall back to ACTIONS[name].desc.
ACTION_TEXT = {
    "wait": "stand still and do nothing",
    "approach": "dash toward the opponent to get close",
    "retreat": "run away from the opponent to make space",
    "dash_dance": "dash back and forth in place to bait the opponent and react",
    "crouch": "crouch to absorb a weak hit at low percent",
    "drop_platform": "fall through the platform you stand on",
    "short_hop": "small jump, to get in the air or dodge something low",
    "full_hop": "high jump, or double jump when already airborne",
    "wavedash": "slide quickly along the ground to reposition",
    "nair": "neutral air: spinning kick around you, safe combo starter in the air",
    "fair": "forward air: attack in front of you while airborne",
    "bair": "back air: strong kick behind you, kills at high percent",
    "uair": "up air: attack above you, juggles and kills an opponent above",
    "dair": "down air: attack below you, spikes or combos an opponent below",
    "jab": "jab: fastest grounded hit, opponent very close in front",
    "ftilt": "forward tilt: quick grounded kick, opponent close in front",
    "utilt": "up tilt: grounded hit above you, starts juggles",
    "dtilt": "down tilt: low grounded poke",
    "fsmash": "forward smash: slow strong grounded hit that kills at high percent",
    "usmash": "up smash: strong hit above you, kills at high percent",
    "dsmash": "down smash: hits both sides on the ground, opponent close and low",
    "dash_attack": "run in and attack, opponent at mid range on the ground",
    "grab": "grab and throw, beats a shielding or idle opponent close by",
    "shine": "Fox/Falco shine (down-B): instant hit when the opponent is touching you, also escapes pressure",
    "laser": "Fox/Falco laser (neutral-B): shoot from far away to chip damage",
    "side_b": "side special: fast horizontal dash, mainly to recover from offstage",
    "up_b": "up special aimed at the ledge, to recover from below the stage",
    "recover": "get back to the stage when offstage",
    "shield": "hold shield to block an incoming attack",
    "roll": "roll out of shield to escape pressure",
    "spot_dodge": "dodge in place, beats a grab or a hit about to land",
    "ledge": "act from the ledge while hanging on it (get up, roll, jump, attack or drop)",
    "tech": "tech when landing after being hit",
}
DIR_TEXT = {"toward": "toward the opponent", "away": "away from the opponent", "left": "to the left",
            "right": "to the right", "center": "toward the stage center", "in_place": "stay in place"}
PARAM_TEXT = {
    "jump": ("For an aerial started from the ground: which jump?",
             {"short": "short hop, low and fast", "full": "full jump, high", "double": "double jump", "none": "no jump"}),
    "throw": ("After grabbing, which throw?",
              {"f": "forward throw", "b": "back throw, toward the edge behind", "u": "up throw, to juggle",
               "d": "down throw, to combo"}),
    "then": ("After a grounded shine, what next?",
             {"jump": "jump out of it to combo", "wavedash": "waveshine to keep pressure", "hold": "keep shining"}),
    "ledge": ("When hanging on the ledge, which ledge option?",
              {"getup": "normal getup onto the stage", "roll": "roll onto the stage past the opponent",
               "jump": "jump up from the ledge", "attack": "getup attack", "drop": "let go and drop"}),
}
FRAMES = {"brief": 10, "medium": 25, "long": 50}
FRAMES_TEXT = {"brief": "about 1/6 second, then decide again", "medium": "about half a second",
               "long": "almost a second"}
GUIDE = ("Super Smash Bros. Melee. You are the player marked YOU; OPP is the opponent. x grows right, y grows up, "
         "floor y=0, 60 frames = 1 second; distance under 20 is melee range, under 35 close. Win by taking stocks: "
         "damage raises percent, higher percent means more knockback. ACTIVE = an attack hitbox is out now; startup/endlag "
         "= vulnerable windows to punish; busy = cannot act yet; hitstun = combo them; OFFSTAGE = edgeguard them or "
         "recover yourself. Punish endlag; shield or retreat when an ACTIVE attack is in range; grab shielding opponents; "
         "don't repeat a failing approach; at high percent go for KO moves.")


class JevBrain:
    """Mixin over LiveLLM / PausedLLM: replaces the LLM call with one Jev request."""
    kind = "jev"

    def __init__(self, spec: str | None = None, *, top_k: int = 5, params: str = "all", shuffle: bool = True,
                 timeout: float = 1.5, retries: int = 1, seed: int | None = None, **kw):
        kw = parse_spec(spec) | kw
        self.top_k, self.params = int(kw.pop("top_k", top_k)), str(kw.pop("params", params))
        self.shuffle = bool(int(kw.pop("shuffle", shuffle)))
        timeout, retries = float(kw.pop("timeout", timeout)), int(kw.pop("retries", retries))
        self.rng = random.Random(kw.pop("seed", seed))
        kw["model"] = kw.get("model") or "jev-latest"
        super().__init__(None, **kw)
        self.llm = SimpleNamespace(mode="jev", effort=None)  # read by the game_start record only
        self.jev = J.Jev(self.model, timeout=timeout, retries=retries, deadline=timeout * (retries + 1))

    def _start_game(self, gs: melee.GameState) -> None:
        self.log = DecisionLog(self.log_dir, f"p{self.port}-{self.kind}")
        self.history, self.stats = [], []
        me, op = gs.players[self.port], gs.players[self.opponent_port]
        self.brief = {"game": f"YOU play {me.character.name} against {op.character.name}. {stage_text(gs.stage)}",
                      "basics": GUIDE, "character_tips": TIPS.get(me.character, "") + self.system_extra,
                      "how_actions_run": "Each decision starts one macro; a controller executes it frame by frame. "
                                         "Reflexes (DI, tech, mash, recovery below the stage) run automatically."}
        self.system = repr(self.brief)
        self.log.write({"type": "game_start", "agent": self.kind, "model": self.model, "port": self.port,
                        "character": me.character.name, "opponent": op.character.name, "stage": gs.stage.name,
                        "interval": self.interval, "mode": "jev", "params": self.params, "shuffle": self.shuffle,
                        "brief": self.brief, "system_prompt": self.system})

    def _options(self, d: dict) -> dict:
        items = list(d.items())
        if self.shuffle:  # Jev leans toward the first option; spread that bias instead of always favouring `wait`
            self.rng.shuffle(items)
        return dict(items)

    def questions(self) -> dict:
        q = {"action": J.choice(self._options({n: ACTION_TEXT.get(n, ACTIONS[n].desc) for n in ACTIONS}),
                                "Which action should YOU do next to win? Pick the best one for the current situation.")}
        if self.params == "none":
            return q
        q["dir"] = J.choice(self._options({d: DIR_TEXT[d] for d in DIRS}),
                            "If YOUR next move goes somewhere, which direction should it go?")
        for name, (instr, crit) in PARAM_TEXT.items():
            q[name] = J.choice(self._options(crit), instr)
        q["frames"] = J.choice(self._options(FRAMES_TEXT), "If YOUR next action lasts a while (waiting, moving, "
                                                           "shielding), how long should it last?")
        q["fastfall"] = J.noul("If YOU do an aerial now, should you fast-fall to land quickly?")
        return q

    def think(self, user: str) -> Reply:
        rep = self.jev.ask({**self.brief, "situation": user.removesuffix("\nChoose the next action.")}, self.questions())
        out = Reply(None, model=rep.model, latency_s=rep.latency_s, prompt_tokens=rep.input_tokens,
                    completion_tokens=rep.output_tokens, mode="jev", error=rep.error, text=rep.error[:600])
        if not rep.ok:
            return out
        action = rep.pick("action")
        if action not in ACTIONS:
            out.error = f"no action in answer: {action!r}"
            return out
        decision = {"action": action}
        for field_ in ACTIONS[action].params:  # schema field names: dir, jump, fastfall, throw, then, ledge, frames, count
            if field_ == "frames" and rep.pick("frames") in FRAMES:
                decision["frames"] = FRAMES[rep.pick("frames")]
            elif field_ == "fastfall" and "fastfall" in rep.answers:
                decision["fastfall"] = rep.answers["fastfall"].get("noul", 1.0) >= .5
            elif field_ in rep.answers and rep.pick(field_) in SCHEMA_FIELDS[field_].get("enum", ()):
                decision[field_] = rep.pick(field_)
        top = rep.top("action", self.top_k)
        p = dict(top).get(action, 0.0)
        decision["reason"] = f"p={p:.2f} conf={rep.confidence('action') or 0:.2f}; next " + \
                             ", ".join(f"{a} {q:.2f}" for a, q in top[1:3])
        out.args = decision
        out.extra = {"probabilities": {name: rep.top(name, self.top_k) for name, a in rep.answers.items()
                                       if a.get("type") == "choice"},
                     "nouls": {name: a.get("noul") for name, a in rep.answers.items() if a.get("type") == "noul"},
                     "confidence": rep.confidence("action"), "action_p": p, "usd": round(rep.usd, 8),
                     "attempts": rep.attempts}
        return out

    def apply(self, gs, obs, user, rep: Reply, asked_frame, **extra):
        super().apply(gs, obs, user, rep, asked_frame, **extra, **rep.extra)

    def _before_end(self):
        self.log.write({"type": "jev_stats", **self.jev.stats()})

    def close(self) -> None:
        super().close()
        self.jev.close()


class JevLive(JevBrain, LiveLLM):
    kind = "jev_live"

    def __init__(self, spec: str | None = None, **kw):
        kw = parse_spec(spec) | kw
        kw.setdefault("interval", 15)
        kw.setdefault("max_stale", 60)
        super().__init__(None, **kw)


class JevPaused(JevBrain, PausedLLM):
    kind = "jev_paused"

    def __init__(self, spec: str | None = None, **kw):
        kw = parse_spec(spec) | kw
        kw.setdefault("timeout", 5.0)
        kw.setdefault("retries", 3)
        super().__init__(None, **kw)
