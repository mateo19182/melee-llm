# Playing a bot yourself, locally

`play.py` starts Dolphin on this machine with you on port 1 and a bot on port 2.

```sh
uv run play.py --iso ~/melee.iso --bot phillip:gm --bot-char FOX
```

- **Controls:** port 1 of the Slippi Launcher's Dolphin (`~/.config/slippi-dolphin/netplay-beta`). Set them once in
  the Launcher's Dolphin (Controllers → Port 1 → Standard Controller → Configure) and `play.py` copies them.
- **Menus:** pick your character and press Start; the bot picks its own character and the stage.
- **Bots:** any `match.py` spec whose bot is installed under `vendor/`: `phillip:<model>`, `faynt`, `reyn:<command>`.
- **Stop:** close the Dolphin window or Ctrl-C. A JSON line with the score prints after each game; replays go to
  `replays/local/`.

## Two or three players

`--humans 2` (or 3) puts humans on ports 1 and 3 (and 4) against the bot on port 2, as a free-for-all. The score
line has each player (`p1`, `p3`, ..., `bot`) and the winner; Ctrl-C prints wins per player.

With a Wii U GameCube adapter: set its switch to "Wii U", plug in the black USB cable (the udev rule for `057e:0337`
comes with Steam's `60-steam-input.rules`), and in the Launcher's Dolphin (Controllers) set Port 1 and Port 3 to
"GameCube Adapter for Wii U". `play.py` exits if a human port has no device there.

```sh
uv run play.py --iso ~/melee.iso --humans 2
```
