"""Check that reyn_step.FastStep plays exactly like upstream `Reyn.predict` on replay frames.

    cd vendor/Reyn && .venv/bin/python ../../scripts/reyn_agreement.py <replay.slp> --port 1 --frames 2000 \
        [--device cuda] [--command "Taunt him."] [--temperature 0.8]

Both draw from the same uniforms each frame (upstream's torch.multinomial is swapped for inverse-CDF sampling)
and run free, each feeding back its own previous action. Prints the % of frames with identical actions.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import melee
import numpy as np
import torch
from reyn import Reyn
from slippi_db.parse_libmelee import Parser

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "melee_llm/bots"))
from bot_reyn import WEIGHTS, _tree  # noqa: E402
from reyn_step import FastStep  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("slp")
    p.add_argument("--port", type=int, default=1)
    p.add_argument("--frames", type=int, default=2000)
    p.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    p.add_argument("--command")
    p.add_argument("--temperature", type=float, default=1.0)
    a = p.parse_args()

    uniforms: list[float] = []

    def multinomial(probs, n, generator=None):
        cdf = probs.cumsum(-1)
        return (cdf < uniforms.pop(0) * cdf[:, -1:]).sum(-1, keepdim=True).clamp(max=probs.shape[-1] - 1)

    torch.multinomial = multinomial  # only upstream samples with it; FastStep draws from Shared below
    ref = Reyn.load(WEIGHTS, device="cpu")
    fast = FastStep(Reyn.load(WEIGHTS, device=a.device))
    if a.command:
        ref.say(a.command), fast.model.say(a.command)

    class Shared:
        def random(self, k):
            return np.array(current)

    fast.rng = Shared()
    console = melee.Console(is_dolphin=False, path=a.slp, allow_old_version=True)
    console.connect()
    parser = Parser(ports=(a.port, next(q for q in (1, 2, 3, 4) if q != a.port)))
    n = same = 0
    while (gs := console.step()) is not None and n < a.frames:
        if gs.menu_state not in (melee.Menu.IN_GAME, melee.Menu.SUDDEN_DEATH):
            continue
        tree = _tree(parser.get_game(gs))
        current = list(np.random.default_rng(n).random(2))
        uniforms[:] = current
        with torch.inference_mode():
            expected = ref.predict(tree, temperature=a.temperature).action.reshape(-1).numpy()
        same += np.allclose(expected, fast(tree, a.temperature), atol=1e-6)
        n += 1
    print(f"{a.device} command={a.command!r} temperature={a.temperature}: {same}/{n} frames identical "
          f"({100 * same / max(n, 1):.2f}%)")


if __name__ == "__main__":
    main()
