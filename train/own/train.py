"""Behaviour cloning of a Faynt-architecture policy on HAL's dataset, with the input delay as a model input.

    PYTHONPATH=. <Faynt venv>/python -m own.train RUN [--delays 0,12] [--frames 1e9] [--batch 64]

RUN is a folder under data/train/runs. Checkpoints are Faynt weight folders (`ckpt/step-N`), so `farm` and the live
bot load them as `faynt:<folder>`; `last.pt` resumes the run. The name code the model is told carries the window's
delay and the player's rank and result (`own.data.code`).

Guard (E35 lost 14 hours to a run that diverged unwatched): the state at the last healthy validation is kept in
`good.pt`. When validation loss exceeds the best by --guard, or the gradient norm stays far above its recent level,
the run goes back to `good.pt` and halves its learning rate; after --rollbacks of these it stops and writes FAILED.
Every weight folder also holds `state.pt`: copy it to `last.pt` to resume from that step.
"""
import argparse
import json
import math
import os
import shutil
import statistics
import sys
import time
from pathlib import Path

import torch
from farm.common import LIVE
from farm.faynt import weights

from . import data

RUNS = LIVE / "data/train/runs"
BASE = "10M-Base"  # the released folder whose architecture and code files we start from


def build(base=BASE, names=data.CODES, compute="float32"):
    """A randomly initialised model of a released Faynt size, without the FoD platform input (not in the dataset)
    and with a name code input."""
    from transformers import AutoConfig, AutoModel

    config = AutoConfig.from_pretrained(weights(base), trust_remote_code=True)
    config.model_config.update(use_fod_platforms=False, condition_on_player_name=True, player_name_vocab_size=names,
                               compute_dtype=compute)
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
        delay = batch["meta"][:, 5]
        for c in delay.unique().tolist():
            rows = (delay == c).nonzero()[:, 0]
            _, m = loss_of(model, {k: v[rows] for k, v in batch.items()})
            s = sums.setdefault(c, [0.0, 0.0, 0.0, 0.0])
            n = float(m["valid_positions"])
            for i, k in enumerate(("loss", "nll/buttons", "nll/main_stick")):
                s[i] += float(m[k]) * n
            s[3] += n
    model.train()
    return {c: [round(v / s[3], 4) for v in s[:3]] for c, s in sorted(sums.items())}


@torch.no_grad()
def logit_scale(model, batch):
    """[mean top logit, mean spread] of the button logits: nothing in the loss pins their level, and E35 broke when
    they ran away (from -50 to -950 in 20,000 steps)."""
    model.eval()
    game, pad, target, name, _ = data.tensors(batch)
    logits = model.policy(game_state_t=game, controller_t=pad, controller_t_plus_1=target, player_name=name)[0]
    logits = logits.logits["buttons"].float()
    model.train()
    return [round(float(logits.max(-1).values.mean()), 2), round(float(logits.std(-1).mean()), 2)]


def save(run, model, opt, step, frames, folder, extra):
    state = dict(model=model.state_dict(), opt=opt.state_dict(), step=step, frames=frames, **extra)
    if folder:
        d = run / "ckpt" / f"step-{step:07d}"
        model.config.checkpoint_step = step
        model.save_pretrained(d)
        for f in Path(weights(BASE)).glob("*.py"):
            shutil.copy2(f, d / f.name)
        torch.save(state, d / "state.pt")
    write(state, run / "last.pt")


def write(state, path):
    tmp = path.with_suffix(".tmp")
    torch.save(state, tmp)
    os.replace(tmp, path)


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
    ap.add_argument("--save-every", type=int, default=2000, help="steps between writes of last.pt")
    ap.add_argument("--ckpt-every", type=int, default=2000, help="steps between weight folders")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--init", help="a weight folder to start from (new optimizer, step 0)")
    ap.add_argument("--compute", default="float32", choices=["float32", "bfloat16"],
                    help="bfloat16 is faster and was what E35's diverged run used")
    ap.add_argument("--guard", type=float, default=1.08, help="validation loss over the best that triggers a rollback")
    ap.add_argument("--grad-guard", type=float, default=6.0, help="gradient norm over its recent median, likewise")
    ap.add_argument("--rollbacks", type=int, default=4, help="rollbacks before the run gives up")
    a = ap.parse_args()
    delays = [int(x) for x in a.delays.split(",")]
    run = RUNS / a.run
    run.mkdir(parents=True, exist_ok=True)
    torch.manual_seed(a.seed)
    if (run / "FAILED").exists():
        print(f"{run}/FAILED exists: this run gave up; see train.jsonl", flush=True)
        sys.exit(0)
    model = build(compute=a.compute).cuda().train()
    if a.init and not (run / "last.pt").exists():
        from safetensors.torch import load_file

        model.load_state_dict(load_file(Path(a.init) / "model.safetensors"))
    decay = [p for p in model.parameters() if p.ndim >= 2]
    rest = [p for p in model.parameters() if p.ndim < 2]
    opt = torch.optim.AdamW([dict(params=decay, weight_decay=0.01), dict(params=rest, weight_decay=0.0)], lr=a.lr,
                            betas=(0.9, 0.95), fused=True)
    per_step = a.batch * data.WINDOW
    steps = int(a.frames // per_step)
    step = frames = 0
    guard = dict(best=float("inf"), scale=1.0, rollbacks=0)  # scale multiplies the learning rate
    if (run / "last.pt").exists():
        state = torch.load(run / "last.pt", map_location="cuda")
        model.load_state_dict(state["model"]); opt.load_state_dict(state["opt"])
        step, frames = state["step"], state["frames"]
        guard.update(state.get("guard", {}))
        print(f"resumed at step {step}", flush=True)
    else:
        (run / "run.json").write_text(json.dumps(dict(kind="own-bc", args=vars(a), base=BASE, steps=steps,
                                                      params=sum(p.numel() for p in model.parameters())), indent=1))
    # cloned: a batch from a worker holds one shared-memory file handle per tensor
    val = [{k: v.clone() for k, v in b.items()} for b in data.loader("val", delays, a.batch, 2, seed=1, limit=a.val_games)]
    print(f"{steps} steps of {per_step} frames; validation {len(val)} batches", flush=True)
    log = open(run / "train.jsonl", "a")
    seen, t0, norms, high = 0.0, time.time(), [], 0

    def rollback(why):
        nonlocal step, frames, norms, high
        guard["rollbacks"] += 1
        line = dict(step=step, rollback=why, n=guard["rollbacks"])
        if guard["rollbacks"] > a.rollbacks or not (run / "good.pt").exists():
            log.write(json.dumps(dict(line, failed=True)) + "\n"); log.flush()
            (run / "FAILED").write_text(json.dumps(line))
            print(f"gave up at step {step}: {why}", flush=True)
            sys.exit(0)  # not an error exit: systemd would restart the run
        state = torch.load(run / "good.pt", map_location="cuda")
        model.load_state_dict(state["model"]); opt.load_state_dict(state["opt"])
        step, frames = state["step"], state["frames"]
        guard["scale"] *= 0.5
        norms, high = [], 0
        line.update(back_to=step, scale=guard["scale"])
        log.write(json.dumps(line) + "\n"); log.flush()
        print(line, flush=True)
        write(dict(state, guard=dict(guard)), run / "last.pt")

    for batch in data.loader("train", delays, a.batch, a.workers, seed=a.seed + step):
        if step >= steps:
            break
        lr = a.lr * guard["scale"] * min(1.0, (step + 1) / a.warmup) * (0.1 + 0.9 * 0.5 * (1 + math.cos(math.pi * step / steps)))
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
                line["val"], line["logit"] = validate(model, val), logit_scale(model, val[0])
            log.write(json.dumps(line) + "\n"); log.flush()
            print(line, flush=True)
            seen, t0 = 0.0, time.time()
            high = high + 1 if len(norms) >= 30 and norm > a.grad_guard * statistics.median(norms[-50:]) else 0
            norms.append(norm)
            if "val" in line:
                now = statistics.mean(v[0] for v in line["val"].values())
                if now > a.guard * guard["best"]:
                    rollback(f"validation {now:.4f} against best {guard['best']:.4f}")
                    continue
                guard["best"] = min(guard["best"], now)
                write(dict(model=model.state_dict(), opt=opt.state_dict(), step=step, frames=frames,
                           guard=dict(guard)), run / "good.pt")
            elif high >= 3:
                rollback(f"gradient norm {norm:.2f} against median {statistics.median(norms[-50:]):.2f}")
                continue
        if step % a.save_every == 0 or step % a.ckpt_every == 0 or step == steps:
            save(run, model, opt, step, frames, step % a.ckpt_every == 0 or step == steps, dict(guard=dict(guard)))


if __name__ == "__main__":
    main()
