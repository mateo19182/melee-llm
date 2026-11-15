"""Slippi replays (.slp) of chosen simulator matches, for watching training in Slippi Lab or the Launcher.

Frames go through melee_llm.sim.slippi.Encoder, the same events the simulator's learned-bot games produce."""
import struct
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from melee_llm.sim.slippi import Encoder  # noqa: E402
from melee_llm.sim.state import SIM_STAGE  # noqa: E402

STAGE = {v: k for k, v in SIM_STAGE.items()}


def _ubjson_str(s: str) -> bytes:
    b = s.encode()
    return b"SU" + bytes([len(b)])  + b


def write_slp(path: Path, raw: bytes, last_frame: int) -> None:
    meta = (b"U\x07startAt" + _ubjson_str(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
            + b"U\x09lastFrame" + b"l" + struct.pack(">i", last_frame)
            + b"U\x08playedOn" + _ubjson_str("melee-sim-light"))
    path.write_bytes(b"{U\x03raw[$U#l" + struct.pack(">I", len(raw)) + raw + b"U\x08metadata{" + meta + b"}}")


class Recorder:
    """Records the next whole game of match `i` when `arm(i, name)` is called; writes it to out_dir on its end."""

    def __init__(self, env, out_dir):
        self.env, self.out = env, Path(out_dir)
        self.out.mkdir(parents=True, exist_ok=True)
        self.armed, self.live = {}, {}   # i -> name; i -> (name, encoder, chunks)

    def arm(self, i, name):
        if i not in self.live:
            self.armed[i] = name

    def after_step(self, done, fresh):
        """Call right after env.step; returns paths written this step."""
        e, written = self.env.env, []
        for i in list(self.armed):
            if fresh[i]:
                obs = e.current_frame[i]
                enc = Encoder(STAGE[int(obs["stage_id"])], [1, 2])
                self.live[i] = (self.armed.pop(i), enc, [enc.frame(obs, None)])
        for i, (name, enc, chunks) in list(self.live.items()):
            if fresh[i]:
                continue
            obs = e.current_frame[i]
            chunks.append(enc.frame(obs, e.raw_action_view[e.t - 1][i]))
            if done[i]:
                chunks.append(enc.game_end())
                path = self.out / f"{time.strftime('%Y%m%dT%H%M%S')}-{name}.slp"
                write_slp(path, b"".join(chunks), int(obs["frame_id"]))
                written.append(path)
                del self.live[i]
        return written
