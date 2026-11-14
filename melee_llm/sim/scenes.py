"""Reach a situation in a simulator match with plain controller inputs, and save it.

Each scene resets the world (game RNG seed 0), drives `port` there with inputs and returns a Snapshot: restore
it as often as needed. The positions are Battlefield's, from port 1's spawn on the left platform.
"""
from __future__ import annotations

from collections.abc import Callable

import melee
from melee import Action as A
from melee import Button as B

from melee_llm.sim.world import Snapshot, World


def until(world: World, done: Callable[[melee.GameState, melee.PlayerState], bool], port: int = 1,
          limit: int = 600) -> melee.GameState:
    """Step until `done(gs, player)`, holding whatever is pressed."""
    for _ in range(limit):
        gs = world.step()
        if done(gs, gs.players[port]):
            return gs
    raise TimeoutError(f"scene condition not reached in {limit} frames")


def _stick(world: World, port: int, x: float) -> None:
    world.controllers[port].tilt_analog(B.BUTTON_MAIN, x, 0.5)


def actionable(world: World, port: int = 1) -> Snapshot:
    """The countdown is over and the player stands where they spawned."""
    world.reset(0)
    until(world, lambda gs, me: gs.frame >= 0 and me.action == A.STANDING, port)
    return world.save()


def center(world: World, port: int = 1) -> Snapshot:
    """Standing at the middle of the main stage, facing right."""
    actionable(world, port)
    _stick(world, port, 1.0)  # walking stops at the platform's edge; running goes off it
    until(world, lambda gs, me: me.on_ground and me.position.y < 1, port)
    until(world, lambda gs, me: me.position.x > -2, port)
    _stick(world, port, 0.5)
    until(world, lambda gs, me: me.action == A.STANDING, port)
    return world.save()


def dashing(world: World, port: int = 1) -> Snapshot:
    """A few frames into a dash to the right from the middle of the stage."""
    center(world, port)
    _stick(world, port, 1.0)
    until(world, lambda gs, me: me.action == A.DASHING and me.action_frame >= 3, port)
    return world.save()


def ledge(world: World, port: int = 1) -> Snapshot:
    """Hanging on the left ledge: face the stage near the edge, hop, and drift back off it (drift never turns).
    Saved on the first hanging frame with the stick still held away, as after a recovery: Melee ignores the stick
    on the ledge until it has been neutral."""
    center(world, port)
    _stick(world, port, 0.2)
    until(world, lambda gs, me: me.position.x < -58, port)
    _stick(world, port, 0.5)
    until(world, lambda gs, me: me.action == A.STANDING, port)
    _stick(world, port, 0.65)
    until(world, lambda gs, me: me.facing, port)
    _stick(world, port, 0.5)
    until(world, lambda gs, me: me.action == A.STANDING, port)
    world.controllers[port].press_button(B.BUTTON_Y)
    world.step()
    world.controllers[port].release_button(B.BUTTON_Y)
    _stick(world, port, 0.0)
    until(world, lambda gs, me: me.action == A.EDGE_HANGING, port)
    return world.save()
