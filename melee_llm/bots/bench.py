"""Measure a bot without the ISO: stream a .slp through it with a fake controller.

    uv run python -m melee_llm.bots.bench hal replays/x.slp --port 1 --frames 3000
    uv run python -m melee_llm.bots.bench phillip replays/x.slp --arg gm --steer-mid temperature=0.8

Open loop: the replay's own inputs stay in the game state, so this measures latency and
pipeline health, not play quality.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path

import melee

from melee_llm.bots import BOTS
from melee_llm.runner import replay_states


class NullController:
    """What Agent.setup needs from a controller: its console, plus the last state the bot applied."""

    def __init__(self, console):
        self._console = console
        self.buttons: set = set()
        self.main = (0.5, 0.5)

    def press_button(self, button):
        self.buttons.add(button)

    def release_button(self, button):
        self.buttons.discard(button)

    def tilt_analog(self, button, x, y):
        if button is melee.Button.BUTTON_MAIN:
            self.main = (x, y)

    def press_shoulder(self, button, amount):
        pass


def _parse(kv: str):
    key, _, value = kv.partition("=")
    for cast in (int, float):
        try:
            return key, cast(value)
        except ValueError:
            pass
    return key, None if value in ("", "none", "None") else value


def gpu_mib(pid: int) -> int | None:
    out = subprocess.run(["nvidia-smi", "--query-compute-apps=pid,used_memory", "--format=csv,noheader,nounits"],
                         capture_output=True, text=True).stdout
    for line in out.splitlines():
        p, mib = (x.strip() for x in line.split(","))
        if int(p) == pid:
            return int(mib)
    return None


def run(bot: str, slp: Path, port: int, frames: int, arg: str | None, steer: dict, steer_mid: dict,
        config: dict | None = None) -> dict:
    first = next(replay_states(slp))
    opponent = next(p for p in sorted(first.players) if p != port)
    agent = BOTS[bot](arg, character=first.players[port].character, steer=steer, **(config or {}))
    agent.open_loop = True
    console = melee.Console(is_dolphin=False, path=str(slp), allow_old_version=True)
    console.connect()
    t0 = time.perf_counter()
    controller = NullController(console)
    agent.setup(controller, port, opponent)
    agent.ready()
    startup_s = round(time.perf_counter() - t0, 1)
    n, vram, mid_applied, moved, pressed = 0, None, None, 0, 0
    try:
        while (gs := console.step()) is not None and n < frames:
            if gs.menu_state not in (melee.Menu.IN_GAME, melee.Menu.SUDDEN_DEATH):
                continue
            if steer_mid and n == frames // 2:
                agent.steer.update(steer_mid)
            agent.step(gs)
            moved += max(abs(v - 0.5) for v in controller.main) > 0.2
            pressed += bool(controller.buttons)
            if steer_mid and n == frames // 2:
                mid_applied = dict(agent.applied_steer)
            n += 1
            if n == 300:
                vram = gpu_mib(agent._proc.pid)
    finally:
        agent.close()
    return {"bot": agent.name, "slp": slp.name, "port": port, "character": agent.character.name,
            "opponent": first.players[opponent].character.name, "stage": first.stage.name, "frames": n,
            "startup_s": startup_s,
            "stick_tilted_frac": round(moved / max(n, 1), 2), "button_frac": round(pressed / max(n, 1), 2), "errors": agent.errors, "vram_mib": vram, "info": agent.info, "steer_after_mid": mid_applied,
            **agent.latency()}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("bot", choices=BOTS)
    p.add_argument("slp", type=Path)
    p.add_argument("--port", type=int, default=1)
    p.add_argument("--frames", type=int, default=3000)
    p.add_argument("--arg")
    p.add_argument("--steer", action="append", default=[], help="key=value, set before the game")
    p.add_argument("--steer-mid", action="append", default=[], help="key=value, set halfway through")
    p.add_argument("--config", action="append", default=[], help="key=value bot init option (device, compile...)")
    a = p.parse_args()
    print(json.dumps(run(a.bot, a.slp, a.port, a.frames, a.arg, dict(map(_parse, a.steer)),
                         dict(map(_parse, a.steer_mid)), dict(map(_parse, a.config))), indent=1, default=str))


if __name__ == "__main__":
    main()
