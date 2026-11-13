"""Run games between two Agents on Slippi Dolphin and save .slp replays."""
from __future__ import annotations

import configparser
import os
import signal
import socket
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


WINDOW = (1280, 960)  # matches the Xvfb :99 screen that live.sh starts


class Console(melee.Console):
    """Rendered modes: put Dolphin's game window at (0, 0) filling the screen, at 2x internal resolution.

    Xvfb has no window manager, so Dolphin's fullscreen flag is ignored; an explicit window size works.
    """

    def _setup_dolphin_ini(self):
        super()._setup_dolphin_ini()
        if self.gfx_backend == "Null":
            return
        cfg_dir = self._get_dolphin_config_path()
        for name, section, values in [
            ("Dolphin.ini", "Display", {"Fullscreen": "False", "RenderToMain": "False", "RenderWindowAutoSize": "False",
                                        "RenderWindowXPos": "0", "RenderWindowYPos": "0",
                                        "RenderWindowWidth": str(WINDOW[0]), "RenderWindowHeight": str(WINDOW[1])}),
            ("GFX.ini", "Settings", {"InternalResolution": "2"}),  # window size is ignored by this build; viewer.py crops to the game window
        ]:
            path, cfg = os.path.join(cfg_dir, name), configparser.ConfigParser()
            cfg.read(path)
            if not cfg.has_section(section):
                cfg.add_section(section)
            for k, v in values.items():
                cfg.set(section, k, v)
            with open(path, "w") as f:
                cfg.write(f)

    def stop(self):
        # The AppImage launcher dies on kill() but the Dolphin inside it (AppRun.wrapped) survives and keeps
        # the Slippi port, so the next match would silently attach to it. Kill everything using our temp home.
        home = self.temp_dir
        super().stop()
        if home:
            _kill_matching(home)


def _kill_matching(needle: str) -> None:
    for pid in filter(str.isdigit, os.listdir("/proc")):
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as f:
                if needle.encode() in f.read() and int(pid) != os.getpid():
                    os.kill(int(pid), signal.SIGKILL)
        except (OSError, ValueError):
            pass


def _port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


@dataclass
class GameResult:
    stocks: dict[int, int]
    percent: dict[int, float]
    frames: int
    seconds: float
    winner: int | None = None
    agents: dict[int, str] = field(default_factory=dict)
    replay: str | None = None


def _result(gs: melee.GameState, frames: int, t0: float, agents: dict[int, Agent]) -> GameResult:
    stocks = {p: gs.players[p].stock for p in agents}
    percent = {p: gs.players[p].percent for p in agents}
    ranked = sorted(agents, key=lambda p: (stocks[p], -percent[p]), reverse=True)
    winner = ranked[0] if (stocks[ranked[0]], -percent[ranked[0]]) != (stocks[ranked[1]], -percent[ranked[1]]) else None
    return GameResult(stocks, percent, frames, time.time() - t0, winner, {p: a.name for p, a in agents.items()})


def _newest_replay(replay_dir: Path, since: float) -> Path | None:
    files = [f for f in replay_dir.rglob("*.slp") if f.stat().st_mtime >= since - 1]
    return max(files, key=lambda f: f.stat().st_mtime, default=None)


def play(agents: dict[int, Agent], iso: str, stage: melee.Stage = melee.Stage.BATTLEFIELD,
         mode: str = "watch", games: int = 1, replay_dir: Path | None = None,
         slippi_port: int = 51441) -> list[GameResult]:
    """Run `games` games. Parallel calls need distinct `slippi_port`s (and distinct X displays if rendered)."""
    assert len(agents) == 2, "two ports for now"
    if not _port_free(slippi_port):
        raise RuntimeError(f"Slippi port {slippi_port} is busy: a stale Dolphin is probably still running")
    fast, blocking = mode == "fast", mode in ("fast", "paused")
    replay_dir = replay_dir or ROOT / "replays"
    replay_dir.mkdir(parents=True, exist_ok=True)
    console = Console(
        path=str(DOLPHIN[mode]), fullscreen=False, save_replays=True, replay_dir=str(replay_dir),
        disable_audio=True, gfx_backend="Null" if fast else "OGL",
        emulation_speed=0 if fast else 1.0, blocking_input=blocking, slippi_port=slippi_port,
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
                    replay = _newest_replay(replay_dir, t0)
                    for a in agents.values():
                        a.on_game_start(gs, replay)
                last, frames = gs, frames + 1
                for p, a in agents.items():
                    if not a.cpu_level:
                        a.step(gs)
                continue
            if last is not None:
                results.append(_result(last, frames, t0, agents))
                found = _newest_replay(replay_dir, t0)
                results[-1].replay = str(found) if found else None
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
