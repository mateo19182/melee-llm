"""Check that each farm seat sees what the live Faynt bot would: the same frames, encoded as Slippi events
(melee_llm.sim.slippi, checked against Dolphin) and rebuilt by libmelee's Console, as bots/server.py does.

    python -m faynt.parity [--games 6] [--lanes 6]

Prints, per field of slippi-ai's Game, how many seat-frames differ. Every stage is covered with --games 6.
"""
import argparse
import collections

import numpy as np

from . import farm


def flatten(nt, prefix=""):
    if hasattr(nt, "_fields"):
        for f in nt._fields:
            yield from flatten(getattr(nt, f), f"{prefix}{f}.")
    else:
        yield prefix[:-1], nt


def main():
    from slippi_db.parse_libmelee import Parser

    from melee_llm.bots.server import Replayer
    from melee_llm.sim.slippi import Encoder
    from melee_llm.sim.state import SIM_STAGE

    ap = argparse.ArgumentParser()
    ap.add_argument("--a", default="faynt:10M-Arena/YOSHI")
    ap.add_argument("--b", default="faynt:10M-Arena/FOX")
    ap.add_argument("--games", type=int, default=6)
    ap.add_argument("--lanes", type=int, default=6)
    ap.add_argument("--ucf", action="store_true")
    args = ap.parse_args()

    lanes = {}  # lane -> (encoder, replayer, parser per port), renewed at each game's first frame
    diffs, frames, examples = collections.Counter(), [0], {}

    def on_frame(lane, obs, inputs, games):
        f = int(obs["frame_id"])
        if lane not in lanes or f == -123:
            stage = next(s for s, v in SIM_STAGE.items() if v == int(obs["stage_id"]))
            lanes[lane] = (Encoder(stage, [1, 2]), Replayer(), {p: Parser(ports=(p, 3 - p)) for p in (1, 2)})
        encoder, replayer, parsers = lanes[lane]
        gs = replayer.feed([("game_event", encoder.frame(obs, inputs))])
        for port, game in games.items():
            ref = parsers[port].get_game(gs)
            frames[0] += 1
            for (name, ours), (_, theirs) in zip(flatten(game), flatten(ref)):
                if not np.array_equal(np.asarray(ours), np.asarray(theirs)):
                    diffs[name] += 1
                    examples.setdefault(name, (lane, f, port, ours, theirs))

    farm.play(farm.Player.parse(args.a), farm.Player.parse(args.b), args.games, args.lanes, ucf=args.ucf,
              on_frame=on_frame)
    print(f"{frames[0]:,} seat-frames compared")
    for name, n in diffs.most_common():
        print(f"  {name}: {n:,} differ, e.g. lane/frame/port/ours/libmelee {examples[name]}")
    if not diffs:
        print("  every field equal")


if __name__ == "__main__":
    main()
