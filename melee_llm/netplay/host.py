"""Play one of our players against a human over Slippi Online Direct Connect.

A rendered mainline netplay Dolphin (bin/Slippi_Mainline.AppImage through scripts/dolphin-gpu.sh) runs on the
hidden display :98, logged in with the bot's own Slippi account (its user.json). MenuHelper goes to Online →
Direct, types the human's connect code and readies up; the human enters the bot's code on their side.

Slippi gives each player its in-game port only when the game starts, and our subprocess bots fix their port at
setup. So every session builds two instances of the player, one for each port, and steps the one whose port
the bot got (found by its connect code). The idle instance never presses buttons; its share of the raw event
stream is dropped every frame.
"""
from __future__ import annotations

import configparser
import json
import os
import re
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import melee
from melee.slippstream import EnetDisconnected

from melee_llm.agents.base import Agent
from melee_llm.paths import DOLPHIN_RENDERED as DOLPHIN  # mainline beta.19 netplay build, rendered on the GPU
from melee_llm.paths import REPLAYS
from melee_llm.players import make as make_player
from melee_llm.runner import Console
from melee_llm.util import port_free

DISPLAY = ":98"  # hidden Xvfb (melee-xvfb-headless). Never :99, the streamed live slot
WINDOW = (640, 480)  # :98's screen size
SPECTATOR_PORTS = range(51800, 51820)
USER_JSON = Path(os.environ.get("MELEE_NETPLAY_USER_JSON", Path.home() / ".config/melee-llm/slippi-bot/user.json"))
OUT = REPLAYS / "netplay"
CODE_RE = re.compile(r"^[A-Z]{1,7}#[0-9]{1,4}$")


@dataclass
class HostConfig:
    opponent: str  # any player spec (melee_llm/players.py) except cpu:N and llm_paused
    connect_code: str  # the human's code, e.g. ABCD#123
    char: str = "FOX"
    stage: str = "BATTLEFIELD"  # used only if the bot gets the stage pick
    games: int = 1  # 0 = until stopped or the human leaves
    costume: int = 0
    online_delay: int = 2  # Slippi's default local input delay
    iso: str = str(Path.home() / "melee.iso")
    user_json: str = str(USER_JSON)
    wait: float = 600.0  # seconds to wait for the human, before the first game and between games
    stall: float = 20.0  # seconds without frames (e.g. a desync or hard disconnect) before giving up
    display: str = DISPLAY


@dataclass
class NetplayResult:
    game: int
    bot: str
    bot_code: str
    opponent_code: str
    bot_port: int
    bot_char: str
    opponent_char: str
    stage: str
    stocks: dict[int, int]
    percent: dict[int, float]
    winner: str | None  # "bot", "human" or None (tie)
    frames: int
    seconds: float
    replay: str | None = None
    ts: float = field(default_factory=time.time)


def normalize_code(code: str) -> str:
    code = code.strip().upper().replace("-", "#")
    if not CODE_RE.match(code):
        raise ValueError(f"not a Slippi connect code: {code!r} (expected e.g. ABCD#123)")
    return code


def bot_code(user_json: str | Path) -> str:
    """The bot account's own connect code. Only this field is read out; the play key never leaves the file."""
    try:
        return json.loads(Path(user_json).read_text()).get("connectCode", "")
    except (OSError, ValueError):
        return ""


def check(cfg: HostConfig) -> list[str]:
    """Preflight problems, empty if ready to host."""
    problems = []
    if not Path(cfg.iso).is_file():
        problems.append(f"ISO not found: {cfg.iso}")
    if not Path(cfg.user_json).is_file():
        problems.append(f"bot user.json missing: {cfg.user_json} (see docs/netplay.md, 'Bot account')")
    elif not bot_code(cfg.user_json):
        problems.append(f"{cfg.user_json} has no connectCode: not a Slippi user.json?")
    if not Path(f"/tmp/.X11-unix/X{cfg.display.lstrip(':')}").exists():
        problems.append(f"X display {cfg.display} is not running (scripts/live.sh starts it as melee-xvfb-headless)")
    try:
        normalize_code(cfg.connect_code)
        if normalize_code(cfg.connect_code) == bot_code(cfg.user_json):
            problems.append("connect code is the bot's own code")
    except ValueError as e:
        problems.append(str(e))
    kind = cfg.opponent.partition(":")[0]
    if kind == "cpu":
        problems.append("cpu:N can't play online (the CPU level is a local VS setting); use a bot")
    if kind == "llm_paused":
        problems.append("llm_paused blocks the game while thinking, which would freeze the human too; use llm_live")
    return problems


class NetplayConsole(Console):
    """runner.Console sized for :98."""

    def _setup_dolphin_ini(self):
        super()._setup_dolphin_ini()
        cfg_dir = self._get_dolphin_config_path()
        for name, section, values in [
            ("Dolphin.ini", "Display", {"RenderWindowWidth": str(WINDOW[0]), "RenderWindowHeight": str(WINDOW[1])}),
            ("GFX.ini", "Settings", {"InternalResolution": "1"}),
        ]:
            path, ini = os.path.join(cfg_dir, name), configparser.ConfigParser()
            ini.read(path)
            if not ini.has_section(section):
                ini.add_section(section)
            for k, v in values.items():
                ini.set(section, k, v)
            with open(path, "w") as f:
                ini.write(f)


def _event_lists(agent: Agent) -> list[list]:
    """The ConsoleTap subscriber lists an agent (or a coach's body) reads from."""
    return [x for x in (getattr(agent, "_events", None), getattr(getattr(agent, "body", None), "_events", None))
            if isinstance(x, list)]


def _find_port(gs: melee.GameState, code: str, char: melee.Character, costume: int) -> int:
    for p, pl in gs.players.items():
        if code and pl.connectCode == code:
            return p
    return melee.gamestate.port_detector(gs, char, costume)


def _winner(stocks, percent, me, opp) -> str | None:
    a, b = (stocks[me], -percent[me]), (stocks[opp], -percent[opp])
    return None if a == b else ("bot" if a > b else "human")


def host(cfg: HostConfig, stop: threading.Event | None = None, on_status=None) -> list[NetplayResult]:
    """Run a session in this thread. `on_status(dict)` gets phase changes and results; `stop` ends it
    after the current game (or at once while waiting in menus)."""
    stop = stop or threading.Event()
    status = {"phase": "starting", "games": 0, "config": asdict(cfg), "error": None}

    def report(**kw):
        status.update(kw)
        if on_status:
            on_status(dict(status))

    problems = check(cfg)
    if problems:
        raise RuntimeError("; ".join(problems))
    code = normalize_code(cfg.connect_code)
    me_code = bot_code(cfg.user_json)
    char, stage = melee.Character[cfg.char], melee.Stage[cfg.stage]
    port = next((p for p in SPECTATOR_PORTS if port_free(p)), None)
    if port is None:
        raise RuntimeError(f"no free Slippi spectator port in {SPECTATOR_PORTS.start}-{SPECTATOR_PORTS.stop - 1}")
    OUT.mkdir(parents=True, exist_ok=True)
    replay_dir = OUT / time.strftime("%Y%m%d-%H%M%S")
    replay_dir.mkdir()
    report(bot_code=me_code, opponent_code=code, slippi_port=port, replay_dir=str(replay_dir))

    os.environ["DISPLAY"] = cfg.display  # Console reads it for --version and Dolphin inherits it
    console = NetplayConsole(
        path=str(DOLPHIN), fullscreen=False, save_replays=True, replay_dir=str(replay_dir), disable_audio=True,
        gfx_backend="OGL", emulation_speed=1.0, blocking_input=True, slippi_port=port,
        online_delay=cfg.online_delay, user_json_path=cfg.user_json)
    controller = melee.Controller(console=console, port=1, type=melee.ControllerType.STANDARD)
    players: dict[int, Agent] = {}
    results: list[NetplayResult] = []
    last_frame = [time.time()]

    def watchdog():  # a stalled netplay game blocks console.step() forever
        while not done.wait(1):
            if time.time() - last_frame[0] > cfg.stall:
                console.interrupt()
                return

    done = threading.Event()
    try:
        console.run(iso_path=cfg.iso)
        report(phase="booting")
        if not console.connect():
            raise RuntimeError("could not connect to Dolphin")
        if not controller.connect():
            raise RuntimeError("could not connect the controller pipe")
        report(phase="loading bot")
        for p in (1, 2):  # see module docstring
            players[p] = make_player(cfg.opponent, cfg.char)
            players[p].costume = cfg.costume
            players[p].setup(controller, p, 3 - p)
        for p in (1, 2):
            players[p].ready()
        menu = melee.MenuHelper()
        last_frame[0] = time.time()
        threading.Thread(target=watchdog, daemon=True).start()
        report(phase="waiting", waiting_since=time.time())
        waiting_since, active, last, frames, t0, seen = time.time(), None, None, 0, 0.0, set()
        while not (cfg.games and len(results) >= cfg.games):
            try:
                gs = console.step()
            except EnetDisconnected:
                raise RuntimeError(f"no frames from Dolphin for {cfg.stall:.0f} s (desync or disconnect)")
            if gs is None:
                continue
            last_frame[0] = time.time()
            in_game = gs.menu_state in (melee.Menu.IN_GAME, melee.Menu.SUDDEN_DEATH)
            if in_game:
                if active is None:
                    bp = _find_port(gs, me_code, char, cfg.costume)
                    if bp not in players or len(gs.players) != 2:
                        raise RuntimeError(f"can't place the bot: port {bp}, players {sorted(gs.players)}")
                    active = players[bp]
                    frames, t0 = 0, time.time()
                    replay = min((f for f in replay_dir.rglob("*.slp") if f not in seen), key=lambda f: f.name,
                                 default=None)
                    active.on_game_start(gs, replay)
                    opp = gs.players[3 - bp]
                    report(phase="playing", game=len(results) + 1, bot_port=bp,
                           opponent_char=opp.character.name, stage_played=gs.stage.name)
                keep = {id(x) for x in _event_lists(active)}
                for a in players.values():
                    for lst in _event_lists(a):
                        if id(lst) not in keep:
                            lst.clear()
                last, frames = gs, frames + 1
                active.step(gs)
                continue
            for a in players.values():  # menus: nobody reads events until the next game starts
                if a is not active:
                    for lst in _event_lists(a):
                        lst.clear()
            if last is not None:
                bp = active.port
                stocks = {p: int(last.players[p].stock) for p in (1, 2)}
                percent = {p: float(last.players[p].percent) for p in (1, 2)}
                replay = min((f for f in replay_dir.rglob("*.slp") if f not in seen), key=lambda f: f.name,
                             default=None)
                if replay:
                    seen.add(replay)
                r = NetplayResult(
                    game=len(results) + 1, bot=active.name, bot_code=me_code, opponent_code=code, bot_port=bp,
                    bot_char=cfg.char, opponent_char=last.players[3 - bp].character.name, stage=last.stage.name,
                    stocks=stocks, percent=percent, winner=_winner(stocks, percent, bp, 3 - bp), frames=frames,
                    seconds=round(time.time() - t0, 1), replay=str(replay) if replay else None)
                active.on_game_end(last)
                results.append(r)
                with open(OUT / "results.jsonl", "a") as f:
                    f.write(json.dumps(asdict(r)) + "\n")
                report(phase="waiting", games=len(results), last_result=asdict(r), waiting_since=time.time())
                last, active, waiting_since = None, None, time.time()
                menu.stage_selected = menu.frozen_stadium_selected = False
            if stop.is_set():
                report(phase="stopping")
                break
            if time.time() - waiting_since > cfg.wait:
                report(error=f"no game started within {cfg.wait:.0f} s")
                break
            menu.menu_helper_simple(gs, controller, char, stage, connect_code=code, costume=cfg.costume,
                                    autostart=True)
        report(phase="done")
        return results
    except Exception as e:
        report(phase="failed", error=f"{type(e).__name__}: {e}")
        raise
    finally:
        done.set()
        for a in players.values():
            a.close()
        console.stop()


def smoke(cfg: HostConfig, seconds: float = 90.0, shots: Path | None = None) -> list[dict]:
    """No human needed: boot the netplay Dolphin on cfg.display, go to Online → Direct, type the code and
    screenshot every menu change. With no user.json it only navigates (libmelee won't type a code)."""
    from melee_llm.netplay.control import screenshot

    shots = shots or OUT / f"smoke-{time.strftime('%Y%m%d-%H%M%S')}"
    shots.mkdir(parents=True, exist_ok=True)
    logged_in = Path(cfg.user_json).is_file()
    code = normalize_code(cfg.connect_code)
    port = next(p for p in SPECTATOR_PORTS if port_free(p))
    os.environ["DISPLAY"] = cfg.display
    console = NetplayConsole(path=str(DOLPHIN), fullscreen=False, save_replays=False, disable_audio=True,
                             gfx_backend="OGL", emulation_speed=1.0, blocking_input=True, slippi_port=port,
                             online_delay=cfg.online_delay, user_json_path=cfg.user_json if logged_in else None)
    controller = melee.Controller(console=console, port=1, type=melee.ControllerType.STANDARD)
    menu, seen, log = melee.MenuHelper(), None, []
    try:
        console.run(iso_path=cfg.iso)
        if not (console.connect() and controller.connect()):
            raise RuntimeError("could not connect to Dolphin")
        t0, n, tick = time.time(), 0, time.time()
        while time.time() - t0 < seconds:
            gs = console.step()
            if gs is None:
                continue
            n += 1
            if time.time() - tick >= 5:
                print(json.dumps({"t": round(time.time() - t0, 1), "fps": round(n / (time.time() - tick), 1),
                                  "frame": int(gs.frame), "dolphin_alive": console._process.poll() is None}), flush=True)
                n, tick = 0, time.time()
            key = (gs.menu_state.name, getattr(gs.submenu, "name", str(gs.submenu)))
            if key != seen:
                seen = key
                time.sleep(0.5)  # let the frame render before grabbing it
                shot = screenshot(shots / f"{len(log):02d}-{key[0]}-{key[1]}.png", cfg.display)
                log.append({"t": round(time.time() - t0, 1), "menu": key[0], "submenu": key[1], "shot": str(shot),
                            "typed": menu.name_tag_index})
                print(json.dumps(log[-1]), flush=True)
            if logged_in:
                menu.menu_helper_simple(gs, controller, melee.Character[cfg.char], melee.Stage[cfg.stage],
                                        connect_code=code, costume=cfg.costume, autostart=True)
            elif key[1] != "ONLINE_PLAY_SUBMENU":  # stop at the Log-in button: pressing it opens a browser
                melee.MenuHelper.choose_direct_online(gs, controller)
            else:
                controller.release_all()
        return log
    finally:
        console.stop()
