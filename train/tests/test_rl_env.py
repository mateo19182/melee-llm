"""The self-play env must hand the model exactly what the live bot reads: simulator frame -> Slippi events
(melee_llm.sim.slippi.Encoder) -> play.RawFrames' parsers.

    cd train && uv run python -m pytest tests/test_rl_env.py
"""
import sys
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("melee_sim")
from meleebot.rl.env import DATA_DIR, SelfPlay, random_matchup, to_inputs  # noqa: E402
from meleebot.schema import CHARACTERS, FRAME  # noqa: E402
from meleebot.play import RawFrames  # noqa: E402

if not DATA_DIR.exists():
    pytest.skip("no melee-sim-light game data", allow_module_level=True)
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
slippi = pytest.importorskip("melee_llm.sim.slippi")

from melee_llm.sim.state import SIM_STAGE  # noqa: E402

CHARS = ("YOSHI", "FOX", "MARTH", "PUFF", "ICS")  # ICS: the follower must not leak into the frames


def events(raw: bytes):
    i = 0
    while i < len(raw):
        code = raw[i]
        size = raw[i + 1] if code == 0x35 else slippi.SIZES[code]
        yield code, raw[i:i + 1 + size]
        i += 1 + size


def reference(enc, obs, row):
    """FRAME records (2,) from Slippi events, as play.RawFrames builds them in a live game."""
    players, pads = {}, {}
    for code, b in events(enc.frame(obs, row)):
        if code in (slippi.PRE, slippi.POST) and b[0x6] == 0:
            (pads if code == slippi.PRE else players)[b[0x5]] = (RawFrames._pad if code == slippi.PRE else RawFrames._player)(b)
    out = np.zeros(2, FRAME)
    for me in (0, 1):
        out[me]["me"], out[me]["opp"] = players[me], players[1 - me]
        if row is not None:
            out[me]["me_pad"], out[me]["opp_pad"] = pads[me], pads[1 - me]
    return out


def test_frames_match_live_parsing():
    rng = np.random.default_rng(1)
    env = SelfPlay(4, lambda r: random_matchup(r, CHARS, CHARS), seed=3, max_frame=1000)  # short timer: matches restart
    centers = np.stack(np.meshgrid(np.arange(-80, 81, 20), np.arange(-80, 81, 20)), -1).reshape(-1, 2).astype(np.float32)
    encoders = [None] * env.n
    inputs = np.zeros((env.n, 2), env.env.raw_action_view.dtype["players"].base)
    choice = None
    compared = 0
    for t in range(3000):
        if t % 6 == 0:  # hold each input a few frames so characters actually fight and die
            choice = {"stick": rng.integers(0, len(centers), (env.n, 2)), "cstick": rng.integers(0, 9, (env.n, 2)),
                      "buttons": rng.integers(0, 32, (env.n, 2)) * (rng.random((env.n, 2)) < 0.3),
                      "shoulder": rng.integers(0, 3, (env.n, 2))}
        to_inputs(choice, centers, inputs)
        frames, done, fresh = env.step(inputs)
        for i in range(env.n):
            if fresh[i] or encoders[i] is None:
                stage = next(s for s, v in SIM_STAGE.items() if v == int(env.env.current_frame[i]["stage_id"]))
                encoders[i] = slippi.Encoder(stage, [1, 2])
                encoders[i].frame(env.env.current_frame[i], None)  # game start + entry frame
                continue
            want = reference(encoders[i], env.env.current_frame[i], env.env.raw_action_view[env.env.t - 1][i])
            got = frames[i]
            for me in (0, 1):
                for part in ("me", "opp", "me_pad", "opp_pad"):
                    for k in FRAME[part].names:
                        a, b = got[me][part][k], want[me][part][k]
                        assert np.array_equal(a, b) or np.allclose(np.float32(a), np.float32(b), equal_nan=True), \
                            (t, i, me, part, k, a, b)
            compared += 1
    assert compared > 10000
    assert env.games > env.n  # some matches ended and restarted
    assert {CHARACTERS[c] for c in env.chars.ravel()} <= set(CHARS)


def test_actor_matches_full_windows():
    """Ring-cached batched steps across game restarts give what play.Policy computes for each game on its own."""
    import torch
    from meleebot import features as fe
    from meleebot.model import load
    from meleebot.rl.policy import Actor

    ck_path = Path.home() / "projects/ai/melee-llm/data/train/runs/bc-20m-ft/last.pt"
    if not ck_path.exists():
        pytest.skip("no bc-20m-ft checkpoint")
    model, ck = load(ck_path, "cpu")
    env = SelfPlay(2, lambda r: random_matchup(r, CHARS, CHARS), seed=5, max_frame=300)
    delay, C = 3, model.config.context
    actor = Actor(model, ck, [0, 1], 0, delay=delay, device="cpu")
    rng = np.random.default_rng(0)
    inputs = np.zeros((env.n, 2), env.env.raw_action_view.dtype["players"].base)
    frames, fid = env.frames.copy(), env.frame_id.copy()
    log = []  # (frame copy, frame id, chars, stage, hidden) per step
    for t in range(700):
        start, active = fid == 0, fid >= 0
        tok = actor.tokens(frames[:, 0], start, env.chars, env.stage)
        h = actor.hidden(tok, start, active)
        log.append((frames[:, 0].copy(), fid.copy(), env.chars.copy(), env.stage.copy(), h.clone()))
        choice = {"stick": rng.integers(0, 40, (2, 2)), "cstick": rng.integers(0, 9, (2, 2)),
                  "buttons": rng.integers(0, 32, (2, 2)), "shoulder": rng.integers(0, 3, (2, 2))}
        to_inputs(choice, actor.centers, inputs)
        f, done, fresh = env.step(inputs)
        frames, fid = f.copy(), env.frame_id.copy()
    checked = 0
    for i in range(2):
        steps = [s for s in log if s[1][i] >= 0]
        games, cur = [], []
        for s in steps:  # split at frame 0
            if s[1][i] == 0 and cur:
                games.append(cur); cur = []
            cur.append(s)
        games.append(cur)
        assert len(games) >= 2
        for g in games:  # reference: play.Policy's way, the game alone, one Cache step per frame
            fr = np.concatenate([np.repeat(g[0][0][i:i + 1], delay, 0), np.stack([s[0][i] for s in g])])
            num, actions = fe.assemble(fe.frame_parts(fr, model.config.features), delay + np.arange(len(g)), delay)
            cond = {k: torch.as_tensor([v]) for k, v in dict(me_char=g[0][2][i, 0], opp_char=g[0][2][i, 1],
                    stage=g[0][3][i], delay=delay, rank=actor.rank, win=actor.win).items()}
            caches = model.new_caches()
            for t in range(len(g)):
                b = dict(num=torch.as_tensor(num[t:t + 1])[None], actions=torch.as_tensor(actions[t:t + 1])[None], **cond)
                with torch.no_grad():
                    want = model.trunk(b, torch.as_tensor([t]), caches)[0, -1]
                assert torch.allclose(g[t][4][i], want, atol=1e-4), (i, t, float((g[t][4][i] - want).abs().max()))
                checked += 1
    assert checked >= 800
