# Demo run sheet (hackathon, 2026-11-14)

About 5-7 minutes. Three parts: website tour, a live commentated match, you vs a bot. Each part has a fallback.

## Before you start (15 min before)

- [ ] Laptop on power, sound out to speakers, browser zoom so the site fills the projector.
- [ ] Sign in: open `melee.m19182.dev/login` once in the demo browser. Signed out, the site is the public view: **Commentator**, **Arena fills idle time**, **Start now** and the Cancel buttons are not shown.
- [ ] Tabs open, in order: **Bench**, **Live**, **Launch**, **Games** (one replay), the **write-up** page (`/writeup/`, also the **Write-up** menu item), and the backup clip (`writeup/media/backup-clip.mp4`, downloaded locally).
- [ ] Server: nothing queued on the live slot (Live page → "Up next" says "Queue empty."). Turn **Arena fills idle time** off so the slot is free when you launch.
- [ ] Commentator test: on the Live page tick **Commentator** and **Voice**, and hear one line during any game. If no voice comes, check `~/.config/melee-llm/elevenlabs.env` on the server.
- [ ] Laptop: charger in, GameCube controller on the Wii U adapter (switch on "Wii U") and one short `play.py` game with it (see part 4).

## 1. The hook (30 s, write-up open)

> "LLMs are great at turn-based games because the game waits for them. I wanted a game that doesn't wait: Super Smash Bros. Melee, 60 frames a second. So I put frontier LLMs inside it five different ways and rated all of them on one Elo scale, next to the game's own CPUs and the best AI bots people have published."

Show the TL;DR, then scroll to the 2D replay clip under "Melee in 30 seconds".

## 2. Website tour (2 min)

1. **Bench** (`/bench`): the real-time board.
   - Point at the **top**: Faynt, 390 wins and 0 losses. Then Phillip, HAL: learned bots trained on human replays.
   - Point at the **bottom**: every LLM playing live, around a level 4 CPU. "Speed beats smarts: a 2-second thought is 120 frames of getting hit."
   - Point at **"Reyn holding 'Don't die.'"**, third from the top. "Four frontier LLMs took turns coaching this bot. It did best with no coach at all, just the words 'Don't die.'"
   - Click an entrant (e.g. GPT-6.1 Sol live) to show its record, games and sample decisions.
2. **Games** (`/games`), one replay page: the Slippi Lab 2D replay with the AI's decision timeline. Click a decision and the replay jumps to what the model saw.
3. **All matches** (`/matches`): every game running on the server, drawn live in 2D (only if something is running).

## 3. Live match with the AI commentators (2-3 min)

Launch it at the start of part 2 so it's in game by the time you get here (bots load in about 20-30 s, then the character screen).

**Launch page** (`/launch`):

| | Fun pick (recommended) | Alternative |
|---|---|---|
| P1 | **LLM coach steering a learned bot**, model `claude-haiku-4-5-20251001` (body Reyn) | **Reyn (language-steerable)**, command `Don't die.` |
| P2 | **Phillip (slippi-ai)**, model `gm` | **Phillip (slippi-ai)**, model `gm` |
| Characters | Fox vs Fox | Fox vs Fox |
| Stage, mode, games | Battlefield, **lockstep**, 1 | same |

Tick **Start now** if the arena is still playing, then **Queue match**.

Other good ones: `meleebot` (our own Yoshi) vs `cpu:9`, honest about it losing; `faynt` vs `hal:MASTER` for pure spectacle (Faynt wins).

**Live page** (`/live`):

- Tick **Commentator** and **Voice** (or press `v`). Lines start within a few seconds of the first hit.
- Point at the **Decisions** feed: each coach call shows the command it picked and why, timed to the video.
- "Two casters, Charlie on play-by-play and Laura on colour. A fast LLM watches the events and writes the lines, ElevenLabs voices them, and nothing is synthesized unless someone is listening."

**Fallback:** if the stream doesn't start in 60 s or the voice stays silent, play the backup clip (`writeup/media/backup-clip.mp4`): a full commentated game with the voices, recorded today.

## 4. You vs a bot, on the laptop (2 min)

Full cheat sheet: `docs/local-play.md` ("Demo cheat sheet"). On the laptop:

```sh
cd ~/Work/personal/melee-llm
ISO="$HOME/Downloads/Super Smash Bros. Melee (v1.02 NTSC).iso"
uv run play.py --iso "$ISO" --bot meleebot:bc-6m-v1 --bot-char YOSHI   # our Yoshi
uv run play.py --iso "$ISO" --bot phillip:gm --bot-char FOX             # Phillip gm
```

- Dolphin opens in a few seconds and the bot loads. At character select, pick yours and press Start; the bot picks its character and the stage.
- **Our Yoshi first**: "trained today on 23,000 ranked online games; it lost its first game 0-3 to the hardest CPU, so you have a chance." Then offer a brave volunteer **Phillip gm**.
- After each game a score line prints and you're back at character select; press Start for another.
- **Stop:** Ctrl-C in the terminal or close the Dolphin window (everything exits in under 10 s).

**Fallbacks:**
- Crash or freeze: Ctrl-C, `pkill -f AppRun.wrapped`, run the command again.
- Controller does nothing: replug it and restart `play.py` (Dolphin only finds devices at start). Keyboard works as a last resort (arrows = stick, X = A, Z = B, Enter = Start).
- Yoshi won't start: play Phillip instead.
- Nothing works: skip to the outro; the live match already showed bots playing.

## 5. Outro (20 s)

> "All of this, the bench, the coach, the commentators, the simulator, our own Yoshi bot, was built in two days. The write-up is at melee.m19182.dev/writeup."

Leave the Bench page up.

## If everything is down

The write-up page (`writeup/index.html`) works offline from the laptop: open it in a browser with the backup clip next to it.
