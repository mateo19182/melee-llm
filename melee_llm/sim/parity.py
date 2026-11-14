"""Check the adapter against libmelee: replay a Dolphin .slp's raw inputs through melee_sim and compare the
GameState StateBuilder makes with the one libmelee's Console parses from the same replay, frame by frame.

melee_sim's RNG runs free (Dolphin's is also advanced outside gameplay), so a replay stays in sync only
until the first random choice that comes out differently. Comparison stops at the first frame where
position or action differs; every field is compared on all frames before it.

    uv run python -m melee_llm.sim.parity replays/.../Game_*.slp
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

import numpy as np

from melee_llm.runner import replay_states
from melee_llm.sim.state import SIM_STAGE, StateBuilder

FIELDS = ("character", "action", "action_frame", "facing", "percent", "shield_strength", "stock", "hitstun_frames_left",
          "hitlag_left", "on_ground", "jumps_left", "invulnerable", "speed_air_x_self", "speed_ground_x_self",
          "speed_y_self", "speed_x_attack", "speed_y_attack", "moonwalkwarning", "off_stage")
CONTROLLER = ("button", "raw_main_stick", "c_stick")


def _inputs_from_replay(slp: Path):
    """Raw input rows (melee_sim layout) for every frame, from the replay's pre-frame events."""
    import peppi_py
    game = peppi_py.read_slippi(str(slp))
    pre = [p.leader.pre for p in game.frames.ports]
    cols = lambda a: np.asarray(a) if a is not None else None
    raw = [dict(buttons=cols(p.buttons_physical), main_x=cols(p.raw_analog_x), main_y=cols(p.raw_analog_y),
                c_x=cols(getattr(p, "raw_analog_cstick_x", None)), c_y=cols(getattr(p, "raw_analog_cstick_y", None)),
                cs_x=cols(p.cstick.x), cs_y=cols(p.cstick.y),
                l=cols(p.triggers_physical.l), r=cols(p.triggers_physical.r)) for p in pre]
    return game, np.asarray(game.frames.id), raw


def compare(slp: Path, verbose: bool = False) -> dict:
    import melee_sim as msl
    game, ids, raw = _inputs_from_replay(slp)
    ports = [int(p.port.value if hasattr(p.port, "value") else p.port) + 1 for p in game.start.players]
    truth = {gs.frame: gs for gs in replay_states(slp)}
    stage = next(iter(truth.values())).stage
    n = len(ids)
    from melee_llm.sim.world import DATA_DIR
    env = msl.EnvBatch(batch_size=1, length=n + 1, action_format="raw", data_dir=str(DATA_DIR))
    env.configure_match(stage=SIM_STAGE[stage], seed=game.start.random_seed,
                        players=tuple(msl.PlayerConfig(truth[ids[0]].players[p].character.value, controller_port=p - 1)
                                      for p in ports))
    env.reset_all()
    builder = StateBuilder(stage, ports)
    mismatches, compared, diverged = Counter(), 0, None
    examples = {}
    builder.build(env.current_frame[0])
    for t in range(n - 1):
        u = t + 1  # buffer row t produces the frame after the reset/current one
        row = env.raw_action_view[t, 0]
        for i, r in enumerate(raw):
            pr = row["players"][i]
            pr["buttons"] = r["buttons"][u]
            pr["main_x"] = r["main_x"][u]
            pr["main_y"] = r["main_y"][u] if r["main_y"] is not None else 0
            pr["c_x"] = r["c_x"][u] if r["c_x"] is not None else round(float(r["cs_x"][u]) * 80)
            pr["c_y"] = r["c_y"][u] if r["c_y"] is not None else round(float(r["cs_y"][u]) * 80)
            pr["l"], pr["r"] = round(float(r["l"][u]) * 140), round(float(r["r"][u]) * 140)
        env.step()
        gs = builder.build(env.current_frame[0], row)
        want = truth.get(gs.frame)
        if want is None:
            continue
        sync = all(abs(gs.players[p].position.x - want.players[p].position.x) < 1e-4
                   and abs(gs.players[p].position.y - want.players[p].position.y) < 1e-4
                   and gs.players[p].action == want.players[p].action for p in ports)
        if not sync:
            diverged = gs.frame
            break
        compared += 1
        for p in ports:
            a, b = gs.players[p], want.players[p]
            for f in FIELDS:
                va, vb = getattr(a, f), getattr(b, f)
                if not (va == vb or (isinstance(vb, (float, np.floating)) and abs(float(va) - float(vb)) < 1e-4)):
                    mismatches[f] += 1
                    examples.setdefault(f, (gs.frame, p, va, vb))
            for f in CONTROLLER:
                if getattr(a.controller_state, f) != getattr(b.controller_state, f):
                    mismatches["controller." + f] += 1
                    examples.setdefault("controller." + f, (gs.frame, p, getattr(a.controller_state, f), getattr(b.controller_state, f)))
        if abs(gs.distance - want.distance) > 1e-3:
            mismatches["distance"] += 1
        if len(gs.projectiles) != len(want.projectiles):
            mismatches["projectiles.count"] += 1
            examples.setdefault("projectiles.count", (gs.frame, None, len(gs.projectiles), len(want.projectiles)))
        else:
            for x, y in zip(sorted(gs.projectiles, key=lambda q: q.spawn_id), sorted(want.projectiles, key=lambda q: q.spawn_id)):
                for f in ("type", "owner", "subtype", "expiration_frames", "spawn_id"):
                    if getattr(x, f) != getattr(y, f):
                        mismatches["projectile." + f] += 1
                        examples.setdefault("projectile." + f, (gs.frame, None, getattr(x, f), getattr(y, f)))
                if abs(x.position.x - y.position.x) > 1e-4 or abs(x.speed.x - y.speed.x) > 1e-4:
                    mismatches["projectile.position/speed"] += 1
    env.close()
    return {"replay": str(slp), "frames": n, "compared": compared, "diverged_at": diverged,
            "mismatches": dict(mismatches), "examples": examples}


if __name__ == "__main__":
    for path in sys.argv[1:]:
        r = compare(Path(path))
        print(f"{Path(path).name}: compared {r['compared']}/{r['frames']} frames, diverged at {r['diverged_at']}")
        for f, k in sorted(r["mismatches"].items(), key=lambda kv: -kv[1]):
            print(f"  {f}: {k}  e.g. frame/port/sim/libmelee = {r['examples'].get(f)}")
