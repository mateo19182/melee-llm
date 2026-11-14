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
