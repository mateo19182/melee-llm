# Netplay: play our bots from another machine

You play on your own Slippi setup (Slippi Launcher on the laptop). The bot plays on the server, in a rendered Slippi Dolphin on the hidden display `:98`, logged in with its **own** Slippi account. You meet over **Slippi Online Direct Connect**: each side types the other's connect code. Commands are under [Play](#play).

## Rules

- **Direct Connect only, with people who agreed to play a bot.** Never Ranked or Unranked: Slippi bans bot accounts there. The code only ever goes to Direct (`MenuHelper.choose_direct_online`); don't change that.
- The bot gets its own Slippi account. Never put your own `user.json` on the server.
- Give the bot account a display name that says it's a bot, e.g. `BOT HAL`.

## Why Direct Connect

- **It is what you already play on.** Slippi Online is rollback netplay with P2P hole punching, so two machines on different networks connect directly. Tailscale isn't needed: from the laptop it reaches the server only through a DERP relay, which would add latency.
- **libmelee supports it**: `Console(user_json_path=..., online_delay=...)` logs Dolphin in, and `MenuHelper.menu_helper_simple(connect_code=...)` gets to Direct and types the code.
- **Dolphin build**: `bin/Slippi_Mainline.AppImage`, the official mainline netplay build v4.0.0-mainline-beta.19 (latest release, checked 2026-11-14). Launcher 2.15.x installs the same version on your side. The ExiAI build can't be used: it is beta.14, headless, and too old to pass Slippi's version check.
- **Fallback, not implemented**: Dolphin's classic netplay works without accounts, but it is delay-based (no rollback) and needs the same build and settings on both ends. Only worth it if Direct can't connect, for example behind a symmetric NAT.

## Bot account (one-time; you need to do this)

1. Create a second slippi.gg account (another email) in Slippi Launcher, and pick its connect code there.
2. Get its `user.json`. It holds `uid`, `playKey` and `connectCode`, and `playKey` is a secret. The easiest place is the laptop, **before** you log in with your own account:
   - Install the Launcher (see below), log in as the bot, then click Play once so Dolphin starts and writes the file.
   - Copy it to the server. It sits in the Launcher's Dolphin user folder: `~/.config/slippi-dolphin/netplay/` or `netplay-beta/` for mainline, `~/.config/SlippiOnline/` for the older build, or `~/.config/Slippi Launcher/netplay/User/Slippi/`. `find ~/.config -name user.json -path '*lippi*'` finds it:
     ```sh
     ssh mateo@m19182 'mkdir -p -m 700 ~/.config/melee-llm/slippi-bot'
     scp "$(find ~/.config -name user.json -path '*lippi*' | head -1)" mateo@m19182:.config/melee-llm/slippi-bot/user.json
     ssh mateo@m19182 'chmod 600 ~/.config/melee-llm/slippi-bot/user.json'
     ```
   - Log out in the Launcher and log in with your own account. Logging out should only delete the local file and leave the copied play key working (inferred, not tested).
3. Check it on the server: `uv run python -m melee_llm.netplay check --opponent hal --connect-code ABCD#123` prints `ok`.

The file stays outside the repo, at `~/.config/melee-llm/slippi-bot/user.json`; `MELEE_NETPLAY_USER_JSON` overrides the path. The code reads only `connectCode` out of it and never logs the rest.

## Laptop setup (Arch / Omarchy)

The ISO is at `~/Downloads/Super Smash Bros. Melee (v1.02 NTSC).iso` (md5 matches 1.02 NTSC). As of 2026-11-14 the Launcher was not installed yet; `fuse2` is present, so AppImages run.

1. **Launcher**: download `Slippi-Launcher-2.15.2-x86_64.AppImage` from https://github.com/project-slippi/slippi-launcher/releases, `chmod +x` it and run it.
2. In the Launcher, set the ISO to the path above, log in, and note your connect code (shown in the top right).
3. **Controller**:
   - With an official or Mayflash adapter in Wii U mode, add the udev rule and replug:
     ```sh
     echo 'SUBSYSTEM=="usb", ATTRS{idVendor}=="057e", ATTRS{idProduct}=="0337", MODE="0666"' | sudo tee /etc/udev/rules.d/51-gcadapter.rules
     sudo udevadm control --reload-rules
     ```
     Then in Dolphin's Controllers settings, set Port 1 to "GameCube Adapter for Wii U".
   - Any other pad (8BitDo, Xbox, DualSense) works as "Standard Controller" with its buttons mapped.
   - The keyboard works, but it is painful.
4. Turn NordVPN off while playing. A VPN breaks P2P hole punching and adds latency.

## Play

On the server, from the repo:

```sh
uv run python -m melee_llm.netplay host --opponent hal:MASTER --char FOX --connect-code ABCD#123 --games 3   # foreground, Ctrl-C ends after the game
uv run python -m melee_llm.netplay start --opponent phillip:gm --char FALCO --connect-code ABCD#123 --games 0  # background, unlimited
uv run python -m melee_llm.netplay status      # phase, bot_code, bot_port, last_result
uv run python -m melee_llm.netplay stop        # after the current game (--force kills at once)
uv run python -m melee_llm.netplay view        # noVNC of :98 at http://m19182:6081/vnc.html (watch the bot's screen)
uv run python -m melee_llm.netplay screenshot  # PNG of :98
```

`ABCD#123` is **your** code. Then on the laptop: Launcher → Play → Online → **Direct** → type the **bot's** code (`status` shows it as `bot_code`). Pick your character and press Start. Slippi decides who picks the stage; if it's the bot, it picks `--stage`. After a game you both go back to the character screen, still connected, and the bot readies up again.

- **Players**: every player spec (`melee_llm/players.py`) except `cpu:N` (a CPU level is a local VS setting) and `llm_paused` (it blocks the game, which would freeze you too). Speed matters: the game runs at the bot's pace for both of you.
  - HAL (4 ms per frame), Phillip (2 ms) and MIMIC are real time.
  - Faynt 10M on the CPU (8 ms) is borderline.
  - Reyn and `coach:` (35 ms) run at about 20 fps.
  - `llm_live` is real time: its executor never waits for the LLM.
- **Options**:
  - `--online-delay` (default 2, Slippi's default).
  - `--wait 600`: seconds to wait for you before the first game and between games.
  - `--stall 20`: seconds without frames before the session gives up, e.g. after a desync.
  - `--costume`, `--stage`, `--games` (0 = until stopped).
- **Output** in `replays/netplay/`:
  - One folder of `.slp` replays per session.
  - `results.jsonl`, one line per game: bot, both codes, bot port, characters, stage, stocks, percent, winner (`bot`, `human` or tie), frames, replay.
  - `status.json` with the current state.
  - `session.log` for background sessions.
- **Ports**: spectator ports come from 51800 to 51819, so sessions never collide with the arena (51441) or with ladder jobs.

## How it works (`melee_llm/netplay/`)

- `host.py`, `host(cfg, stop, on_status)`: runs one session in the calling thread.
  - Dolphin is `scripts/dolphin-gpu.sh` (VirtualGL on the GPU) on `DISPLAY=:98`, in a 640×480 window, with blocking pipes and `online_delay` 2. The bot's `user.json` is copied into Dolphin's temporary `User/Slippi/`.
  - Slippi assigns in-game ports only when the game starts, but our subprocess bots fix their port at `setup`. So the session builds **two instances** of the player, one per port, and steps the one whose port has the bot's connect code. The fallback is libmelee's `port_detector`, by character and costume.
  - The idle instance never presses buttons. Cost: two bot processes, e.g. 2 × 1 GB VRAM for HAL, loaded in about 20-40 s before the bot enters the lobby.
- **Rollback**: `skip_rollback_frames=True` (libmelee's default), so each agent sees every frame once, at its latest prediction. While a correction is pending, the opponent's state is Slippi's prediction (you repeating your last input). HAL's "executed action differs" check is soft here and will log more mismatches online.
- **Watchdog**: if Dolphin sends no frames for `stall` seconds, it calls `console.interrupt()`, so a dead connection ends the session instead of hanging it.
- `smoke(cfg)` needs no human: it boots, goes to Direct, types the code and screenshots every menu change into `replays/netplay/smoke-*/`.

## Python API (for the web UI)

```python
from melee_llm.netplay import start, stop, status, check, screenshot, view, HostConfig

start(opponent="hal:MASTER", connect_code="ABCD#123", char="FOX", games=3)  # kwargs = HostConfig fields; raises if busy or preflight fails
status()  # {"running", "phase", "bot_code", "opponent_code", "bot_port", "game", "games", "last_result", "error", "config", ...}
stop(force=False)
check(HostConfig(...))  # list of problems, [] if ready
screenshot()  # Path to a PNG of :98
view()        # noVNC URL for :98
```

- Phases: `starting`, `booting`, `loading bot`, `waiting` (in the lobby, `waiting_since`), `playing`, `stopping`, `done`, `failed`, or `dead` (the process died without reporting).
- `start` runs `python -m melee_llm.netplay host` in its own process group and returns at once; the state lives in `replays/netplay/status.json`.
- Only one session runs at a time, because the bot account can only be in one lobby.

## Status (2026-11-14)

A full human game over netplay has never been played: it needs the bot account and you.

- **Verified on the server, without a real account**: Dolphin beta.19 boots on `:98` and renders at 60 fps in the lobby (machine at load 55); with a dummy `user.json` the bot reaches Direct, types the code, picks Fox and readies, and Slippi's server answers "User does not exist"; `start` and `stop` load and clean up both bot instances.
- **Never tried**: a real connection, port detection on a live game, bot behaviour under rollback, who picks the stage.
- **Known gap**: after you leave the lobby, Slippi shows an error that needs Z, which MenuHelper doesn't press, so the session idles until `--wait` runs out.
