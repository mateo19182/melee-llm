"""Play agents against each other in melee-sim-light: Melee's gameplay code from the decompilation, with no
Dolphin, no menus and no rendering, as fast as the agents answer. Same contract as runner.play: agents
get setup/ready/on_game_start/begin/step/on_game_end, and the result is a list of GameResults.

Differences from Dolphin (docs/simulator.md): no in-game CPU, no learned bots (they read the raw Slippi
stream), no replays, no ECB or powershield flag in the GameState, and `hitstun_frames_left` is 0 outside
hitstun (libmelee shows whatever Melee keeps in that slot). The game's RNG is not Dolphin's, so a given
seed and inputs replay identically here but not on Dolphin.
"""
from __future__ import annotations

import os
import random
import time
from pathlib import Path
from typing import Callable

import melee

from melee_llm import matches
from melee_llm.agents.base import Agent
from melee_llm.paths import VENDOR
from melee_llm.sim.controller import SimController
from melee_llm.sim.state import SIM_STAGE, StateBuilder

DATA_DIR = Path(os.environ.get("MSL_DATA_DIR", VENDOR / "melee-sim-light/data"))
TIMER_FRAMES = 8 * 60 * 60  # Slippi's 8-minute timer
_RING = 1024  # frames per buffer pass; the cursor wraps


def _check_agents(agents: dict[int, Agent]) -> None:
    from melee_llm.bots.agent import BotAgent as LearnedBot
    for p, a in agents.items():
        if a.cpu_level:
            raise ValueError(f"port {p}: the simulator has no in-game CPU")
        if isinstance(a, LearnedBot):
            raise ValueError(f"port {p}: learned bots read the Slippi event stream, which the simulator does not produce")


def play(agents: dict[int, Agent], stage: melee.Stage = melee.Stage.BATTLEFIELD, games: int = 1,
         seed: int | None = None, observer: Callable[[str, dict], None] | None = None,
         meta: dict | None = None) -> list:
    """Run `games` games. `seed` fixes the game RNG of game 0 (game i uses seed + i); None picks one."""
    import melee_sim as msl

    from melee_llm.runner import GameResult, _result

    notify = observer or (lambda event, info: None)
    assert len(agents) == 2, "two ports for now"
    _check_agents(agents)
    if stage not in SIM_STAGE:
        raise ValueError(f"{stage.name} is not a legal stage in the simulator")
    ports = sorted(agents)
    controllers = {p: SimController(p) for p in ports}
    seed = random.getrandbits(32) if seed is None else seed
    pub = matches.publisher(agents, stage, "sim", games, 0, None, {"source": "sim", **(meta or {})})
    results: list[GameResult] = []
    error = None
    env = msl.EnvBatch(batch_size=1, length=_RING, action_format="raw", data_dir=str(DATA_DIR))
    try:
        for p, a in agents.items():
            a.setup(controllers[p], p, next(q for q in ports if q != p))
        for a in agents.values():
            a.ready()
        stepping = [agents[p] for p in ports]
        for game in range(games):
            env.configure_match(stage=SIM_STAGE[stage], seed=(seed + game) % 2**32, max_frame=TIMER_FRAMES,
                                players=tuple(msl.PlayerConfig(agents[p].character.value, controller_port=p - 1,
                                                               costume=agents[p].costume) for p in ports))
            env.reset_all()
            builder = StateBuilder(stage, ports, {p: agents[p].costume for p in ports})
            gs, row = builder.build(env.current_frame[0]), None
            for c in controllers.values():
                c.release_all()
                c.flush()
            for a in agents.values():
                a.on_game_start(gs, None)
            if pub:
                pub.game_start(game, gs, None)
            notify("game_start", {"game": game, "replay": None, "gs": gs})
            frames, t0 = 0, time.time()
            while True:
                frames += 1
                for a in stepping:
                    a.begin(gs)
                for a in stepping:
                    a.step(gs)
                if pub:
                    pub.frame(gs)
                if observer:
                    observer("frame", {"gs": gs})
                if env.t >= env.length:
                    env.reset_cursor()
                row = env.raw_action_view[env.t, 0]
                for i, p in enumerate(ports):
                    controllers[p].raw_input(row["players"][i])
                    controllers[p].flush()
                t = env.t
                env.step()
                gs = builder.build(env.current_frame[0], row)
                if env.terminal_view[t, 0]["done"]:
                    break
            results.append(_result(gs, frames, t0, agents))
            for a in agents.values():
                a.on_game_end(gs)
            if pub:
                pub.game_end(game, results[-1])
            notify("game_end", {"game": game, "result": results[-1]})
        return results
    except BaseException as e:
        error = e
        raise
    finally:
        for a in agents.values():
            a.close()
        env.close()
        if pub:
            pub.close(error)
