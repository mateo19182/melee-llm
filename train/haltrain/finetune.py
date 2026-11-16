"""Fine-tune HAL's model with its own loss, in microbatches that fit a 24 GB card.

    python -m haltrain.finetune RUN_DIR [--init X.hal] [--updates 200] [--micro 16] [--accum 4] [--lr-scale 0.00588]

One update = --accum microbatches of --micro windows. The loss is HAL's (059: advantage-weighted policy loss over
16 action offsets on 32 sampled positions per window, plus the value loss), averaged over the microbatches, so
advantage weights are normalised per microbatch and not per update. Identity and return are dropped with HAL's
probabilities. The optimiser is HAL's Muon + Adam with its per-role learning rates times --lr-scale; the default,
1/170, is where the released run ended.

Writes RUN_DIR/run.json, log.jsonl (one line per --log-every updates and per validation) and last.hal, a bundle
the bots load like the original (`hal:AMSA#0` with config weights=RUN_DIR/last.hal).
"""
import argparse
import json
import time
from pathlib import Path

import torch

from . import WEIGHTS, load_model, o59, save_bundle
from .data import train_loader
from .validate import cohort, score


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir", type=Path)
    ap.add_argument("--init", default=str(WEIGHTS))
    ap.add_argument("--data", default="/mnt/data/melee/hal-ft", help="a copy of the dataset folder (see data.py)")
    ap.add_argument("--val", default="/mnt/data/melee/hal-val")
    ap.add_argument("--updates", type=int, default=200)
    ap.add_argument("--micro", type=int, default=16)
    ap.add_argument("--accum", type=int, default=4)
    ap.add_argument("--lr-scale", type=float, default=1 / 170)
    ap.add_argument("--warmup", type=int, default=20)
    ap.add_argument("--val-every", type=int, default=100)
    ap.add_argument("--log-every", type=int, default=10)
    ap.add_argument("--compile", action="store_true", help="torch.compile the trunk and decoder (slow start)")
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    m = o59()
    torch.manual_seed(a.seed)
    torch.set_float32_matmul_precision("high")
    a.run_dir.mkdir(parents=True, exist_ok=True)
    cfg = m.TrainConfig()
    model, artifact = load_model(a.init)
    model.train()
    optimizer = m.make_optimizer(model, cfg)
    base = [g["lr"] for g in optimizer.param_groups]
    trunk_fn, temporal_fn = model.forward, model.temporal.teacher_forced_nll_with_diagnostics
    model.trunk.resolve_attention("cuda")
    if a.compile:
        trunk_fn = torch.compile(trunk_fn, dynamic=False, fullgraph=True)
        temporal_fn = torch.compile(temporal_fn, dynamic=False, fullgraph=True)
    sampler = m.PrefixSampler(a.seed, "cuda")
    drop_identity = m.IdentityMasker(a.seed, cfg.identity_dropout)
    drop_return = m.ReturnMasker(a.seed, cfg.return_dropout)
    _, held_out = cohort(a.val, 0, only_amsa=True)
    loader = train_loader(a.data, artifact.statistics, batch=a.micro, seed=a.seed)
    batches = iter(loader)
    log = open(a.run_dir / "log.jsonl", "a")
    (a.run_dir / "run.json").write_text(json.dumps({"kind": "haltrain", "args": {k: str(v) for k, v in vars(a).items()},
                                                    "started_at": time.time()}, indent=1))

    def validate(update):
        out = m._validation_wandb_metrics(score(model, cfg, held_out, a.micro), cfg)
        row = {"update": update, "val": {k: round(v, 4) for k, v in out.items()}}
        log.write(json.dumps(row) + "\n"); log.flush(); print(row, flush=True)

    validate(0)
    started, seen, acc = time.monotonic(), 0, {}
    try:
        for update in range(1, a.updates + 1):
            for g, lr in zip(optimizer.param_groups, base):
                g["lr"] = lr * a.lr_scale * min(1.0, update / max(a.warmup, 1))
            optimizer.zero_grad()
            for _ in range(a.accum):
                batch = drop_return(drop_identity(next(batches))).to("cuda")
                positions = sampler.sample(batch.context.ctx_pad, length=cfg.arch.L_ctx,
                                           suffix_start=cfg.arch.direct_loss_start)
                loss, _, metrics = m.microbatch_loss(
                    model, batch, cfg, step=cfg.awr.start_update, valid_prefixes=a.micro * m.POLICY_PREFIXES_PER_WINDOW,
                    trunk_fn=trunk_fn, temporal_fn=temporal_fn, prefix_positions=positions)
                if not bool(torch.isfinite(loss)):
                    raise FloatingPointError(f"update {update}: loss is not finite")
                (loss / a.accum).backward()
                for name, k in (("policy_bits", "train/loss"), ("value_loss", "value/loss"), ("awr_ess", "awr/ess_fraction")):
                    acc[name] = acc.get(name, 0.0) + float(metrics[k]) / a.accum
            norm = float(torch.nn.utils.clip_grad_norm_(model.parameters(), cfg.grad_clip))
            optimizer.step()
            acc["grad_norm"] = acc.get("grad_norm", 0.0) + norm
            seen += a.micro * a.accum
            if update % a.log_every == 0:
                row = {"update": update, "windows": seen, "minutes": round((time.monotonic() - started) / 60, 2),
                       "windows_per_s": round(seen / (time.monotonic() - started), 1),
                       "peak_gb": round(torch.cuda.max_memory_allocated() / 2**30, 2),
                       **{k: round(v / a.log_every, 4) for k, v in acc.items()}}
                log.write(json.dumps(row) + "\n"); log.flush(); print(row, flush=True)
                acc = {}
            if update % a.val_every == 0 or update == a.updates:
                validate(update)
    finally:
        loader.close()
    save_bundle(model, a.init, a.run_dir / "last.hal", name=a.run_dir.name)


if __name__ == "__main__":
    main()
