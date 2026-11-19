"""HAL in the farm: HAL's batched evaluator adapter playing every seat of one checkpoint and delay.

Runs in vendor/hal's venv (farm.remote), working directory vendor/hal. Each seat reads what the live bot
(melee_llm/bots/bot_hal.py) reads: HAL's canonical frame of the seat's GameState, projected to the policy's columns,
plus the action the game applied. Settings per seat (identity, return target, temperature) follow the HAL farm
(train/haltrain/farm.py), and so does one difference from the live bot: the executed-action check is skipped,
because without UCF the simulator reports a few near-cardinal stick values differently from what was sent.
"""
import dataclasses

import numpy as np

from .common import Brain

WEIGHTS = "weights/hal-250m.hal"
MAX_DELAY = 11


class HALBrain(Brain):
    """Spec `hal:IDENTITY[,return_target=N|p90][,temperature=T][,delay=N]`; IDENTITY a connect code in the vocabulary
    (e.g. AMSA#0) or a rank (MASTER)."""

    from_events = True  # HAL's libmelee fork reads its observations from the parsed Slippi events

    def __init__(self, spec, seats, seed=0, check=False, compiled=True):
        super().__init__(seats, check)
        import melee
        from hal.controller import POLICY_BUTTON_MASK
        from hal.eval.policy import PolicyBatchAdapter, PolicySettings
        from hal.eval.scheduling import FrameTiming
        from hal.inference.action_sequence_artifact import load_action_sequence_policy
        from hal.inference.api import RuntimeConfig
        from hal.inference.engine import configure_inference_process, freeze_inference_runtime
        from hal.sim.rollout import Slot
        from hal.wire import BUTTON_BITS

        identity, *options = spec.partition(":")[2].split(",")
        o = dict(x.split("=", 1) for x in options)
        delay = int(o.get("delay", 0))
        if not 0 <= delay <= MAX_DELAY:
            raise ValueError(f"delay must be 0..{MAX_DELAY}")
        configure_inference_process()
        # As bot_hal.Bot: the same timing, cache and prediction settings, with one slot per seat.
        timing = FrameTiming(delay, 0, delay, min(2, 12 - delay), min(delay + 4, 12))
        policy = load_action_sequence_policy(o.get("weights", WEIGHTS), device="cuda", seed=seed, compiled=compiled,
                                             history_mode="kv_cache", kv_update_frames=2)
        policy.spec = dataclasses.replace(policy.spec, supported_transport_delays=tuple(
            sorted({*policy.spec.supported_transport_delays, delay})))
        runtime = RuntimeConfig(len(self.seats), (delay,), replan_interval_frames=timing.replan_interval_frames)
        policy.prepare_prediction(runtime, timing.prediction_horizon_frames, timing.fixed_prefix_frames)
        target = o.get("return_target", "p90")
        settings = PolicySettings(identity.upper() if identity.upper() in ("PLATINUM", "DIAMOND", "MASTER")
                                  else identity, policy.return_p90 if target == "p90" else float(target),
                                  float(o.get("temperature", 1.0)))

        class Adapter(PolicyBatchAdapter):
            def _ingest_one(self, slot, frame):
                state = self._states.get(slot)
                if state is not None:
                    state.expected_applied.pop(frame.frame_id, None)
                return super()._ingest_one(slot, frame)

        self.adapter = Adapter(policy, runtime, timing, desired_return=settings.desired_return)
        self.adapter.default_settings = settings
        self.fields = policy.spec.required_observation_fields
        self.slots = [Slot(lane, port) for lane, port in self.seats]
        self.buttons = {bit: melee.enums.Button[f"BUTTON_{name.upper()}"] for name, bit in BUTTON_BITS.items()
                        if bit & POLICY_BUTTON_MASK}
        freeze_inference_runtime()

    def reader(self, port):
        from hal.controller import controller_to_action_vec
        from hal.eval.observations import applied_action_from_frame
        from hal.representation.observations import flatten_canonical_frame, project_observation_columns
        from hal.sim.session import canonical_frame

        def read(gs):
            frame = canonical_frame(gs)
            ports = frame["ports"]  # as bot_hal: the matchup supplies the character and stage columns
            frame["_matchup"] = {"stage": frame["stage"],
                                 "character": {p: int(ports[p]["leader"]["post"]["character"]) for p in (1, 2)}}
            columns = project_observation_columns(flatten_canonical_frame(frame), self.fields)
            return int(frame["id"]), columns, controller_to_action_vec(applied_action_from_frame(frame, port))
        return read

    def decide(self, states, frame):
        import melee
        from hal.sim.rollout import ObservationRow

        readers = {}
        rows = {}
        for i, (lane, port) in enumerate(self.seats):
            if lane not in states:
                continue
            read = readers.setdefault(port, self.reader(port))
            self.last_read[i] = frame_id, columns, applied = read(states[lane])
            rows[self.slots[i]] = ObservationRow(frame_id, columns, np.asarray(applied),
                                                 reset=bool(frame.fresh[lane]))
        due = self.adapter._step(rows)
        B = melee.enums.Button
        for i, slot in enumerate(self.slots):
            action = due.get(slot)
            if action is None:
                continue
            c = self.controllers[i]
            # As bot_hal: HAL sticks are signed [-1, 1].
            c.tilt_analog(B.BUTTON_MAIN, (action.main_x + 1) / 2, (action.main_y + 1) / 2)
            c.tilt_analog(B.BUTTON_C, (action.c_x + 1) / 2, (action.c_y + 1) / 2)
            c.press_shoulder(B.BUTTON_L, action.trigger_l)
            c.press_shoulder(B.BUTTON_R, action.trigger_r)
            for bit, button in self.buttons.items():
                (c.press_button if action.buttons & bit else c.release_button)(button)
