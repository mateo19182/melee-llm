# Perception: screenshots for the LLM player

Question: does giving the LLM player screenshots help, hurt, or not matter compared with the structured text state ([llm-player.md](llm-player.md))?

Short answer from the pilot (2026-11-14): **a screenshot alone hurts; adding one to the text does not clearly help.** Models read the HUD (damage %) almost perfectly but cannot reliably tell where the fighters are, which Fox is which, or who is offstage. Keep `obs=text` as the default.

## Usage

```sh
uv run -m melee_llm.match --iso ~/melee.iso --mode paused --p1 "llm_paused:claude-haiku-4-5-20251001,obs=image" --p2 cpu:5
uv run -m melee_llm.match --iso ~/melee.iso --p1 "llm_live:claude-haiku-4-5-20251001,obs=both,clip=3" --p2 cpu:5
```

Spec keys for `llm_paused` and `llm_live`:

| Key | Default | Meaning |
|---|---|---|
| `obs` | `text` | `text`: rendered state, as before. `image`: screenshot plus a short legend (your port, character and costume, which HUD number is yours), your own recent decisions and their macro outcomes, and no game state or events. `both`: the text state plus the screenshot. |
| `clip` | 1 | Frames per decision. With more than 1, the model gets the last `clip` frames, oldest first, `clip_every` frames apart. |
| `clip_every` | 5 | Spacing of clip frames in game frames. |
| `img_width` / `img_quality` | 512 / 80 | Downscale width and JPEG quality. 512 px is 512x384 for the 640x480 game window. |

Image modes need a rendered game (`paused`, `lockstep` or `watch`, not `fast`). The agent grabs Dolphin's window on `$DISPLAY`, so run each game on its own display.

## Frame capture (`melee_llm/vision.py`)

- `PrivateDisplay()` starts an Xvfb of its own (first free number from `:120`; Xvfb's lock file settles races) and points `$DISPLAY` at it while open. Each game gets its own display, so parallel games never see each other's windows. `scripts/perception_pilot.py` runs every game this way, and never touches `:98` or `:99`.
- `Camera` finds the render window by its `GALE01` title (like `scripts/stream.sh`). Despite `RenderWindowWidth`, this Dolphin build opens it at 640x480. The camera grabs the window through XCB (Pillow `ImageGrab`, one call per shot), then downscales it and encodes a JPEG.
- **Paused mode** grabs inside `step()` while Dolphin waits for our input, so the image matches the logged state. From the in-game timer's centiseconds, it lags by at most 1-2 frames. Clip frames come from a ring that `step()` fills every `clip_every` frames.
- **Live mode** grabs on the LLM worker thread, because a grab takes longer than the 16 ms frame budget. The image is then a frame or two newer than the text state, and each image records the frame it was grabbed on. A clip ring thread runs only when `clip>1`.
- Dolphin frame dumps (`DumpConfig`) were not used. They write a video file at game end, and nothing can be read while the game runs.

Measured on this host (load average 35-60, 32 cores):

| | p50 | p95 |
|---|---|---|
| Grab, 640x480 via XCB | 16-18 ms | 22-30 ms |
| Downscale + JPEG, 512x384 | 5 ms | |
| Grab + encode inside pilot games (5 parallel) | 22-25 ms | 51-57 ms |
| Grab + encode, live games | 33 ms | 67 ms |
| JPEG size | 24 KB | |

Cost on the game: CPU vs CPU in lockstep ran at 56 fps when grabbing every 30 frames, and at 35 fps when grabbing every frame. Per decision, the grab adds about 1-2% to a 1.2 s LLM call.

## Saved images (for the web UI)

Every image sent is saved exactly as sent, next to the decision log:

```
<replay>.p<port>.llm.jsonl                     decision log (renamed at game end, as before)
<replay>.p<port>.llm.frames/f<asked>_<grabbed>.jpg
```

`<asked>` is the decision's `asked_frame` and `<grabbed>` is the game frame the shot was taken on (they can be negative before GO). The folder is renamed together with the log. Decision records gain these fields:

- `images`: a list of `{file, frame, w, h, bytes}`, oldest first. `file` is relative to the `.frames` folder.
- `image_tokens_est`: Anthropic's w·h/750 estimate.
- `capture_ms`.
- `invalid`: true when the reply was unparseable or named an unknown action.
- `image_error`, when no window was found.

`game_start` gains `obs_mode` and `clip`. `game_end` gains `invalid`, `obs_mode`, `mean_capture_ms` and `mean_image_tokens_est`.

## Which models take images through CLIProxy

Every model tried accepts `image_url` data URIs through the proxy (`/v1/chat/completions`). All of them read both damage numbers and the timer of a test frame correctly: claude-haiku-4-5-20251001, claude-sonnet-5-5, claude-sonnet-4-6, claude-opus-5-5, claude-fable-5, gpt-6-luna, gpt-6-sol, gpt-6.1-sol, gpt-6.1-terra and gpt-5.6-luna. claude-haiku-5-5 accepted the image but returned no parseable JSON.

A 512x384 JPEG costs **269-270 prompt tokens on Claude models** (the estimate is 262) and **231 on GPT models**. The local Qwen3.5-9B charges about 194.

## Local VLM baseline

- **Server:** llama.cpp b12374 (CUDA 12.8 build, in `bin/llama/`, gitignored) serving unsloth `Qwen3.5-9B-Q4_K_M.gguf` with `mmproj-F16`. It ran with `-ngl 99 -c 16384 -np 2 --jinja --chat-template-kwargs '{"enable_thinking":false}'` on 127.0.0.1:8095 and used **7.0 GB VRAM**. Spec: `llm_paused:qwen3.5-9b,obs=image,base_url=http://127.0.0.1:8095/v1,timeout=60`.
- **Decision latency** with the full prompt (1.6k tokens + image), run in isolation: **0.74 s p50** (0.56 s without the image). Haiku through the proxy took 1.14 s. In games it was 0.94 s p50, and a 2.3 s mean while the GPU was shared.
- **Play:** 19% of its replies were invalid (unparseable or an unknown action), against 0.1-0.3% for Haiku.
- The server was stopped after the pilot.

To start it again:

```sh
cd bin/llama && LD_LIBRARY_PATH=$PWD/x/llama-b12374:$PWD/x/cudart-llama-b12374-bin-ubuntu-cuda-12.8-x64 \
  x/llama-b12374/llama-server -m models/Qwen3.5-9B-Q4_K_M.gguf --mmproj models/mmproj-Qwen3.5-9B-F16.gguf \
  --host 127.0.0.1 --port 8095 -ngl 99 -c 16384 -np 2 --jinja --chat-template-kwargs '{"enable_thinking":false}' --alias qwen3.5-9b
```

## Pilot (2026-11-14)

All games were Fox (P1, orange costume) against a level-5 CPU Fox (default costume) on Battlefield. Games ended at **7200 frames (2 minutes)**: a 4-minute cap made each paused game take about 40 minutes on the loaded host. A capped game is won on stocks, then percent, like a time-out. Each game ran on its own private display, on Slippi ports 51860-51870. Data: `replays/perception/{paused,live,local}/results.jsonl`.

```sh
uv run scripts/perception_pilot.py summary replays/perception/paused
```

### Paused mode (no reaction-time confound), claude-haiku-4-5, n=8 per condition

| obs | W-L | win (95% CI) | stock diff | % diff | latency | prompt / completion tok | invalid | cost per decision* |
|---|---|---|---|---|---|---|---|---|
| text | 4-4 | 0.50 (0.22-0.78) | −0.12 | −3 | 1.14 s | 1711 / 56 | 0.1% | $0.0020 |
| image | 1-7 | 0.12 (0.02-0.47) | **−1.25** | −12 | 1.19 s | 1890 / 59 | 0.3% | $0.0022 |
| both | 5-3 | 0.62 (0.31-0.86) | −0.25 | +67 | 1.18 s | 2008 / 56 | 0.2% | $0.0023 |
| Qwen3.5-9B local, image (n=3) | 0-3 | 0.00 (0-0.56) | −2.33 | −25 | 0.94 s p50 | 1597 / 31 | 19% | — |

\* At Haiku 4.5 list prices ($1/M input, $5/M output). Through the proxy the actual spend is the subscription. About 250 decisions per 2-minute game.

- **Image only** loses about one more stock per 2 minutes. The logs show why: the model does not notice that it is hanging on the ledge or standing at the edge, so it keeps choosing `dash_dance`, which does nothing from the ledge. It also self-destructs, losing all 4 stocks in 85 s in one game. Over all 8 games, 41% of its decisions are `dash_dance`, against 6-7% in text and both modes.
- **Both** against **text**: 5-3 against 4-4 is not a significant difference (with n=8 the CIs overlap almost completely). Stock diff is about the same; percent diff is better, but it is noisy. The screenshot neither clearly helps nor hurts once the text is there. It costs about 300 more tokens (+15%) and no measurable latency.

### Live mode, claude-haiku-4-5, n=3 per condition (lockstep, about 54 fps)

| obs | W-L | stock diff | % diff | reply latency (frames, p50) | dropped stale replies |
|---|---|---|---|---|---|
| text | 0-3 | −1.00 | −2 | 67 | 18 / 260 |
| image | 1-2 | 0.00 | −119 | 71 | 34 / 238 |

Live play is dominated by the roughly 70-frame reply latency, not by perception. With n=3 nothing can be concluded. Image mode had twice as many replies dropped as stale.

### Perception probe (100 frames, image only)

`perception_pilot.py probe` sampled 100 frames, frozen in `replays/perception/paused/probe-frames.json`. They came from the paused image and both games, where the image is exactly the logged state's frame. Each model was given the same stage geometry and HUD legend as the players, and was asked for both fighters' x, y, %, stocks, offstage, airborne and facing. Scores are per fighter (n=200) unless noted.

| | Haiku 4.5 | Sonnet 5.5 | gpt-6-luna | Qwen3.5-9B (local) |
|---|---|---|---|---|
| damage % within ±1 | **0.99** | **0.99** | 0.98 | 0.52† |
| stocks exact | 0.47 | **0.93** | 0.64 | 0.16 |
| offstage flag | 0.94 | 0.95 | 0.91 | 0.46 |
| ... on frames where someone is offstage (both right, n=11) | 0.00 | 0.45 | 0.27 | 0.09 |
| airborne | 0.62 | 0.74 | 0.56 | 0.30 |
| facing | 0.48 | 0.60 | 0.52 | 0.26 |
| x error, median (units; the stage is 137 wide) | 33 | 20 | 22 | 41 |
| y error, median | 22 | 4 | 10 | 27 |
| who is left of whom (n=85) | 0.48 | 0.56 | 0.48 | 0.29 |
| which Fox is which, fighters >20 apart (n=44) | 0.64 | 0.68 | 0.50 | 0.78 (n=23) |
| latency p50 | 1.6 s | 3.9 s | 3.0 s | 2.8 s (2 parallel) |

† Qwen left fields out of about half of its replies. Missing fields count as wrong.

**Reading:** the HUD is easy for every model, and Sonnet can also count stock icons. Spatial state is not. Facing and left/right order are at chance, positions are off by 20-40 units, and offstage situations, the ones that matter most for edgeguarding and recovery, are mostly misread. Two orange and default Foxes at 512x384 are hard to tell apart. For the decisions that matter, the picture carries less usable information than the text state.

## Recommendation

- **Keep `obs=text` as the default.** Do not spend effort on image-only play with current small or medium models.
- **`obs=both` is a cheap optional extra** (+15% tokens, no extra latency) for qualitative work, and it lets the web UI show what the model saw. The evidence does not show that it improves play.
- If vision is revisited:
  - Use distinct characters, or strongly contrasting costumes.
  - Send larger images, or crops around each fighter.
  - Try Sonnet-class models, the best at spatial reading here.
  - Measure with the probe first: it is cheap, and it predicted the game result.
- The local VLM is fast (0.74 s) but not accurate enough to play: it reads the screen poorly and 19% of its replies are invalid. For a local model, use it with `obs=text` (0.56 s per decision) instead.

## Files

- `melee_llm/vision.py`: `PrivateDisplay`, `Camera`, `Shot`.
- `melee_llm/agents/llm_common.py`: `obs`/`clip` options, legend, image saving, `invalid` flag.
- `melee_llm/agents/llm_paused.py` and `llm_live.py`: when to grab.
- `melee_llm/llm.py`: `choose(..., images=[data URIs])`.
- `scripts/perception_pilot.py`: `run`, `one`, `summary`, `probe`, `rescore` and `bench`.
- `tests/test_perception.py`: offline tests of the modes, saved frames and the log rename.
