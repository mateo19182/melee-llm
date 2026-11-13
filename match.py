"""CLI: run Melee games between two players and save .slp replays to replays/.

Players: cpu:N (in-game CPU level 1-9), shine, idle, llm_paused:<model>, llm_live:<model> (see AGENTS).
"""
import argparse
import json
import signal
import sys
from dataclasses import asdict

import melee

from melee_llm.agents.base import CPU, Idle, Multishine
from melee_llm.runner import DOLPHIN, play

AGENTS = {"shine": Multishine, "idle": Idle}

from melee_llm.agents.llm_live import LiveLLM  # noqa: E402
from melee_llm.agents.llm_paused import PausedLLM  # noqa: E402

AGENTS |= {"llm_paused": PausedLLM, "llm_live": LiveLLM}  # llm_paused:<model>[,interval=30,mode=json,...]

from melee_llm.bots import BOTS  # noqa: E402

AGENTS |= BOTS  # hal[:identity], phillip[:model], mimic[:checkpoint], faynt[:variant]; see docs/bots.md


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
    p.add_argument("--mode", choices=DOLPHIN, default="lockstep",
                   help="lockstep/paused: rendered, game waits for each input (real time with fast bots); "
                        "watch: real time, never waits (crashes with learned bots); fast: headless, unthrottled")
    p.add_argument("--games", type=int, default=1)
    a = p.parse_args()
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))  # so play()'s cleanup runs under `timeout`/kill
    agents = {1: make(a.p1, a.char1), 2: make(a.p2, a.char2)}
    for r in play(agents, a.iso, melee.Stage[a.stage], a.mode, a.games):
        print(json.dumps(asdict(r), default=float))


if __name__ == "__main__":
    main()
