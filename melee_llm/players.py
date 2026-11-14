"""Player specs: the one place a string like `cpu:9` or `coach:haiku,body=reyn` becomes an Agent.

  cpu:N                         in-game CPU, level 1-9
  shine | idle                  libmelee's multishine demo | stands still
  llm_paused:<model>[,k=v...]   LLM player, the game waits for it          docs/llm-player.md
  llm_live:<model>[,k=v...]     LLM player thinking off-thread
  hal[:identity] phillip[:model] mimic[:checkpoint] faynt[:variant] reyn[:command]   docs/bots.md
  coach:<model|random>[,body=reyn|hal,interval=60]   LLM steering a learned bot      docs/coach.md
  jev_live | jev_paused | coach_jev [:<model>][,k=v...]   TypeSafe Jev               docs/jev.md
  bot:PATH | baseline:NAME      a bot-writer bot, sandboxed and time-budgeted        docs/bot-writer.md

Classes are imported on first use: a bot-vs-bot game never loads the LLM client, which is most of a game
process's import time.
"""
from __future__ import annotations

import importlib
from pathlib import Path

import melee

from melee_llm.agents.base import CPU, Agent

KINDS = {
    "shine": "melee_llm.agents.base:Multishine", "idle": "melee_llm.agents.base:Idle",
    "llm_paused": "melee_llm.agents.llm_paused:PausedLLM", "llm_live": "melee_llm.agents.llm_live:LiveLLM",
    "hal": "melee_llm.bots:HAL", "phillip": "melee_llm.bots:Phillip", "mimic": "melee_llm.bots:MIMIC",
    "faynt": "melee_llm.bots:Faynt", "reyn": "melee_llm.bots:ReynBot",
    "coach": "melee_llm.agents.coach:CoachedBot", "coach_jev": "melee_llm.agents.jev_coach:JevCoach",
    "jev_live": "melee_llm.agents.jev_player:JevLive", "jev_paused": "melee_llm.agents.jev_player:JevPaused",
}
WAITED_FOR = ("llm_paused", "jev_paused")  # the game stops for each of their decisions


def unthrottled(mode: str, *specs: str) -> bool:
    """A fast game nobody stops: needs a machine slot (util.claim_slot) wherever it is launched."""
    return mode == "fast" and not any(s.partition(":")[0] in WAITED_FOR for s in specs)


def make(spec: str, character: str | melee.Character, log_dir: Path | None = None) -> Agent:
    """Build the player. `log_dir`, if given, is where its decision log (or a bot-writer bot's log) goes."""
    kind, _, arg = spec.partition(":")
    char = character if isinstance(character, melee.Character) else melee.Character[character]
    if kind == "cpu":
        return CPU(int(arg or 9), char)
    if kind in ("bot", "baseline"):
        from melee_llm.botwriter.specs import make_agent
        return make_agent(spec, char, log_dir=log_dir)
    module, _, cls = KINDS[kind].partition(":")
    agent = getattr(importlib.import_module(module), cls)(*([arg] if arg else []))
    agent.character = char
    if log_dir is not None and hasattr(agent, "log_dir"):
        agent.log_dir = log_dir  # keep decision logs next to this game's replays, away from parallel games
    return agent
