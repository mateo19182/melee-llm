"""Our own games as training data for HAL's model.

A .slp goes through HAL's own extraction to the per-frame columns its dataset stores, then through its return labels
and window code, so a batch is what the 059 loss expects. There are no shard files: a few thousand games fit in
memory, and unlike HAL's loaders this picks which side is the player.

    games = Games([(path, "p1", info), ...], stats)   # the port our bot played (p1 is the lower port), and
    batch, infos = games.sample(16, rng)              # anything to carry along per game, e.g. its delay

Normalisation uses the statistics stored in the model bundle, as training on HAL's own data does.
"""
import pickle
from pathlib import Path

import numpy as np

from . import AMSA, o59

CACHE = Path("/mnt/data/melee/own-games")  # extracted replays, one pickle per .slp


def _parse(path):
    """HAL's per-frame columns for a .slp. Dolphin leaves a torn last frame when it is killed mid-game; trim it."""
    from hal.data.extract import extract_policy_world_replay
    from hal.data.slp_finalize import trim_to_last_frame_bytes

    def read(p):
        try:
            return extract_policy_world_replay(str(p))
        except BaseException as error:  # peppi panics on a torn file, and a Rust panic is not an Exception
            if isinstance(error, KeyboardInterrupt):
                raise
            return None

    sample = read(path)
    if sample is None:
        trimmed = trim_to_last_frame_bytes(Path(path).read_bytes())
        if trimmed is not None:
            repaired = CACHE / "repair.slp"
            repaired.write_bytes(trimmed)
            sample = read(repaired)
            repaired.unlink()
    return sample


def from_tape(path):
    """HAL's per-frame columns for a game the farm saved (haltrain.farm --out): its 71 observation columns as they
    are, and both controllers from the actions the simulator applied on each frame."""
    from hal.data.schema import MDS_PER_FRAME_DTYPES, Rank
    from hal.sim.native import OBSERVATION_FIELDS
    from hal.wire import ACTION_CHANNELS, ITEM_OWNER_NONE, MASK_INT32

    records = np.load(path)["records"]
    words = records["columns"]
    sample = {name: np.ascontiguousarray(words[:, i]).view(np.dtype(MDS_PER_FRAME_DTYPES[name]))
              for i, name in enumerate(OBSERVATION_FIELDS)}
    sample["frame"] = records["frame_id"].astype(np.int32)
    for slot in range(4):  # the dataset also stores who threw each item; the model does not read it
        kind = sample[f"item{slot}_type"]
        sample[f"item{slot}_owner"] = np.where(kind == MASK_INT32, MASK_INT32, ITEM_OWNER_NONE).astype(np.int32)
    for port in (1, 2):
        applied = records["applied_action"][:, port - 1]
        for i, channel in enumerate(ACTION_CHANNELS):
            kind = np.int32 if channel.startswith("button") else np.float32
            sample[f"p{port}_{channel}"] = applied[:, i].astype(kind)
        sample[f"p{port}_button_start"] = np.zeros(len(records), np.int32)
        sample[f"p{port}_rank"] = np.full(len(records), int(Rank.MASTER), np.uint8)
    return sample


def extract(path, side):
    """HAL's compact row for one replay or farm tape, cached. None if the file cannot be read.

    HAL stores stick values on its 1/80 grid and refuses others. Our bot's are on it; some opponents send raw byte
    values (-127/128), so the other side's sticks are rounded to the grid. They are not a model input.
    """
    from hal.data.policy_schema import policy_replay_identity
    from hal.data.policy_world_schema import encode_policy_world_replay

    path = Path(path)
    CACHE.mkdir(parents=True, exist_ok=True)
    cached = CACHE / f"{policy_replay_identity(str(path))}.pkl"
    if cached.exists():
        return pickle.loads(cached.read_bytes())
    sample = from_tape(path) if path.suffix == ".npz" else _parse(path)
    if sample is not None:
        other = "p2" if side == "p1" else "p1"
        for key in [k for k in sample if k.startswith(other) and "stick" in k]:
            sample[key] = (np.rint(np.asarray(sample[key], np.float32) * 80) / np.float32(80)).astype(np.float32)
        sample["schema_version"] = 7
        sample = encode_policy_world_replay(sample, policy_replay_identity(str(path)))
    cached.write_bytes(pickle.dumps(sample))
    return sample


class Games:
    def __init__(self, games, stats, identity=AMSA):
        """games: (slp path, "p1" or "p2", info). The named side plays as `identity`; the other is masked."""
        from hal.data.player_identity import ReplayPlayerLookup
        from hal.data.policy_world_schema import decode_policy_world_replay
        from hal.representation.features import ITEM_PLAYER_COLUMNS, ITEM_PLAYER_PROJECTION, FeatureProjection
        from hal.training import returns as returns_lib

        m = o59()
        self.cfg, self.stats, self.extra = m.TrainConfig(), stats, ITEM_PLAYER_COLUMNS
        awr = self.cfg.awr
        self.projection = FeatureProjection(columns=ITEM_PLAYER_PROJECTION.columns | {
            awr.ego_return_column, awr.ego_return_valid_column, "ego_return60", "ego_return60_valid"})
        self.length = self.cfg.arch.L_ctx + self.cfg.arch.sample_chunk_length
        self.samples, self.skipped = [], []
        for path, side, info in games:
            compact = extract(path, side)
            if compact is None or int(np.asarray(compact["num_frames"]).item()) < self.length:
                self.skipped.append(str(path))
                continue
            ids = (identity, 0) if side == "p1" else (0, identity)
            labels = m.ReturnLabels(returns_lib.PolicyReturnLabels(
                ReplayPlayerLookup({str(compact["replay_id"]): ids}), awr.gamma, awr.damage_shaping, awr.win_reward,
                awr.stock_value, awr.return_suffix))(compact)
            self.samples.append(({**decode_policy_world_replay(compact), **labels}, side, info))
        self.frames = np.array([len(s[0]["frame"]) for s in self.samples])

    def window(self, game, start):
        """Frames [start, start + 284) of one game: 256 of context and the 28 that follow."""
        from hal.training.replay_windows import make_window

        sample, side, _ = self.samples[game]
        window = make_window(sample, ego_prefix=side, start=start, pad=0, length=self.length,
                             projection=self.projection)
        window["ctx_pad"] = np.int64(0)
        return window

    def batch(self, windows):
        from hal.training.replay_windows import collate_windows, train_batch_from_columns

        batch = train_batch_from_columns(collate_windows(windows), stats=self.stats, L_ctx=self.cfg.arch.L_ctx,
                                         extra=self.extra, projection=self.projection)
        return o59().collate_awr_batch(windows, batch, L_ctx=self.cfg.arch.L_ctx)

    def sample(self, n, rng):
        """n random windows and their games' infos, games drawn in proportion to their length."""
        room = self.frames - self.length + 1
        games = rng.choice(len(self.samples), size=n, p=room / room.sum())
        return self.batch([self.window(g, int(rng.integers(room[g]))) for g in games]), [self.samples[g][2] for g in games]
