"""CLI: run Melee games between two players and save .slp replays to replays/.

Players: cpu:N (in-game CPU level 1-9), shine, idle. More arrive as agents are added to AGENTS.
"""
import argparse
import json
from dataclasses import asdict

import melee

from melee_llm.agents.base import CPU, Idle, Multishine
from melee_llm.runner import DOLPHIN, play

AGENTS = {"shine": Multishine, "idle": Idle}


def make(spec: str, character: str):
    kind, _, arg = spec.partition(":")
    char = melee.Character[character]
    if kind == "cpu":
        return CPU(int(arg or 9), char)
    agent = AGENTS[kind]() if not arg else AGENTS[kind](arg)
    agent.character = char
    return agent


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--iso", required=True)
    p.add_argument("--p1", default="cpu:9")
    p.add_argument("--p2", default="cpu:9")
    p.add_argument("--char1", default="FOX")
    p.add_argument("--char2", default="FALCO")
    p.add_argument("--stage", default="BATTLEFIELD")
    p.add_argument("--mode", choices=DOLPHIN, default="watch",
                   help="watch: real time; paused: game waits for each input; fast: headless, unthrottled")
    p.add_argument("--games", type=int, default=1)
    a = p.parse_args()
    agents = {1: make(a.p1, a.char1), 2: make(a.p2, a.char2)}
    for r in play(agents, a.iso, melee.Stage[a.stage], a.mode, a.games):
        print(json.dumps(asdict(r), default=float))


if __name__ == "__main__":
    main()
