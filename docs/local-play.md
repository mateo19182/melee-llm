# Playing a bot yourself, locally

`play.py` starts Dolphin on this machine with you on port 1 and a bot on port 2. You pick your character and press
Start; the bot picks its own character and the stage.

## Demo cheat sheet

```sh
cd ~/Work/personal/melee-llm
ISO="$HOME/Downloads/Super Smash Bros. Melee (v1.02 NTSC).iso"

# Our own bot: behaviour-cloned Yoshi (lane B)
uv run play.py --iso "$ISO" --bot meleebot:bc-6m-v1 --bot-char YOSHI

# Phillip (slippi-ai), the strong one
uv run play.py --iso "$ISO" --bot phillip:gm --bot-char FOX
```

- **Starts** in a few seconds (Dolphin opens, the bot loads), then character select. Pick a character, press Start.
- **Stop:** Ctrl-C in the terminal, or close the Dolphin window. Both shut everything down in under 10 s.
- **After each game** a JSON line prints the score and the game's `fps` (60 = no slowdown). You return to character
  select; press Start again for another game. Replays go to `replays/local/`.
- **Stage:** `--stage FINAL_DESTINATION` (default `BATTLEFIELD`). **Games:** `--games 3` stops after three.

### If something goes wrong

| Problem | Fix |
|---|---|
| Crash, freeze or a stuck window | Ctrl-C, then `pkill -f AppRun.wrapped` to clear leftovers, then run the command again. |
| `could not connect to Dolphin` | Same: clear leftovers and rerun. Another Dolphin may be holding the port. |
| Controller does nothing | Unplug and replug it, then restart `play.py` (Dolphin only finds devices at start). Check Port 1 in the Launcher's Dolphin (below). |
| Game runs slow (`fps` well under 60) | Plug in the charger and close other heavy apps. Phillip is the safer choice: lighter on the CPU. |
| Yoshi bot fails to start | Its venv or checkpoint is missing: see "Setup" below. Play Phillip meanwhile. |

## Controller

Your controls are Port 1 of the Slippi Launcher's Dolphin (`~/.config/slippi-dolphin/netplay-beta`). Set them once
there (Slippi Launcher, Dolphin's configuration → Controllers); `play.py` copies them on every start.

- **GameCube controller on a Wii U adapter** (official or Mayflash): set the adapter's switch to "Wii U", plug in
  the black USB cable, and set Port 1 to "GameCube Adapter for Wii U". No mapping needed. The udev rule for
  `057e:0337` comes with Steam's `60-steam-input.rules`; without Steam see `docs/netplay.md`.
- **Any other pad** (8BitDo, Xbox, DualSense): set Port 1 to "Standard Controller", Configure, pick the pad as Device
  and map the buttons.
- **Keyboard** (fallback): arrows = stick, X = A, Z = B, C/S = X/Y, D = Z, Q/W = L/R, IJKL = C-stick, Enter = Start.
  Hold the direction a moment before B for specials.

## Bots

Any `match.py` player spec whose bot is installed works: `phillip:<model>` (`gm`, `super-gm`, `master`, `diamond`,
`fox_d21_v6.2`), `meleebot[:run]`, `faynt`, `reyn:<command>`, `baseline:<name>`, `bot:<path.py>`.

Dolphin waits for the bot every frame, so a bot slower than 16.7 ms per frame slows the whole game. On the laptop
(Ryzen AI Max 390, CPU only) Phillip gm and meleebot bc-6m-v1 both hold 60 fps.

## Setup (once per machine)

- Dolphin: `bin/Slippi_Mainline.AppImage` (`scripts/setup.sh`), the Slippi Launcher's Dolphin config for Port 1.
- meleebot runs under `train/.venv`, CPU-only on a laptop without NVIDIA:
  ```sh
  cd train && uv venv --python 3.12 && uv pip install --torch-backend cpu torch numpy "melee>=0.47.6" "peppi-py>=0.8"
  ```
  and its checkpoint at `data/train/runs/bc-6m-v1/last.pt` (copy it from the server).

## Two or three players

`--humans 2` (or 3) puts humans on ports 1 and 3 (and 4) against the bot on port 2, as a free-for-all.

- The score line has each player (`p1`, `p3`, ..., `bot`) and the winner; Ctrl-C prints wins per player.
- Set Port 3 (and 4) in the Launcher's Dolphin too: `play.py` exits if a human port has no device there.
- Phillip only sees port 1.

```sh
uv run play.py --iso "$ISO" --bot phillip:gm --bot-char FOX --humans 2
```
