# Web UI and the live slot

https://melee.m19182.dev serves `melee_llm/web/` from 127.0.0.1:8770 through a Cloudflare Tunnel. The site is public:

- **Visitors** can browse everything and queue matches within limits (`specs.public_errors`): Haiku or Sonnet models only, no Jev players or extra player options, at most 3 games per match, at most 2 matches waiting.
- **The owner** signs in at `/login` through Cloudflare Access (`melee_llm/web/auth.py`). Requests that do not come through Cloudflare (scripts and tools on this machine) also count as the owner, so the server refuses to bind all interfaces.
- **Owner-only controls** (Commentator, "Arena fills idle time", "Start now", Cancel) are hidden from visitors, and the server refuses them: 403 for a setting or a cancel, and "Start now" is dropped from a visitor's match (`tests/test_web_public.py`).

Pages:

- **Bench**: the Melee Bench boards per track, with category filters, rating and 95% interval, cost per game, scheduler progress, and a page per entrant.
- **Live**: the stream of display :99 as LL-HLS, proxied same-origin from mediamtx (`/hls/`), with a broadcast scorebug and a decision feed.
  - **Feed**: each LLM decision, each coach call and the steer state of learned bots, tailed from the live game's decision logs. The page holds each event until the video has played that far; "Instant" shows them on arrival. Click an entry for the full state and reply.
  - **Commentary** (`melee_llm/commentary.py`): a play-by-play ticker computed from the game state is always on. While the owner's Commentator toggle is on, an LLM (setting `commentator_model`, default `claude-haiku-5-5`) adds a two-caster booth, one call at most every 4 s from a background thread. The game loop never waits on it.
  - **Voice**: the speaker button plays the casters' lines, spoken with ElevenLabs. Speech is synthesized only while the owner's Live page has the speaker on. The key is `ELEVENLABS_API_KEY` from the environment or `~/.config/melee-llm/elevenlabs.env`, never in the repo.
- **All matches** (`/matches`): every game running on this host, live, whoever started it (web jobs, the arena, bot-writer ladders, coach pilots, scripts), drawn in 2D with Slippi Lab's character renderer about 0.35 s behind. The live slot's card shows the HLS video. Ended games move to "Recently finished".
  - Each `runner.play()` publishes its match to `data/matches/` (`melee_llm/matches.py`); `MELEE_MATCHES=0` turns that off, and its cost is in [performance.md](performance.md#per-frame). The server marks a match whose process died as crashed and forgets ended ones after 3 hours.
  - The renderer comes from `patches/slippilab.patch` and is built by `npm run build:live`.
- **Launch**: pick both players from every registered spec, characters (checked per bot), stage, mode and number of games. Models come from the CLIProxy `/v1/models`. Jobs, their results and LLM token spend (with a list-price estimate) are in `data/web.sqlite` (gitignored); replays and decision logs of job N go to `replays/jobs/N/`.
- **Games**: every `.slp` under `replays/` and the bot-writer ladders, with players and results. A game page embeds Slippi Lab next to the decision log: the current decision follows the replay, and clicking a decision jumps to the state the model saw.
- **Arena**, **Coach** (pilot summaries), **Bot-writer** (sessions with cost, time and bot source; ladder boards), **Play vs bot** (placeholder for netplay).

The frontend is plain ES modules with no build step (`melee_llm/web/static/`), with one stylesheet, `style.css`. It is styled after Melee's menus; the fonts (Archivo and Barlow, SIL OFL) are vendored in `static/vendor/fonts/`.

## Services

Two user services run it:

```sh
# web server
systemd-run --user --unit=melee-web --working-directory=$PWD --setenv=BIND=127.0.0.1 --setenv=PORT=8770 \
    $PWD/.venv/bin/python -m melee_llm.web.server
# worker: owns the live slot (display :99, Slippi port 51441) and the headless pool
systemd-run --user --unit=melee-arena --working-directory=$PWD --setenv=DISPLAY=:99 \
    $PWD/.venv/bin/python -m melee_llm.web.worker --iso ~/melee.iso
```

- Queued live jobs (lockstep or paused) run one at a time on :99. When none is queued, the learned-bot arena (below) fills the slot one game at a time; a queued job waits for the arena game to end, or aborts it if "start now" was ticked. The arena can be switched off from the UI.
- Fast jobs run headless on :98, up to 4 at once, on Slippi ports 51700-51799. An unthrottled fast job waits for a machine slot shared with the bench and the ladder ([performance.md](performance.md)).
- Each job is `python -m melee_llm.web.runjob` in its own process group, so cancelling one kills its Dolphin and bots.
- What the live slot is playing comes from the match registry: the Live page shows the match flagged `live_slot` (players, score, decision-log paths, steer state), so a manual game on :99 shows there too. To take :99 for a manual `melee_llm.match` run, switch the arena off and wait for the slot to go idle.

## Learned-bot arena

`melee_llm/arena.py` runs the learned bots and a level-9 CPU on display :99, in lockstep at about 60 fps.

- Each game uses the least-played pairing, random characters (Fox, Falco, Marth or Falcon) and a random legal stage.
- Results go to `data/arena/results.jsonl` and `data/arena/standings.json`. Ratings come from the shared fit (`melee_llm/ratings.py`) over every arena game, with CPU 9 at 1500. Standings are on the Arena page, and still at http://m19182:8767/arena (`scripts/viewer.py`, Tailscale only).
- The worker above starts it with `--games 1 --no-retry` whenever the live slot is free. Standalone, `DISPLAY=:99 uv run -m melee_llm.arena --iso ~/melee.iso` loops forever (stop the worker first).

Each arena game starts a fresh Dolphin and fresh bot processes, so about 14-30 s pass between games, mostly the bots' models loading ([performance.md](performance.md)). Keeping Dolphin up across games was left out: every arena game changes the pairing, characters and which ports are CPUs, which `runner.play()` and libmelee's menu helper do not support, and the results and character screens would still cost about 10 s per game.
