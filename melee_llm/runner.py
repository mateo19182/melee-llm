"""Run games between two Agents on Slippi Dolphin and save .slp replays."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

import melee

from melee_llm.agents.base import Agent

ROOT = Path(__file__).resolve().parent.parent
DOLPHIN = {
    "watch": ROOT / "scripts/dolphin-gpu.sh",  # rendered on the GPU, real time (view on :99)
    "paused": ROOT / "scripts/dolphin-gpu.sh",  # rendered, game waits for every input
    "fast": ROOT / "bin/Slippi_Mainline_ExiAI.AppImage",  # headless, unthrottled
}


@dataclass
class GameResult:
    stocks: dict[int, int]
    percent: dict[int, float]
    frames: int
    seconds: float
    winner: int | None = None
    agents: dict[int, str] = field(default_factory=dict)


def _result(gs: melee.GameState, frames: int, t0: float, agents: dict[int, Agent]) -> GameResult:
    stocks = {p: gs.players[p].stock for p in agents}
    percent = {p: gs.players[p].percent for p in agents}
    ranked = sorted(agents, key=lambda p: (stocks[p], -percent[p]), reverse=True)
    winner = ranked[0] if (stocks[ranked[0]], -percent[ranked[0]]) != (stocks[ranked[1]], -percent[ranked[1]]) else None
    return GameResult(stocks, percent, frames, time.time() - t0, winner, {p: a.name for p, a in agents.items()})


def play(agents: dict[int, Agent], iso: str, stage: melee.Stage = melee.Stage.BATTLEFIELD,
         mode: str = "watch", games: int = 1, replay_dir: Path | None = None) -> list[GameResult]:
    assert len(agents) == 2, "two ports for now"
    fast, blocking = mode == "fast", mode in ("fast", "paused")
    replay_dir = replay_dir or ROOT / "replays"
    replay_dir.mkdir(parents=True, exist_ok=True)
    console = melee.Console(
        path=str(DOLPHIN[mode]), fullscreen=False, save_replays=True, replay_dir=str(replay_dir),
        disable_audio=True, gfx_backend="Null" if fast else "OGL",
        emulation_speed=0 if fast else 1.0, blocking_input=blocking,
    )
    ports = sorted(agents)
    controllers = {p: melee.Controller(console=console, port=p, type=melee.ControllerType.STANDARD) for p in ports}
    console.run(iso_path=iso)
    try:
        if not console.connect():
            raise RuntimeError("could not connect to Dolphin")
        for c in controllers.values():
            if not c.connect():
                raise RuntimeError("could not connect controller")
        for p, a in agents.items():
            a.setup(controllers[p], p, next(q for q in ports if q != p))
        menu, results = melee.MenuHelper(), []
        last, frames, t0 = None, 0, time.time()
        while len(results) < games:
            gs = console.step()
            if gs is None:
                continue
            if gs.menu_state in (melee.Menu.IN_GAME, melee.Menu.SUDDEN_DEATH):
                if last is None:
                    frames, t0 = 0, time.time()
                last, frames = gs, frames + 1
                for p, a in agents.items():
                    if not a.cpu_level:
                        a.step(gs)
                continue
            if last is not None:
                results.append(_result(last, frames, t0, agents))
                for a in agents.values():
                    a.on_game_end(last)
                last = None
            for p, a in agents.items():
                menu.menu_helper_simple(gs, controllers[p], a.character, stage, cpu_level=a.cpu_level,
                                        costume=a.costume or p, autostart=p == ports[0])
        return results
    finally:
        for a in agents.values():
            a.close()
        console.stop()


def replay_states(slp: str | Path):
    """Yield in-game GameStates from a .slp file — lets agents be tested without the ISO."""
    console = melee.Console(is_dolphin=False, path=str(slp), allow_old_version=True)
    console.connect()
    while (gs := console.step()) is not None:
        if gs.menu_state in (melee.Menu.IN_GAME, melee.Menu.SUDDEN_DEATH):
            yield gs
