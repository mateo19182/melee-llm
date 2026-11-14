"""Play agents against each other in melee-sim-light: Melee's gameplay code from the decompilation, with no
Dolphin, no menus and no rendering, as fast as the agents answer. Same contract as runner.play: agents
get setup/ready/on_game_start/begin/step/on_game_end, and the result is a list of GameResults.

Differences from Dolphin (docs/simulator.md): no in-game CPU, no learned bots (they read the raw Slippi
stream), no replays, no ECB or powershield flag in the GameState, and `hitstun_frames_left` is 0 outside
hitstun (libmelee shows whatever Melee keeps in that slot). The game's RNG is not Dolphin's, so a given
seed and inputs replay identically here but not on Dolphin.
"""
from __future__ import annotations

import random
import time
from typing import Callable

import melee

from melee_llm import matches
from melee_llm.agents.base import Agent
from melee_llm.sim.state import SIM_STAGE
from melee_llm.sim.world import TIMER_FRAMES, World


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
    from melee_llm.runner import GameResult, _result

    notify = observer or (lambda event, info: None)
    assert len(agents) == 2, "two ports for now"
    _check_agents(agents)
    if stage not in SIM_STAGE:
        raise ValueError(f"{stage.name} is not a legal stage in the simulator")
    ports = sorted(agents)
    seed = random.getrandbits(32) if seed is None else seed
    pub = matches.publisher(agents, stage, "sim", games, 0, None, {"source": "sim", **(meta or {})})
    results: list[GameResult] = []
    error = None
    world = World({p: agents[p].character for p in ports}, stage, seed, {p: agents[p].costume for p in ports},
                  max_frame=TIMER_FRAMES)
    try:
        for p, a in agents.items():
            a.setup(world.controllers[p], p, next(q for q in ports if q != p))
        for a in agents.values():
            a.ready()
        stepping = [agents[p] for p in ports]
        for game in range(games):
            gs = world.reset(seed + game)
            for a in agents.values():
                a.on_game_start(gs, None)
            if pub:
                pub.game_start(game, gs, None)
            notify("game_start", {"game": game, "replay": None, "gs": gs})
            frames, t0 = 0, time.time()
            while not world.done:
                frames += 1
                for a in stepping:
                    a.begin(gs)
                for a in stepping:
                    a.step(gs)
                if pub:
                    pub.frame(gs)
                if observer:
                    observer("frame", {"gs": gs})
                gs = world.step()
            results.append(_result(gs, frames, t0, agents))
            for a in agents.values():
                a.on_game_end(gs)
            if pub:
                pub.game_end(game, results[-1])
            notify("game_end", {"game": game, "result": results[-1], "gs": gs})
        return results
    except BaseException as e:
        error = e
        raise
    finally:
        for a in agents.values():
            a.close()
        world.close()
        if pub:
            pub.close(error)
