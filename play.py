"""Play against a bot yourself, on this machine: you on port 1 (keyboard or pad), the bot on port 2.

    uv run play.py --iso ~/melee.iso --bot phillip:gm --bot-char FOX
    uv run play.py --iso ~/melee.iso --bot faynt --bot-char FOX --stage FINAL_DESTINATION --games 3

Your controls are Port 1 of the Slippi Launcher's Dolphin (~/.config/slippi-dolphin/netplay-beta): set them
there once and they carry over. Pick your character and press Start yourself; the bot picks its own and the
stage. Ctrl-C quits. See docs/local-play.md.
"""
import argparse
import json
import os
import signal
import sys
import time
from pathlib import Path

import melee

from melee_llm.paths import ROOT
from melee_llm.players import make
from melee_llm.runner import Console, _new_replay
from melee_llm.util import port_free

DOLPHIN = ROOT / "bin/Slippi_Mainline.AppImage"  # scripts/setup.sh fetches it
SLIPPI_HOME = Path("~/.config/slippi-dolphin/netplay-beta").expanduser()  # the Launcher's mainline config
HUMAN, BOT = 1, 2


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--iso", required=True)
    p.add_argument("--bot", default="phillip:gm", help="match.py spec: phillip[:model], faynt[:variant], reyn[:command], ...")
    p.add_argument("--bot-char", default="FOX")
    p.add_argument("--stage", default="BATTLEFIELD")
    p.add_argument("--games", type=int, default=0, help="0 = until Ctrl-C")
    p.add_argument("--dolphin", default=str(DOLPHIN))
    p.add_argument("--slippi-home", default=str(SLIPPI_HOME), help="Dolphin user folder whose Port 1 controls you use")
    a = p.parse_args()
    if not Path(a.slippi_home, "Config", "GCPadNew.ini").is_file():
        sys.exit(f"no controller config in {a.slippi_home}/Config: open Dolphin from the Slippi Launcher once and "
                 "set Port 1 to Standard Controller (see docs/local-play.md)")
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
    os.environ.setdefault("QT_QPA_PLATFORM", "xcb")  # Dolphin only reads the keyboard through X11 (XInput2)

    bot, stage = make(a.bot, a.bot_char), melee.Stage[a.stage]
    replay_dir = ROOT / "replays/local"
    replay_dir.mkdir(parents=True, exist_ok=True)
    port = next(p for p in range(51460, 51480) if port_free(p))
    # Copy the Launcher's Dolphin folder so your Port 1 mapping comes along; libmelee only rewrites Port 2.
    console = Console(path=a.dolphin, dolphin_home_path=a.slippi_home, copy_home_directory=True, fullscreen=False,
                      save_replays=True, replay_dir=str(replay_dir), disable_audio=False, gfx_backend="OGL",
                      emulation_speed=1.0, blocking_input=True, slippi_port=port)
    controller = melee.Controller(console=console, port=BOT, type=melee.ControllerType.STANDARD)
    console.run(iso_path=a.iso)
    results = []
    try:
        if not (console.connect() and controller.connect()):
            raise RuntimeError("could not connect to Dolphin")
        bot.setup(controller, BOT, HUMAN)
        bot.ready()
        print(f"Dolphin is up. You: port 1. Bot: {a.bot} as {a.bot_char} on {a.stage}. Pick a character, press Start.",
              flush=True)
        menu, last, frames, replay, seen = melee.MenuHelper(), None, 0, None, set(replay_dir.rglob("*.slp"))
        screen = None
        while not a.games or len(results) < a.games:
            gs = console.step()
            if gs is None:
                continue
            if gs.menu_state != screen:
                screen = gs.menu_state
                print(f"[{screen.name}]", flush=True)
            if gs.menu_state in (melee.Menu.IN_GAME, melee.Menu.SUDDEN_DEATH):
                if last is None:
                    frames, t0, replay = 0, time.time(), _new_replay(replay_dir, seen)
                    bot.on_game_start(gs, replay)
                last, frames = gs, frames + 1
                bot.begin(gs)
                bot.step(gs)
                continue
            if last is not None:
                me, it = last.players[HUMAN], last.players[BOT]
                a_, b_ = (me.stock, -me.percent), (it.stock, -it.percent)
                r = {"game": len(results) + 1, "winner": "you" if a_ > b_ else "bot" if b_ > a_ else "tie",
                     "you": {"char": me.character.name, "stocks": me.stock, "percent": round(me.percent)},
                     "bot": {"spec": a.bot, "char": it.character.name, "stocks": it.stock, "percent": round(it.percent)},
                     "stage": last.stage.name, "seconds": round(time.time() - t0), "replay": str(replay) if replay else None}
                if replay:
                    seen.add(replay)
                bot.on_game_end(last)
                results.append(r)
                print(json.dumps(r), flush=True)
                last = None
            # Only the bot's port is driven; you pick your own character and press Start.
            menu.menu_helper_simple(gs, controller, bot.character, stage, costume=bot.costume or 1, autostart=False)
    except (KeyboardInterrupt, melee.slippstream.EnetDisconnected):  # Ctrl-C or Dolphin window closed
        pass
    finally:
        bot.close()
        console.stop()
    if results:
        wins = sum(r["winner"] == "you" for r in results)
        print(f"you {wins} - {sum(r['winner'] == 'bot' for r in results)} bot")


if __name__ == "__main__":
    main()
