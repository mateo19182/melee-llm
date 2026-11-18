"""Train a small student (student.py) to play Yoshi like HAL's model does without delay, at 0 and 9 to 11 frames of delay.

    python -m haltrain.distill RUN_DIR --farm /mnt/data/melee/farm/student-1/d* [--width 256] [--context 128]

Every example is: the game up to frame t, the d actions that followed (already sent, in play), and a label for the
action of frame t+d+1. Three kinds of game supply them:

- Farm games the teacher played without delay, and aMSa's human games: the label is the action that was played.
  d is drawn per window from --delays. This is imitation at delay alignment, as slippi-ai does it.
- Farm games the teacher played WITH delay d: these hold the positions a delayed player gets into. The label is what
  the teacher would have done seeing the present (haltrain.relabel), and d is the delay the game was played at.

Each update takes --batch windows of farm games and --batch of aMSa's. Every tenth farm game is held out.
The student is saved as RUN_DIR/last.pt with its shape.
"""
import argparse
import json
import math
import queue
import threading
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F

from . import WEIGHTS, o59
from .data import train_loader
from .own import Games
from .student import Student
from .validate import cohort


def farm_games(folders, stats):
    """Games of farm folders with their delay and, where they were played with delay, the teacher's labels."""
    listed = []
    for folder in map(Path, folders):
        for line in (folder / "results.jsonl").read_text().splitlines():
            row = json.loads(line)
            delay = int(dict(x.split("=") for x in row["a"].split(",")[1:]).get("delay", 0))
            labels = np.load(folder / "labels" / (Path(row["tape"]).stem + ".npy")) if delay else None
            listed.append((folder / row["tape"], f"p{row['a_port']}", {"delay": delay, "labels": labels}))
    held = Games([g for i, g in enumerate(listed) if i % 10 == 0], stats)
    return Games([g for i, g in enumerate(listed) if i % 10], stats), held


def farm_batch(games, n, rng, delays):
    """n random windows: the batch, each window's delay, and the teacher's labels for its frames (or None)."""
    room = games.frames - games.length + 1
    picks = rng.choice(len(games.samples), size=n, p=room / room.sum())
    starts = [int(rng.integers(room[g])) for g in picks]
    batch = games.batch([games.window(g, s) for g, s in zip(picks, starts)])
    delay = np.zeros(n, np.int64)
    labels = np.full((n, games.length, 4), -2, np.int64)  # -2: use the action that was played
    for i, (g, s) in enumerate(zip(picks, starts)):
        info = games.samples[g][2]
        delay[i] = info["delay"] or rng.choice(delays)
        if info["labels"] is not None:
            labels[i] = info["labels"][s:s + games.length]
    return batch, torch.from_numpy(delay), torch.from_numpy(labels)


class Prefetch:
    """Batches built on a thread, a few ahead."""

    def __init__(self, make, ahead=6):
        self.queue, self.stop = queue.Queue(ahead), False
        threading.Thread(target=self._run, args=(make,), daemon=True).start()

    def _run(self, make):
        while not self.stop:
            self.queue.put(make())

    def __next__(self):
        return self.queue.get()


def loss(student, m, cfg, batch, delay, labels=None):
    """Bits per frame of the student on the labels, at the last half of its context. Returns (mean, per-window)."""
    from hal.representation.features import stack_actions

    batch = batch.to("cuda")
    delay = delay.to("cuda")
    features, pad = batch.context.features, batch.context.ctx_pad
    length, context, chunk = cfg.arch.L_ctx, student.cfg.L_ctx, cfg.arch.sample_chunk_length
    first = length - context  # the student sees the last `context` frames of the window
    played = student.body.codec.quantize(torch.cat((stack_actions(features), batch.target[:, :chunk]), dim=1))
    t = torch.arange(first + context // 2, length, device="cuda")  # where the loss is taken, in window frames
    rows = torch.arange(len(delay), device="cuda")[:, None]
    after = t[None, :, None] + 1 + torch.arange(student.max_delay, device="cuda")
    pending = played[rows[:, :, None], after]                        # [B, T, max_delay, groups]
    target_at = (t[None] + 1 + delay[:, None])
    target = played[rows, target_at]
    if labels is not None:
        teacher = labels.to("cuda")[rows, target_at]
        target = torch.where(teacher == -2, target, teacher)
    known = (target >= 0).all(-1) & (t[None] >= pad[:, None] + context // 4)
    with m.amp_context(cfg, "cuda"):
        hidden = student.hidden({k: v[:, first:] for k, v in features.items()}, (pad - first).clamp(min=0))
        hidden = hidden[:, context // 2:]
        fused = student.fused(hidden.flatten(0, 1), pending.flatten(0, 1), delay[:, None].expand(-1, len(t)).flatten())
        logits = student.logits(fused, target.clamp(min=0).flatten(0, 1))
    nll = sum(F.cross_entropy(logits[name].float(), target.clamp(min=0).flatten(0, 1)[:, student.index[name]],
                              reduction="none") for name in student.order).view(len(delay), len(t))
    nll = nll * known
    per_window = nll.sum(1) / known.sum(1).clamp(min=1) / math.log(2)
    return nll.sum() / known.sum().clamp(min=1) / math.log(2), per_window


def make_optimizer(student, muon_lr, adam_lr):
    """Muon on the trunk's weight matrices, as HAL trains its own; AdamW on everything else."""
    from hal.training.muon import SingleDeviceMuonWithAuxAdam

    split, plain, rest = [], [], []
    for name, p in student.named_parameters():
        if name.startswith("body.trunk.blocks.") and p.ndim == 2:
            (split if name.endswith("c_attn.weight") else plain).append(p)
        else:
            rest.append(p)
    muon = dict(lr=muon_lr, momentum=0.95, weight_decay=1e-4, use_muon=True, muon_scale_clamp_min_one=False)
    return SingleDeviceMuonWithAuxAdam([
        {"params": split, **muon, "logical_splits": 3}, {"params": plain, **muon, "logical_splits": 1},
        {"params": rest, "lr": adam_lr, "betas": (0.9, 0.99), "eps": 1e-8, "weight_decay": 1e-4,
         "update_clip_threshold": None, "use_muon": False}])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir", type=Path)
    ap.add_argument("--farm", nargs="+", required=True, help="farm folders (haltrain.farm --out, then haltrain.relabel)")
    ap.add_argument("--data", default="/mnt/data/melee/hal-ft", help="a copy of HAL's dataset, for aMSa's games")
    ap.add_argument("--val", default="/mnt/data/melee/hal-val")
    ap.add_argument("--width", type=int, default=256)
    ap.add_argument("--layers", type=int, default=6)
    ap.add_argument("--heads", type=int, default=8)
    ap.add_argument("--context", type=int, default=128)
    ap.add_argument("--delays", type=int, nargs="+", default=[0, 9, 10, 11])
    ap.add_argument("--updates", type=int, default=20000)
    ap.add_argument("--batch", type=int, default=64, help="windows per update from each source; must divide 2048")
    ap.add_argument("--muon-lr", type=float, default=0.007)
    ap.add_argument("--adam-lr", type=float, default=1e-3)
    ap.add_argument("--warmup", type=int, default=500)
    ap.add_argument("--val-every", type=int, default=1000)
    ap.add_argument("--log-every", type=int, default=50)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    torch.manual_seed(a.seed)
    torch.set_float32_matmul_precision("high")
    a.run_dir.mkdir(parents=True, exist_ok=True)
    from hal.inference.action_sequence_artifact import read_action_sequence_artifact

    m = o59()
    cfg = m.TrainConfig()
    artifact = read_action_sequence_artifact(WEIGHTS)
    shape = dict(width=a.width, layers=a.layers, heads=a.heads, context=a.context)
    student = Student(artifact.model_config, artifact.vocabulary, **shape).cuda()
    student.body.trunk.resolve_attention("cuda")
    optimizer = make_optimizer(student, a.muon_lr, a.adam_lr)
    base = [g["lr"] for g in optimizer.param_groups]
    train, held = farm_games(a.farm, artifact.statistics)
    rng = np.random.default_rng(a.seed)
    farm = Prefetch(lambda: farm_batch(train, a.batch, rng, a.delays))
    human = iter(train_loader(a.data, artifact.statistics, batch=a.batch, seed=a.seed))
    _, human_val = cohort(a.val, 0, only_amsa=True)
    held_rng, human_rng = np.random.default_rng(1), np.random.default_rng(a.seed + 2)  # `rng` belongs to the farm thread
    held_batches = [farm_batch(held, a.batch, held_rng, a.delays) for _ in range(12)]
    setup = {"kind": "haltrain.distill", "args": {k: str(v) for k, v in vars(a).items()}, "shape": shape,
             "parameters_m": round(student.parameters_m(), 2), "started_at": time.time(),
             "games": {"train": len(train.samples), "held_out": len(held.samples),
                       "skipped": len(train.skipped) + len(held.skipped), "train_frames": int(train.frames.sum())}}
    (a.run_dir / "run.json").write_text(json.dumps(setup, indent=1))
    print(setup, flush=True)
    log = open(a.run_dir / "log.jsonl", "a")

    def save(update):
        torch.save({"model": student.state_dict(), "shape": shape, "update": update}, a.run_dir / "last.pt")

    def validate(update):
        student.eval()
        by_delay = {}
        with torch.no_grad():
            for batch, delay, labels in held_batches:
                _, per_window = loss(student, m, cfg, batch, delay, labels)
                for d, bits in zip(delay.tolist(), per_window.tolist()):
                    by_delay.setdefault(d, []).append(bits)
            humans = {d: float(np.mean([float(loss(student, m, cfg, b, torch.full((len(b.context.ctx_pad),), d))[0])
                                        for b in human_val[:8]])) for d in (0, 10)}
        student.train()
        row = {"update": update, "val": {**{f"farm_d{d}": round(float(np.mean(v)), 4) for d, v in sorted(by_delay.items())},
                                         **{f"human_d{d}": round(v, 4) for d, v in humans.items()}}}
        log.write(json.dumps(row) + "\n"); log.flush(); print(row, flush=True)
        save(update)

    validate(0)
    started, acc = time.monotonic(), {}
    for update in range(1, a.updates + 1):
        progress = update / a.updates
        scale = min(1.0, update / a.warmup) * (0.1 + 0.9 * 0.5 * (1 + math.cos(math.pi * progress)))
        for group, lr in zip(optimizer.param_groups, base):
            group["lr"] = lr * scale
        optimizer.zero_grad()
        batch, delay, labels = next(farm)
        farm_bits, _ = loss(student, m, cfg, batch, delay, labels)
        batch = next(human)
        delays = torch.from_numpy(human_rng.choice(a.delays, size=len(batch.context.ctx_pad)))
        human_bits, _ = loss(student, m, cfg, batch, delays)
        total = (farm_bits + human_bits) / 2
        if not bool(torch.isfinite(total)):
            raise FloatingPointError(f"update {update}: loss is not finite")
        total.backward()
        norm = torch.nn.utils.clip_grad_norm_(student.parameters(), 1.0)
        optimizer.step()
        for k, v in (("farm_bits", farm_bits), ("human_bits", human_bits), ("grad_norm", norm)):
            acc[k] = acc.get(k, 0.0) + float(v)
        if update % a.log_every == 0:
            row = {"update": update, "minutes": round((time.monotonic() - started) / 60, 2),
                   **{k: round(v / a.log_every, 4) for k, v in acc.items()}}
            log.write(json.dumps(row) + "\n"); log.flush(); print(row, flush=True)
            acc = {}
        if update % a.val_every == 0 or update == a.updates:
            validate(update)
    farm.stop = True


if __name__ == "__main__":
    main()
