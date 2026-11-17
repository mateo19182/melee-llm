"""HAL's validation loss for a checkpoint, computed as its training script does.

    python -m haltrain.validate [--weights X.hal] [--root DIR] [--samples 2048] [--chunk 16] [--only-amsa-yoshi]

Default: the fixed validation cohort of the 059 run (seed 0, 2,048 windows over all 44 sources). HAL recorded
val/nll 1.0870 bits for the released weights (vendor/hal/experiments/o59/scaling-comparison/sources/
o59_cooldown_validation.json), so that is what this must print for them.

--root must hold `<source>/val`, `<source>/stats.json` and `player_codes.jsonl.gz` in the dataset's layout. Point it
at a copy: the loader decompresses shards next to the compressed files and may delete the compressed ones.
--only-amsa-yoshi scores aMSa's held-out games instead, keeping the windows where he is the player and on Yoshi.
"""
import argparse
import functools
import json
import time
from pathlib import Path

import torch

from . import AMSA, WEIGHTS, load_model, o59, take

YOSHI = 14  # libmelee internal character id


def cohort(root, n, only_amsa=False, passes=8):
    m = o59()
    from hal.data.player_identity import ReplayPlayerLookup
    from hal.representation.features import ITEM_PLAYER_COLUMNS, ITEM_PLAYER_PROJECTION, FeatureProjection
    from hal.training import returns as returns_lib
    from hal.training.validation_replay_loader import make_validation_replay_loader

    cfg = m.TrainConfig()
    corpus = m.huggingface_corpus(Path(root))
    stats = m.load_stats(cfg, corpus)
    lookup = ReplayPlayerLookup(m.load_identity_sidecar(cfg, corpus).by_replay)
    sources = tuple(s for s in corpus.sources if "amsa" in s.name) if only_amsa else corpus.sources
    make = lambda seed: make_validation_replay_loader(
        sources=sources, stats=stats, context_length=cfg.arch.L_ctx, chunk_length=cfg.arch.sample_chunk_length,
        batch_size=cfg.val_batch_size, seed=seed, cache_limit="64gb", schema_version=cfg.mds_schema_version,
        extra=ITEM_PLAYER_COLUMNS,
        projection=FeatureProjection(columns=ITEM_PLAYER_PROJECTION.columns | {
            cfg.awr.ego_return_column, cfg.awr.ego_return_valid_column, "ego_return60", "ego_return60_valid"}),
        batch_transform=functools.partial(m.collate_awr_batch, L_ctx=cfg.arch.L_ctx),
        replay_labels=m.ReturnLabels(returns_lib.PolicyReturnLabels(
            lookup, cfg.awr.gamma, cfg.awr.damage_shaping, cfg.awr.win_reward, cfg.awr.stock_value,
            cfg.awr.return_suffix)))
    if not only_amsa:
        return cfg, m.cache_validation(make(cfg.seed), n)
    kept = []
    # each pass over aMSa's held-out games gives one window per game, with a random side as the player
    for batch in (b for seed in range(passes) for b in make(seed)):
        f = batch.context.features
        keep = (f["ego_player_id"][:, -1] == AMSA) & (f["ego_character"][:, -1] == YOSHI)
        if keep.any():
            kept.append(take(batch, keep.nonzero().flatten()))
    return cfg, kept


def score(model, cfg, batches, chunk):
    m = o59()
    pieces = [take(b, slice(i, i + chunk)) for b in batches for i in range(0, b.target.shape[0], chunk)]
    with torch.no_grad():
        return m.val_metrics(model, pieces, cfg)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--weights", default=str(WEIGHTS))
    ap.add_argument("--root", default="/mnt/data/melee/hal-val")
    ap.add_argument("--samples", type=int, default=2048)
    ap.add_argument("--chunk", type=int, default=16, help="windows per forward pass")
    ap.add_argument("--only-amsa-yoshi", action="store_true")
    ap.add_argument("--out")
    a = ap.parse_args()
    torch.set_float32_matmul_precision("high")
    cfg, batches = cohort(a.root, a.samples, a.only_amsa_yoshi)
    model, _ = load_model(a.weights)
    started = time.monotonic()
    out = score(model, cfg, batches, a.chunk)
    wandb = o59()._validation_wandb_metrics(out, cfg)
    wandb["windows"] = sum(b.target.shape[0] for b in batches)
    wandb["seconds"] = round(time.monotonic() - started, 1)
    wandb["peak_gb"] = round(torch.cuda.max_memory_allocated() / 2**30, 2)
    print(json.dumps(wandb, indent=1))
    if a.out:
        Path(a.out).write_text(json.dumps({"summary": wandb, "all": out}, indent=1))


if __name__ == "__main__":
    main()
