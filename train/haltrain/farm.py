"""Many Melee games at once in the simulator, played by HAL's model on both sides (docs/simulator.md).

    python -m haltrain.farm "hal:AMSA#0,return_target=40,delay=10" hal:MASTER/FOX --games 64 [--lanes 64] [--out DIR]

A player is a HAL spec as the league writes it: `hal:IDENTITY[,return_target=N][,temperature=T][,delay=N][,run=NAME]`
and `/CHARACTER` (default Yoshi). The first player takes port 1 on even lanes and port 2 on odd ones; stages cycle
over the six legal ones. Every game is played to its end (or the 8-minute timer), so short games are not
over-counted. Players that share weights and delay share one model and one batch. Rules are stomped's: 4 stocks,
8 minutes, no items, no UCF (--ucf turns it on, as on Slippi).

With --out, DIR/results.jsonl gets one row per game (the league log's keys) and DIR/frames/ one .npz per game with
every frame as the simulator adapter packs it: HAL's 71 observation columns, both controllers and the reward.

The simulator is our fork, melee-brute, at d3832724 or later (the observation layout HAL's adapter needs):
$MELEE_SIM is a checkout with `make python-library` done, and $HAL_NATIVE_LIBRARY is HAL's adapter compiled against
it (`python -m hal.sim.native_build --native-source $MELEE_SIM --output $HAL_NATIVE_LIBRARY`, in vendor/hal).
"""
import argparse
import dataclasses
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

from . import HAL, REPO, WEIGHTS

SIM = Path(os.environ.get("MELEE_SIM", "/mnt/data/melee/native/melee-brute"))
os.environ.setdefault("HAL_NATIVE_LIBRARY", "/mnt/data/melee/native/libhal_native.so")
sys.path.insert(0, str(SIM))
RUNS = REPO / "data/train/runs"
STAGES = ["BATTLEFIELD", "FINAL_DESTINATION", "YOSHIS_STORY", "DREAMLAND", "FOUNTAIN_OF_DREAMS", "POKEMON_STADIUM"]
TIMER = 8 * 60 * 60  # frames; Slippi's 8-minute timer


@dataclasses.dataclass(frozen=True)
class Player:
    name: str
    character: str
    identity: str
    desired_return: float | None  # None: the model's own 90th percentile, HAL's default
    temperature: float
    delay: int
    weights: Path

    @classmethod
    def parse(cls, name):
        spec, _, character = name.partition("/")
        kind, _, arg = spec.partition(":")
        if kind != "hal":
            raise ValueError(f"{name}: only hal: players run in the farm")
        identity, *options = arg.split(",")
        o = dict(x.split("=", 1) for x in options)
        target = o.get("return_target", "p90")
        return cls(name, character or "YOSHI", identity, None if target == "p90" else float(target),
                   float(o.get("temperature", 1.0)), int(o.get("delay", 0)),
                   RUNS / o["run"] / "last.hal" if "run" in o else WEIGHTS)


class Brain:
    """One model playing every (lane, port) of the players that share its weights and delay."""

    def __init__(self, weights, delay, seats, compiled):
        from hal.eval.policy import PolicyBatchAdapter, PolicySettings
        from hal.eval.scheduling import FrameTiming
        from hal.inference.action_sequence_artifact import load_action_sequence_policy
        from hal.inference.api import RuntimeConfig

        timing = FrameTiming(delay, 0, delay, min(2, 12 - delay), min(delay + 4, 12))  # as melee_llm/bots/bot_hal.py
        policy = load_action_sequence_policy(weights, device="cuda", seed=0, compiled=compiled,
                                             history_mode="kv_cache", kv_update_frames=2)
        policy.spec = dataclasses.replace(policy.spec, supported_transport_delays=tuple(
            sorted({*policy.spec.supported_transport_delays, delay})))
        runtime = RuntimeConfig(len(seats), (delay,), replan_interval_frames=timing.replan_interval_frames)
        policy.prepare_prediction(runtime, timing.prediction_horizon_frames, timing.fixed_prefix_frames)
        settings = {slot: PolicySettings(p.identity, policy.return_p90 if p.desired_return is None else p.desired_return,
                                         p.temperature) for slot, p in seats.items()}

        class Adapter(PolicyBatchAdapter):
            def _ingest_one(self, slot, frame):  # upstream picks settings per port; here each seat has its own
                self.default_settings = settings[slot]
                # Upstream raises when the action the game reports differs from the one sent. Without UCF the
                # simulator reports a few near-cardinal stick values differently, so skip the check, as
                # melee_llm/bots/bot_hal.py does for live games.
                state = self._states.get(slot)
                if state is not None:
                    state.expected_applied.pop(frame.frame_id, None)
                return super()._ingest_one(slot, frame)

        self.adapter, self.seats = Adapter(policy, runtime, timing), seats

    def act(self, rows):
        return self.adapter._step({slot: rows[slot] for slot in self.seats if slot in rows})


def play(a, b, games, lanes=64, out=None, compiled=True, seed=0, ucf=False):
    """Play `games` games of a against b. Returns the result rows; a's score is 1 for a win, 0.5 for a draw."""
    import melee
    from hal.controller import controller_to_action_vec
    from hal.sim.native import NativeMatch, NativePlayer, NativeRolloutBatch
    from hal.sim.rollout import ObservationRow, Slot

    lanes = min(lanes, games)
    a_port = [1 + lane % 2 for lane in range(lanes)]
    seats = {}
    for lane in range(lanes):
        for port in (1, 2):
            player = a if port == a_port[lane] else b
            seats.setdefault((player.weights, player.delay), {})[Slot(lane, port)] = player
    brains = [Brain(weights, delay, s, compiled) for (weights, delay), s in seats.items()]

    def match(lane, game):
        chars = (a.character, b.character) if a_port[lane] == 1 else (b.character, a.character)
        return NativeMatch(stage=int(melee.Stage[STAGES[game % len(STAGES)]].value), seed=seed + game, max_frame=TIMER,
                           ucf_cardinals_1_0_enabled=ucf,
                           players=tuple(NativePlayer(port=i + 1, character=int(melee.Character[c].value))
                                         for i, c in enumerate(chars)))

    if out:
        (Path(out) / "frames").mkdir(parents=True, exist_ok=True)
    writer, results, started = ThreadPoolExecutor(2), [], time.monotonic()
    with NativeRolloutBatch(HAL.parent / "melee-sim-light/data", lanes) as sim:
        game = list(range(lanes))  # the game each lane is playing
        active, next_game, frames = np.ones(lanes, bool), lanes, 0
        frame = sim.reset([match(lane, game[lane]) for lane in range(lanes)], active)
        tape = np.empty((lanes, TIMER + 200), dtype=frame.records.dtype)
        length = np.zeros(lanes, int)

        def record(which):
            for lane in np.flatnonzero(which):
                tape[lane, length[lane]] = frame.records[lane]
                length[lane] += 1

        record(active)
        while active.any():
            columns = {k: v.tolist() for k, v in frame.columns.items()}
            rows = {}
            for lane in np.flatnonzero(active):
                flat = {k: v[lane] for k, v in columns.items()}
                for port in (1, 2):
                    rows[Slot(int(lane), port)] = ObservationRow(
                        int(frame.frame_id[lane]), flat, np.array(frame.applied_action[lane, port - 1]),
                        reset=bool(frame.reset[lane]))
            actions = np.zeros((lanes, 2, 14), np.float32)
            for brain in brains:
                for slot, action in brain.act(rows).items():
                    actions[slot.match, slot.port - 1] = controller_to_action_vec(action)
            frame = sim.step(actions, active)
            frames += int(active.sum())
            record(active)
            over = active & (frame.terminated | frame.truncated)
            if not over.any():
                continue
            restart = np.zeros(lanes, bool)
            for lane in np.flatnonzero(over):
                mine, theirs = (1, 2) if a_port[lane] == 1 else (2, 1)
                stocks = [int(frame.columns[f"p{p}_stock"][lane]) for p in (mine, theirs)]
                percent = [float(frame.columns[f"p{p}_percent"][lane]) for p in (mine, theirs)]
                lead = (stocks[0] - stocks[1]) or (percent[1] - percent[0])  # timer: stocks, then the lower percent
                row = dict(time=time.time(), a=a.name, b=b.name, a_char=a.character, b_char=b.character,
                           stage=STAGES[game[lane] % len(STAGES)], score=0.5 if lead == 0 else float(lead > 0),
                           stocks_a=stocks[0], stocks_b=stocks[1], frames=int(length[lane]) - 1, a_port=mine,
                           seed=seed + game[lane], timeout=not bool(frame.terminated[lane]), sim=True)
                if out:
                    row["tape"] = f"frames/{game[lane]:05d}.npz"
                    writer.submit(np.savez_compressed, Path(out) / row["tape"], records=tape[lane, :length[lane]].copy())
                    with open(Path(out) / "results.jsonl", "a") as log:
                        log.write(json.dumps(row) + "\n")
                results.append(row)
                print(f"{a.name} vs {b.name} on {row['stage']}: {row['score']} ({stocks[0]}-{stocks[1]} stocks, "
                      f"{row['frames']} frames)", flush=True)
                length[lane] = 0
                if next_game < games:
                    game[lane], next_game, restart[lane] = next_game, next_game + 1, True
                else:
                    active[lane] = False
            if restart.any():
                frame = sim.reset([match(lane, game[lane]) for lane in range(lanes)], restart)
                record(restart)
    writer.shutdown()
    wall = time.monotonic() - started
    score = sum(r["score"] for r in results)
    print(f"{a.name}: {score:g} of {len(results)} against {b.name}; {frames:,} frames in {wall / 60:.1f} min "
          f"({frames / wall:,.0f} a second)", flush=True)
    return results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("a")
    ap.add_argument("b")
    ap.add_argument("--games", type=int, default=64)
    ap.add_argument("--lanes", type=int, default=64)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--no-compile", action="store_true")
    ap.add_argument("--ucf", action="store_true")
    args = ap.parse_args()
    play(Player.parse(args.a), Player.parse(args.b), args.games, args.lanes, args.out, not args.no_compile, args.seed,
         args.ucf)


if __name__ == "__main__":
    main()
