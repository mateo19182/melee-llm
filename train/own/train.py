"""Behaviour cloning of a Faynt-architecture policy on HAL's dataset, with the input delay as a model input.

    PYTHONPATH=. <Faynt venv>/python -m own.train RUN [--delays 0,12] [--frames 1e9] [--batch 64]

RUN is a folder under data/train/runs. Checkpoints are Faynt weight folders (`ckpt/step-N`), so `farm` and the live
bot load them as `faynt:<folder>`; `last.pt` resumes the run. The name code the model is told is the index of the
window's delay in --delays.
"""
import argparse
import json
import math
import os
import shutil
import time
from pathlib import Path

import torch
from farm.common import LIVE
from farm.faynt import weights

from . import data

RUNS = LIVE / "data/train/runs"
BASE = "10M-Base"  # the released folder whose architecture and code files we start from
NAMES = 8


def build(base=BASE, names=NAMES):
    """A randomly initialised model of a released Faynt size, without the FoD platform input (not in the dataset)
    and with a name code input."""
    from transformers import AutoConfig, AutoModel

    config = AutoConfig.from_pretrained(weights(base), trust_remote_code=True)
    config.model_config.update(use_fod_platforms=False, condition_on_player_name=True, player_name_vocab_size=names,
                               compute_dtype="bfloat16")
    config.training_stage, config.checkpoint_step, config.provenance = "own-bc", 0, {}
    return AutoModel.from_config(config, trust_remote_code=True)


def loss_of(model, batch):
    game, pad, target, name, valid = data.tensors(batch)
    out = model.policy(game_state_t=game, controller_t=pad, controller_t_plus_1=target, player_name=name)[0]
    return model.policy.loss(out, target, valid)


@torch.no_grad()
def validate(model, batches):
    model.eval()
    sums = {}
    for batch in batches:
        code = batch["meta"][:, 4]
        for c in code.unique().tolist():
            rows = (code == c).nonzero()[:, 0]
            _, m = loss_of(model, {k: v[rows] for k, v in batch.items()})
            s = sums.setdefault(c, [0.0, 0.0, 0.0, 0.0])
            n = float(m["valid_positions"])
            for i, k in enumerate(("loss", "nll/buttons", "nll/main_stick")):
                s[i] += float(m[k]) * n
            s[3] += n
    model.train()
    return {c: [round(v / s[3], 4) for v in s[:3]] for c, s in sorted(sums.items())}


def save(run, model, opt, step, frames):
    d = run / "ckpt" / f"step-{step:07d}"
    model.config.checkpoint_step = step
    model.save_pretrained(d)
    for f in Path(weights(BASE)).glob("*.py"):
        shutil.copy2(f, d / f.name)
    tmp = run / "last.pt.tmp"
    torch.save(dict(model=model.state_dict(), opt=opt.state_dict(), step=step, frames=frames), tmp)
    os.replace(tmp, run / "last.pt")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run")
    ap.add_argument("--delays", default="0,12")
    ap.add_argument("--frames", type=float, default=1e9, help="training frames in total")
    ap.add_argument("--batch", type=int, default=64)
    ap.add_argument("--lr", type=float, default=3e-4)
    ap.add_argument("--warmup", type=int, default=1000)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--val-every", type=int, default=2000)
    ap.add_argument("--val-games", type=int, default=240)
    ap.add_argument("--save-every", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    delays = [int(x) for x in a.delays.split(",")]
    run = RUNS / a.run
    run.mkdir(parents=True, exist_ok=True)
    torch.manual_seed(a.seed)
    model = build().cuda().train()
    decay = [p for p in model.parameters() if p.ndim >= 2]
    rest = [p for p in model.parameters() if p.ndim < 2]
    opt = torch.optim.AdamW([dict(params=decay, weight_decay=0.01), dict(params=rest, weight_decay=0.0)], lr=a.lr,
                            betas=(0.9, 0.95), fused=True)
    per_step = a.batch * data.WINDOW
    steps = int(a.frames // per_step)
    step = frames = 0
    if (run / "last.pt").exists():
        state = torch.load(run / "last.pt", map_location="cuda")
        model.load_state_dict(state["model"]); opt.load_state_dict(state["opt"])
        step, frames = state["step"], state["frames"]
        print(f"resumed at step {step}", flush=True)
    else:
        (run / "run.json").write_text(json.dumps(dict(kind="own-bc", args=vars(a), base=BASE, steps=steps,
                                                      params=sum(p.numel() for p in model.parameters())), indent=1))
    val = list(data.loader("val", delays, a.batch, 2, seed=1, limit=a.val_games))
    print(f"{steps} steps of {per_step} frames; validation {len(val)} batches", flush=True)
    log = open(run / "train.jsonl", "a")
    seen, t0 = 0.0, time.time()
    for batch in data.loader("train", delays, a.batch, a.workers, seed=a.seed + step):
        if step >= steps:
            break
        lr = a.lr * min(1.0, (step + 1) / a.warmup) * (0.1 + 0.9 * 0.5 * (1 + math.cos(math.pi * step / steps)))
        for g in opt.param_groups:
            g["lr"] = lr
        loss, m = loss_of(model, batch)
        loss.backward()
        norm = float(torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0))
        opt.step(); opt.zero_grad(set_to_none=True)
        step += 1; frames += per_step
        seen += float(m["loss"])
        if step % 100 == 0:
            line = dict(step=step, frames=frames, loss=round(seen / 100, 4), lr=round(lr, 6), grad=round(norm, 3),
                        fps=round(100 * per_step / (time.time() - t0)), time=time.time())
            if step % a.val_every == 0:
                line["val"] = validate(model, val)
            log.write(json.dumps(line) + "\n"); log.flush()
            print(line, flush=True)
            seen, t0 = 0.0, time.time()
        if step % a.save_every == 0 or step == steps:
            save(run, model, opt, step, frames)


if __name__ == "__main__":
    main()
