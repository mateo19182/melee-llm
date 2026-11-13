"""Player specs shared by practice and the ladder.

  cpu:N                   in-game CPU, level 1-9
  idle                    stands still
  baseline:NAME           scripted bot from botwriter/baselines/NAME.py (visible to the coding agent)
  bot:PATH                any submitted single-file bot (sandboxed, time-budgeted)
  agent:MODULE:CLASS[:ARG]  any Agent subclass, e.g. learned bots under melee_llm.bots (ladder only)
"""
from __future__ import annotations

import importlib
from pathlib import Path

import melee

from melee_llm.agents.base import CPU, Agent, Idle
from melee_llm.botwriter.agent import BotAgent

BASELINES = Path(__file__).resolve().parent / "baselines"


def baseline_names() -> list[str]:
    return sorted(p.stem for p in BASELINES.glob("*.py"))


def make_agent(spec: str, character: melee.Character = melee.Character.FOX, budget_ms: float | None = 16.0,
               log_dir: Path | None = None, allow_agents: bool = True) -> Agent:
    kind, _, arg = spec.partition(":")
    log = (lambda name: log_dir / f"{name}.log") if log_dir else (lambda name: None)
    if kind == "cpu":
        return CPU(int(arg or 9), character)
    if kind == "idle":
        a = Idle()
        a.character = character
        return a
    if kind == "baseline":
        if arg not in baseline_names():
            raise ValueError(f"unknown baseline {arg!r}; have {baseline_names()}")
        return BotAgent(BASELINES / f"{arg}.py", budget_ms, log_path=log(f"baseline-{arg}"), label=spec)
    if kind == "bot":
        return BotAgent(arg, budget_ms, log_path=log(Path(arg).stem), label=None)
    if kind == "agent" and allow_agents:
        module, _, rest = arg.partition(":")
        cls_name, _, cls_arg = rest.partition(":")
        cls = getattr(importlib.import_module(module), cls_name)
        a = cls(cls_arg) if cls_arg else cls()
        a.character = character
        return a
    raise ValueError(f"unsupported player spec {spec!r}")
