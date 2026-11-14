"""Run games between two Agents on Slippi Dolphin and save .slp replays."""
from __future__ import annotations

import configparser
import ctypes
import os
import re
import signal
import struct
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import melee

from melee_llm import matches
from melee_llm.agents.base import Agent
from melee_llm.paths import DOLPHIN_HEADLESS, DOLPHIN_RENDERED, HEADLESS_DISPLAY, LIVE_DISPLAY, REPLAYS
from melee_llm.util import port_free

DOLPHIN = {
    "watch": DOLPHIN_RENDERED,  # rendered on the GPU, real time (view on :99)
    "paused": DOLPHIN_RENDERED,  # rendered, game waits for every input (slow players → slow motion)
    "lockstep": DOLPHIN_RENDERED,  # same as paused; with fast bots it runs at real time, no dropped frames
    "fast": DOLPHIN_HEADLESS,  # headless, unthrottled
    "realtime": DOLPHIN_HEADLESS,  # headless lockstep: 60 fps cap, game waits for slow inputs
}
WINDOW = (1280, 960)  # matches the Xvfb :99 screen that scripts/live.sh starts
LIVE_WINDOW = (1168, 960)  # the streamed game window on :99: Melee's 73:60 at the screen's full height


class Console(melee.Console):
    """Rendered modes: Dolphin's game window at (0, 0), at 2x internal resolution.

    Xvfb has no window manager, so Dolphin's fullscreen flag is ignored, and so are the RenderWindow sizes in
    Dolphin.ini: the game window opens at 640x480 (Qt's default) and resizing it later breaks the picture, since
    VirtualGL keeps its first buffer size. On the live display the window is instead created at LIVE_WINDOW from
    Qt's saved geometry, with the picture stretched to it (same aspect, so no distortion and no black bars).
    """

    def _setup_dolphin_ini(self):
        super()._setup_dolphin_ini()
        if self.gfx_backend == "Null":
            return
        cfg_dir = self._get_dolphin_config_path()
        gfx = {"InternalResolution": "2"}
        if self._live():
            gfx["AspectRatio"] = "3"  # stretch to window
            _set_qt_geometry(os.path.join(cfg_dir, "Qt.ini"), LIVE_WINDOW)
        for name, section, values in [
            ("Dolphin.ini", "Display", {"Fullscreen": "False", "RenderToMain": "False", "RenderWindowAutoSize": "False",
                                        "RenderWindowXPos": "0", "RenderWindowYPos": "0",
                                        "RenderWindowWidth": str(WINDOW[0]), "RenderWindowHeight": str(WINDOW[1])}),
            ("GFX.ini", "Settings", gfx),
        ]:
            path, cfg = os.path.join(cfg_dir, name), configparser.ConfigParser()
            cfg.read(path)
            if not cfg.has_section(section):
                cfg.add_section(section)
            for k, v in values.items():
                cfg.set(section, k, v)
            with open(path, "w") as f:
                cfg.write(f)

    def _live(self) -> bool:
        return os.environ.get("DISPLAY") == LIVE_DISPLAY

    def run(self, *args, **kwargs):
        super().run(*args, **kwargs)
        if self.gfx_backend != "Null" and self._live():
            # Qt leaves room for a title bar no window manager draws and puts the window back at y=20 (bottom
            # off screen, Dolphin's menu bar showing above it) when the game starts, so keep moving it home
            # while Dolphin runs. Moving it (unlike resizing) is safe.
            self._home_stop = threading.Event()
            threading.Thread(target=_keep_game_window_home, args=(os.environ["DISPLAY"], self._home_stop), daemon=True).start()

    def stop(self):
        # The AppImage launcher dies on kill() but the Dolphin inside it (AppRun.wrapped) survives and keeps
        # the Slippi port, so the next match would silently attach to it. Kill everything using our temp home.
        home = self.temp_dir
        if stop := getattr(self, "_home_stop", None):
            stop.set()
        super().stop()
        if home:
            _kill_matching(home)


def _set_qt_geometry(path: str, size: tuple[int, int]) -> None:
    """Write the game window's saved geometry ([renderwidget] in Qt.ini, QWidget::saveGeometry v3.0 format)."""
    w, h = size
    rect = struct.pack(">4i", 0, 0, w - 1, h - 1)
    blob = struct.pack(">IHH", 0x1D9D0CB, 3, 0) + rect + rect + struct.pack(">iBBi", 0, 0, 0, WINDOW[0]) + rect
    value = "@ByteArray(" + "".join(f"\\x{b:02x}" for b in blob) + ")"
    try:
        text = open(path).read()
    except OSError:
        text = ""
    # Qt keys are case-sensitive, so no configparser (it lowercases them): drop any old section, append ours.
    text = re.sub(r"(?ms)^\[renderwidget\]\n.*?(?=^\[|\Z)", "", text).rstrip("\n")
    with open(path, "w") as f:
        f.write(f"{text}\n\n[renderwidget]\ngeometry={value}\n".lstrip("\n"))


def _keep_game_window_home(display: str, stop: threading.Event) -> None:
    """Keep Dolphin's game window on `display` at (0, 0) until `stop` is set."""
    x11 = ctypes.CDLL("libX11.so.6")
    x11.XOpenDisplay.restype = ctypes.c_void_p
    dpy = ctypes.c_void_p(x11.XOpenDisplay(display.encode()))
    if not dpy.value:
        return
    try:
        while not stop.wait(0.5):
            out = subprocess.run(["xwininfo", "-root", "-tree"], env={**os.environ, "DISPLAY": display},
                                 capture_output=True, text=True).stdout
            m = re.search(r"^\s*(0x[0-9a-f]+) \"[^\"]*GALE01[^\"]*\".*?\d+x\d+\+(-?\d+)\+(-?\d+)", out, re.M)
            if m and (m[2], m[3]) != ("0", "0"):
                x11.XMoveWindow(dpy, ctypes.c_ulong(int(m[1], 16)), 0, 0)
                x11.XFlush(dpy)
    finally:
        x11.XCloseDisplay(dpy)


def _kill_matching(needle: str) -> None:
    for pid in filter(str.isdigit, os.listdir("/proc")):
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as f:
                if needle.encode() in f.read() and int(pid) != os.getpid():
                    os.kill(int(pid), signal.SIGKILL)
        except (OSError, ValueError):
            pass


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


def _new_replay(replay_dir: Path, seen: set[Path]) -> Path | None:
    """Oldest .slp not yet assigned to a game (names are Game_<start time>.slp). A Sudden Death after a
    timed-out game gets its own, later file, which must not be taken for the game's replay."""
    return min((f for f in replay_dir.rglob("*.slp") if f not in seen), key=lambda f: f.name, default=None)


def _cpus_ready(gs: melee.GameState, agents: dict[int, Agent]) -> bool:
    """libmelee's autostart presses START once both characters are picked, before a CPU on a later port has
    switched itself to CPU: that port would then stand still all game. Start only once every CPU is set."""
    return all(p in gs.players and gs.players[p].controller_status == melee.ControllerStatus.CONTROLLER_CPU
               and gs.players[p].cpu_level == a.cpu_level for p, a in agents.items() if a.cpu_level)


def play(agents: dict[int, Agent], iso: str, stage: melee.Stage = melee.Stage.BATTLEFIELD,
         mode: str = "watch", games: int = 1, replay_dir: Path | None = None,
         slippi_port: int = 51441, observer: Callable[[str, dict], None] | None = None,
         meta: dict | None = None) -> list[GameResult]:
    """Run `games` games. Parallel calls need distinct `slippi_port`s (and distinct X displays if rendered).

    `mode="sim"` plays in melee-sim-light instead of Dolphin (melee_llm.sim.runner).

    `observer(event, info)`, if given, is called with "game_start" {game, replay, gs}, "frame" {gs} on every
    in-game frame (after the agents stepped) and "game_end" {game, result} (in sim mode also `gs`, the final
    frame, which no "frame" event shows). It must be fast.

    Every call publishes itself to the match registry (melee_llm.matches, shown on the web UI's All matches
    page). `meta` overrides what it guesses: {"source", "label", "job_id", "specs": {port: spec}, ...}.
    """
    if mode == "sim":  # no Dolphin: melee-sim-light (docs/simulator.md); iso, replay_dir and slippi_port unused
        from melee_llm.sim.runner import play as play_sim
        return play_sim(agents, stage, games, observer=observer, meta=meta)
    notify = observer or (lambda event, info: None)
    stepping = [a for a in agents.values() if not a.cpu_level]
    assert len(agents) == 2, "two ports for now"
    if not port_free(slippi_port):
        raise RuntimeError(f"Slippi port {slippi_port} is busy: a stale Dolphin is probably still running")
    fast, blocking = mode == "fast", mode in ("fast", "paused", "lockstep", "realtime")
    headless = mode in ("fast", "realtime")
    replay_dir = replay_dir or REPLAYS
    replay_dir.mkdir(parents=True, exist_ok=True)
    console = Console(
        path=str(DOLPHIN[mode]), fullscreen=False, save_replays=True, replay_dir=str(replay_dir),
        disable_audio=True, gfx_backend="Null" if headless else "OGL",
        emulation_speed=0 if fast else 1.0, blocking_input=blocking, slippi_port=slippi_port,
    )
    ports = sorted(agents)
    controllers = {p: melee.Controller(console=console, port=p, type=melee.ControllerType.STANDARD) for p in ports}
    display = os.environ.get("DISPLAY")
    pub = matches.publisher(agents, stage, mode, games, slippi_port, replay_dir, meta)
    error = None
    if headless:  # keep headless Dolphins off the streamed display
        os.environ["DISPLAY"] = HEADLESS_DISPLAY
    try:
        console.run(iso_path=iso)
    except BaseException as e:
        if pub:
            pub.close(e)
        raise
    finally:
        if headless:
            os.environ.pop("DISPLAY", None) if display is None else os.environ.__setitem__("DISPLAY", display)
    try:
        if not console.connect():
            raise RuntimeError("could not connect to Dolphin")
        for c in controllers.values():
            if not c.connect():
                raise RuntimeError("could not connect controller")
        for p, a in agents.items():
            a.setup(controllers[p], p, next(q for q in ports if q != p))
        for a in agents.values():
            a.ready()
        menu, results = melee.MenuHelper(), []
        last, frames, t0, replay, tiebreak = None, 0, time.time(), None, False
        seen = set(replay_dir.rglob("*.slp"))

        def finish(final: melee.GameState) -> None:
            results.append(_result(final, frames, t0, agents))
            found = replay or _new_replay(replay_dir, seen)
            seen.add(found)
            results[-1].replay = str(found) if found else None
            for a in agents.values():
                a.on_game_end(final)
            if pub:
                pub.game_end(len(results) - 1, results[-1])
            notify("game_end", {"game": len(results) - 1, "result": results[-1]})

        while len(results) < games:
            gs = console.step()
            if gs is None:
                continue
            in_game = gs.menu_state in (melee.Menu.IN_GAME, melee.Menu.SUDDEN_DEATH)
            if in_game and last is not None and gs.frame < last.frame:
                # A timeout with tied stocks starts Sudden Death as a new game (frame -123, its own .slp), with no
                # menu in between: score the timed-out game on its last frame (stocks, then percent).
                finish(last)
                last, tiebreak = None, True
            if in_game and tiebreak:
                # play the tie-break out uncounted: with nobody pressing anything it would never end
                for a in stepping:
                    a.begin(gs)
                for a in stepping:
                    a.step(gs)
                continue
            if tiebreak:  # back in the menus: the tie-break's .slp must not be taken for the next game
                seen.add(_new_replay(replay_dir, seen))
                tiebreak = False
            if in_game:
                if last is None:
                    frames, t0 = 0, time.time()
                    wrong = {p: int(gs.players[p].cpu_level) for p, a in agents.items() if gs.players[p].cpu_level != a.cpu_level}
                    if wrong:
                        raise RuntimeError(f"game started with wrong CPU levels {wrong}")
                    replay = _new_replay(replay_dir, seen)
                    for a in agents.values():
                        a.on_game_start(gs, replay)
                    if pub:
                        pub.game_start(len(results), gs, replay)
                    notify("game_start", {"game": len(results), "replay": replay, "gs": gs})
                last, frames = gs, frames + 1
                for a in stepping:
                    a.begin(gs)
                for a in stepping:
                    a.step(gs)
                if pub:
                    pub.frame(gs)
                if observer:
                    observer("frame", {"gs": gs})
                continue
            if last is not None:
                finish(last)
                last = None
            start = gs.menu_state != melee.Menu.CHARACTER_SELECT or _cpus_ready(gs, agents)
            for p, a in agents.items():
                menu.menu_helper_simple(gs, controllers[p], a.character, stage, cpu_level=a.cpu_level,
                                        costume=a.costume or p, autostart=start and p == ports[0])
        return results
    except BaseException as e:
        error = e
        raise
    finally:
        for a in agents.values():
            a.close()
        console.stop()
        if pub:
            pub.close(error)


def replay_states(slp: str | Path):
    """Yield in-game GameStates from a .slp file — lets agents be tested without the ISO."""
    console = melee.Console(is_dolphin=False, path=str(slp), allow_old_version=True)
    console.connect()
    while (gs := console.step()) is not None:
        if gs.menu_state in (melee.Menu.IN_GAME, melee.Menu.SUDDEN_DEATH):
            yield gs
