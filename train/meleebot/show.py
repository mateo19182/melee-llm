"""Print a stretch of one stored game in readable form.

    uv run python -m meleebot.show DATA_DIR --game 0 --start 600 --frames 20
"""
import argparse, json, os

import numpy as np

from .schema import BUTTONS, CHARACTERS, FRAME, RANKS, STAGES

try:
    from melee.enums import Action
    ACTION = {a.value: a.name for a in Action}
except ImportError:
    ACTION = {}


def load(data_dir):
    games = dict(np.load(os.path.join(data_dir, "games.npz")))
    frames = np.memmap(os.path.join(data_dir, "frames.bin"), FRAME, "r")
    return games, frames


def pad_text(p):
    held = "+".join(k for k, v in BUTTONS.items() if p["buttons"] & v) or "-"
    trig = f" L{p['trigger'][0]} R{p['trigger'][1]}" if p["trigger"].any() else ""
    c = f" c({p['cstick'][0]:+d},{p['cstick'][1]:+d})" if p["cstick"].any() else ""
    return f"stick({p['stick'][0]:+3d},{p['stick'][1]:+3d}){c}{trig} {held}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("data_dir"); ap.add_argument("--game", type=int, default=0)
    ap.add_argument("--start", type=int, default=600); ap.add_argument("--frames", type=int, default=20)
    a = ap.parse_args()
    games, frames = load(a.data_dir)
    print(json.dumps(json.load(open(os.path.join(a.data_dir, "meta.json")))))
    g = a.game
    print(f"{games['replay'][g]}: {CHARACTERS[games['me_char'][g]]} ({RANKS[games['rank'][g]]}) vs "
          f"{CHARACTERS[games['opp_char'][g]]} on {STAGES[int(games['stage'][g])]}, "
          f"{'won' if games['win'][g] else 'lost'}, {games['length'][g]} frames")
    lo = int(games["offset"][g]) + a.start
    for i, f in enumerate(frames[lo:lo + a.frames]):
        me, opp = f["me"], f["opp"]
        print(f"{a.start + i:5d} me {ACTION.get(int(me['action']), me['action']):>22} age {me['state_age']:4.0f} "
              f"pos({me['pos'][0]:7.1f},{me['pos'][1]:6.1f}) {me['percent']:5.1f}% | "
              f"opp {ACTION.get(int(opp['action']), opp['action']):>18} pos({opp['pos'][0]:7.1f},{opp['pos'][1]:6.1f}) "
              f"{opp['percent']:5.1f}% | pad {pad_text(f['me_pad'])}")


if __name__ == "__main__":
    main()
