"""Training batches from HAL's dataset, restricted to chosen games.

HAL's own loader does the work (a ring of decoded replays, eight windows from each before it is replaced, a random
side of each game as the player being imitated). This module only chooses the games and keeps the settings small
enough for one machine.
"""
import functools
import json
from pathlib import Path

from . import o59

YOSHI = 14  # libmelee internal character id


def rows_where(source_root, keep, split="train"):
    """(rows in the split, row numbers to exclude) for a source folder, from its manifest.jsonl."""
    total, excluded = 0, []
    for line in open(Path(source_root) / "manifest.jsonl"):
        game = json.loads(line)
        if game["annotation"]["split"] != split:
            continue
        total += 1
        if not keep(game):
            excluded.append(game["annotation"]["mds_row_idx"])
    return total, tuple(sorted(excluded))


def amsa_yoshi(game):
    return any(p.get("code") == "AMSA#0" and p.get("character") == YOSHI for p in game["players"])


def train_loader(root, stats, folder="pro/amsa", keep=amsa_yoshi, batch=16, slots=2048, workers=4, seed=0):
    """An endless iterator of ReturnBatch over the kept games of one source folder under `root`.

    `stats` are the model's feature statistics (the artifact's). `root` must be a copy of the dataset folder (train split, stats.json, manifest.jsonl, player_codes.jsonl.gz):
    the loader decompresses shards in place and removes the compressed files.
    """
    m = o59()
    from hal import streams
    from hal.data.player_identity import ReplayPlayerLookup
    from hal.representation.features import ITEM_PLAYER_PROJECTION, FeatureProjection
    from hal.training import returns as returns_lib
    from hal.training.buffered_mds_replay_loader import (
        BufferedMDSReplayLoader, MDSStorageAdapter, PhysicalShardSelection, SourceRowSelection, build_shard_plan)
    import torch

    cfg = m.TrainConfig()
    corpus = m.huggingface_corpus(Path(root))
    source = next(s for s in corpus.sources if str(s.local).endswith(folder))
    total, excluded = rows_where(source.local_root, keep)
    selection = PhysicalShardSelection.from_sources((SourceRowSelection(source.name, total, excluded),))
    adapter = MDSStorageAdapter(selection, sources=(source,), download_retry=cfg.download_retry)
    lookup = ReplayPlayerLookup(m.load_identity_sidecar(cfg, corpus).by_replay)
    projection = FeatureProjection(columns=ITEM_PLAYER_PROJECTION.columns | {
        cfg.awr.ego_return_column, cfg.awr.ego_return_valid_column, "ego_return60", "ego_return60_valid"})
    return BufferedMDSReplayLoader[m.ReturnBatch](
        selection=selection, adapter=adapter, tasks=build_shard_plan(selection, adapter.manifests),
        data_protocol=cfg.data_protocol,
        source_manifest_sha256={source.name: streams.POLICY_WORLD_V8_TRAIN_MANIFEST_SHA256[source.name]},
        batch_transform=functools.partial(
            m._collate_o59_batch, stats=stats, projection=projection,
            context_length=cfg.arch.L_ctx, return_column=cfg.awr.ego_return_column,
            return_valid_column=cfg.awr.ego_return_valid_column),
        batch_size=batch, replay_slots=slots, seed=seed, num_workers=workers,
        labels=m.ReturnLabels(returns_lib.PolicyReturnLabels(
            player_lookup=lookup, gamma=cfg.awr.gamma, damage_shaping=cfg.awr.damage_shaping,
            win_reward=cfg.awr.win_reward, stock_value=cfg.awr.stock_value, suffix=cfg.awr.return_suffix)),
        projection=projection, context_length=cfg.arch.L_ctx, chunk_length=cfg.arch.sample_chunk_length,
        windows_per_generation=cfg.windows_per_generation, replay_phase_block_batches=cfg.replay_phase_block_batches,
        schema_version=cfg.mds_schema_version, reserved_disk_bytes=0, pin_memory=torch.cuda.is_available(),
        materialization_threads=workers)
