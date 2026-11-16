"""HAL 250M (ericyuegu/hal) inside vendor/hal/.venv (Python 3.14, HAL's own libmelee fork).

Reproduces `hal-policy play` (hal/scripts/policy.py:_play_local): cached KV inference, zero added
delay, replan every 2 frames with a 4-frame horizon, observed-action alignment.
"""
from __future__ import annotations

import dataclasses
import sys
from pathlib import Path

import melee

from hal.controller import POLICY_BUTTON_MASK, action_vec_to_controller, controller_to_action_vec
from hal.data.schema import Rank
from hal.eval.observations import applied_action_from_frame
from hal.eval.policy import PolicyBatchAdapter, PolicySettings
from hal.eval.scheduling import FrameTiming
from hal.inference.action_sequence_artifact import load_action_sequence_policy
from hal.inference.api import RuntimeConfig
from hal.inference.engine import configure_inference_process, freeze_inference_runtime
from hal.representation.observations import flatten_canonical_frame, project_observation_columns
from hal.sim.inputs import controller_action_readback, controller_actions_match
from hal.sim.rollout import ObservationRow, Slot
from hal.sim.session import canonical_frame
from hal.wire import BUTTON_BITS

WEIGHTS = Path("weights/hal-250m.hal")
BUTTON_NAMES = {bit: f"BUTTON_{name.upper()}" for name, bit in BUTTON_BITS.items() if bit & POLICY_BUTTON_MASK}
B = melee.enums.Button
MAX_DELAY = 10


class _Adapter(PolicyBatchAdapter):
    """HAL's evaluator adapter, with its executed-action check made non-fatal.

    Upstream raises if the action seen in the next frame differs from the one HAL sent. Open loop
    (replay tests) that is always true; live, we count mismatches instead of killing the match.
    """

    open_loop = False
    mismatches = 0

    def __call__(self, frame_index, obs):
        # Upstream feeds raw floats here; its shared-memory transport would cast them to the stored
        # column types, which the policy validates. Do that cast explicitly.
        fields = self.policy.spec.required_observation_fields
        rows = {slot: ObservationRow(int(frame["id"]),
                                     project_observation_columns(flatten_canonical_frame(frame), fields),
                                     controller_to_action_vec(applied_action_from_frame(frame, slot.port)),
                                     reset=frame.get("_reset", False))
                for slot, frame in obs.items()}
        return self._step(rows)

    def _ingest_one(self, slot, frame):
        state = self._states.get(slot)
        expected = state.expected_applied.get(frame.frame_id) if state is not None else None
        if expected is not None and (self.open_loop or not controller_actions_match(
                controller_action_readback(expected), action_vec_to_controller(frame.action))):
            del state.expected_applied[frame.frame_id]
            if not self.open_loop:
                self.mismatches += 1
                if self.mismatches <= 3:
                    print(f"hal: executed action differs from sent at frame {frame.frame_id}", file=sys.stderr)
        return super()._ingest_one(slot, frame)


class Bot:
    def __init__(self, init: dict):
        configure_inference_process()
        cfg = init["config"]
        self.port = init["port"]
        if {init["port"], init["opponent_port"]} != {1, 2}:
            raise ValueError("HAL's observation schema is fixed to ports 1 and 2")
        # delay: frames between choosing an action and the game reading it, beyond the usual one. The
        # actions already on their way are the fixed prefix; the model's contiguous heads reach 12 frames
        # ahead, so 10 is the most that still leaves a 2-frame replan.
        delay = int(cfg.get("delay", 0))
        if not 0 <= delay <= MAX_DELAY:
            raise ValueError(f"delay must be 0..{MAX_DELAY}")
        timing = FrameTiming(delay, 0, delay, 2, min(delay + 4, 12))
        self.policy = load_action_sequence_policy(
            cfg.get("weights", WEIGHTS), device="cuda", seed=cfg.get("seed"), compiled=cfg.get("compile", True),
            history_mode="kv_cache", kv_update_frames=2)
        if delay not in self.policy.spec.supported_transport_delays:  # the bundle declares only the delays it was qualified at
            self.policy.spec = dataclasses.replace(self.policy.spec, supported_transport_delays=tuple(
                sorted({*self.policy.spec.supported_transport_delays, delay})))
        runtime = RuntimeConfig(1, (delay,), replan_interval_frames=timing.replan_interval_frames)
        self.policy.prepare_prediction(runtime, timing.prediction_horizon_frames, timing.fixed_prefix_frames)
        self.adapter = _Adapter(self.policy, runtime, timing, desired_return=self.policy.return_p90)
        # ahead (train/meleebot/stomped.py): return the action just chosen, for frame + 1 + delay, instead of
        # the one due now. The caller delivers it to the game itself, `delay` frames early.
        self.ahead = bool(cfg.get("ahead")) and delay > 0
        self.slot = Slot(0, self.port)
        self.steer = {"identity": "IBDW#0", "return_target": "p90", "temperature": 1.0}
        self.active_identity = self.steer["identity"]
        self.last_frame = None
        freeze_inference_runtime()

    def info(self) -> dict:
        codes = sorted(self.policy.code_to_id)
        return {"model": str(WEIGHTS), "return_p90": self.policy.return_p90, "ranks": [r.name for r in Rank],
                "n_identities": len(codes), "identities_sample": codes[:40], "steer": dict(self.steer),
                "ranges": {"return_target": [-20, 140], "temperature": [0.8, 1.1]}}

    def _settings(self, steer: dict, identity: str | None) -> PolicySettings:
        target = steer["return_target"]
        desired = self.policy.return_p90 if target == "p90" else None if target is None else float(target)
        return PolicySettings(identity, desired, float(steer["temperature"]))  # validates the ranges

    def set_steer(self, steer: dict) -> dict:
        # Return target and temperature are read at every replan (<= 2 frames). The identity embedding
        # is fixed per KV stream, so a new identity waits for the next game.
        new = {**self.steer, **{k: v for k, v in steer.items() if k in self.steer}}
        if new["identity"] is not None:
            if new["identity"].upper() in Rank.__members__:
                new["identity"] = new["identity"].upper()
            self.policy._player_id(new["identity"])  # raises if not in the checkpoint vocabulary
        self._settings(new, new["identity"])
        self.steer = new
        if self.last_frame is None:
            self.active_identity = new["identity"]
        self.adapter.default_settings = self._settings(new, self.active_identity)
        return {**new, "identity_active": self.active_identity}

    def act(self, gs, controller, open_loop: bool) -> None:
        self.adapter.open_loop = open_loop
        new_game = self.last_frame is not None and gs.frame <= self.last_frame
        if new_game and self.active_identity != self.steer["identity"]:
            self.active_identity = self.steer["identity"]
            self.adapter.default_settings = self._settings(self.steer, self.active_identity)
        # a stream that skips frames (a reconnect replay) starts a new history instead of failing forever
        gap = self.last_frame is not None and gs.frame > self.last_frame + 1
        self.last_frame = gs.frame
        frame = canonical_frame(gs)
        frame["_reset"] = gap
        ports = frame["ports"]
        frame["_matchup"] = {"stage": frame["stage"],
                             "character": {p: int(ports[p]["leader"]["post"]["character"]) for p in (1, 2)}}
        action = self.adapter(0, {self.slot: frame})[self.slot]
        if self.ahead:
            action = self.adapter._states[self.slot].transport.pending[-1]
        # HAL sticks are signed [-1, 1]; the parent's libmelee Controller applies the same wire fix HAL does.
        controller.tilt_analog(B.BUTTON_MAIN, (action.main_x + 1) / 2, (action.main_y + 1) / 2)
        controller.tilt_analog(B.BUTTON_C, (action.c_x + 1) / 2, (action.c_y + 1) / 2)
        controller.press_shoulder(B.BUTTON_L, action.trigger_l)
        controller.press_shoulder(B.BUTTON_R, action.trigger_r)
        for bit, name in BUTTON_NAMES.items():
            (controller.press_button if action.buttons & bit else controller.release_button)(B[name])
