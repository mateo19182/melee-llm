"""CLI: run Melee games between two players and save .slp replays to replays/.

    DISPLAY=:99 uv run -m melee_llm.match --iso ~/melee.iso --p1 hal:MASTER --p2 cpu:9

Player specs are listed in melee_llm/players.py.
"""
import argparse
import json
from dataclasses import asdict

import melee

from melee_llm.players import make
from melee_llm.runner import DOLPHIN, play
from melee_llm.util import exit_on_term


def main() -> None:
    p = argparse.ArgumentParser(prog="python -m melee_llm.match")
    p.add_argument("--iso", help="required except with --mode sim")
    p.add_argument("--p1", default="cpu:9")
    p.add_argument("--p2", default="cpu:9")
    p.add_argument("--char1", default="FOX")
    p.add_argument("--char2", default="FALCO")
    p.add_argument("--stage", default="BATTLEFIELD")
    p.add_argument("--mode", choices=[*DOLPHIN, "sim"], default="lockstep",
                   help="lockstep/paused: rendered, game waits for each input (real time with fast bots); "
                        "watch: real time, never waits (crashes with learned bots); fast: headless, unthrottled; "
                        "realtime: headless, 60 fps cap, waits for slow inputs; "
                        "sim: no Dolphin, melee-sim-light (docs/simulator.md)")
    p.add_argument("--games", type=int, default=1)
    a = p.parse_args()
    if not a.iso and a.mode != "sim":
        p.error("--iso is required except with --mode sim")
    exit_on_term()  # so play()'s cleanup runs under `timeout`/kill
    agents = {1: make(a.p1, a.char1), 2: make(a.p2, a.char2)}
    for r in play(agents, a.iso, melee.Stage[a.stage], a.mode, a.games):
        print(json.dumps(asdict(r), default=float))


if __name__ == "__main__":
    main()
