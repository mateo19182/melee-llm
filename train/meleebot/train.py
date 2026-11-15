"""Behaviour cloning on a dataset built by build_dataset.

    uv run python -m meleebot.train DATA_DIR RUN_DIR [--steps N] [--overfit-game G] [--init CKPT]

--overfit-game trains on one game only; the loss should fall close to zero, otherwise the
pipeline has a bug. --init fine-tunes a trained checkpoint (e.g. the all-character pretrain on Yoshi): it
keeps that model's shape, input normalisation and stick classes, so --layers/--width/--pos are ignored.
"""
import argparse, json, math, os, time

import numpy as np
import torch
import torch.nn.functional as F

from . import features as fe
from .model import HEADS, Config, Policy, load, save
from .schema import FRAME, RANKS

COND_DROP = 0.1   # share of windows trained without rank / result, so both can be left unknown at play time


class Windows(torch.utils.data.IterableDataset):
    def __init__(self, data_dir, games, stick_centers, batch, context, seed, features="v1", delays=(0, fe.MAX_DELAY)):
        self.data_dir, self.g, self.centers, self.features, self.delays = data_dir, games, stick_centers, features, delays
        self.batch, self.context, self.seed = batch, context, seed
        # A window needs MAX_DELAY frames before it and one after; starts are drawn uniformly over frames.
        self.starts = np.maximum(games["length"] - context - fe.MAX_DELAY - 1, 0)
        self.cum = np.cumsum(self.starts)

    def __iter__(self):
        info = torch.utils.data.get_worker_info()
        rng = np.random.default_rng([self.seed, info.id if info else 0])
        frames = np.memmap(os.path.join(self.data_dir, "frames.bin"), FRAME, "r")
        while True:
            yield self.make(frames, rng)

    def make(self, frames, rng):
        B, T = self.batch, self.context
        pick = rng.integers(0, self.cum[-1], B)
        gi = np.searchsorted(self.cum, pick, side="right")
        within = pick - np.concatenate([[0], self.cum])[gi]
        delay = rng.integers(self.delays[0], self.delays[1] + 1, B)
        num = np.empty((B, T, fe.NUM), np.float32)
        actions = np.empty((B, T, 2), np.int64)
        target = np.empty((B, T), FRAME["me_pad"])
        for i in range(B):
            off = int(self.g["offset"][gi[i]])
            game = np.asarray(frames[off + within[i]: off + within[i] + fe.MAX_DELAY + T + 1])
            num[i], actions[i], target[i] = fe.window(game, fe.MAX_DELAY, T, delay[i], self.features)
        b = dict(num=num, actions=actions, delay=delay)
        for k in ("me_char", "opp_char", "rank"):
            b[k] = self.g[k][gi]
        b["stage"] = np.array([fe.STAGE_INDEX[int(s)] for s in self.g["stage"][gi]])
        b["win"] = self.g["win"][gi].copy()
        b["rank"] = np.where(rng.random(B) < COND_DROP, 0, b["rank"])
        b["win"] = np.where(rng.random(B) < COND_DROP, 2, b["win"])
        b.update(zip(HEADS, fe.targets(target, self.centers)))
        return {k: torch.from_numpy(np.asarray(v)) for k, v in b.items()}


def subset(games, mask):
    return {k: v[mask] for k, v in games.items()}


def loss_fn(logits, b):
    parts = {h: F.cross_entropy(l.flatten(0, 1).float(), b[h].flatten()) for h, l in zip(HEADS, logits)}
    acc = {h: (l.argmax(-1) == b[h]).float().mean() for h, l in zip(HEADS, logits)}
    return sum(parts.values()), parts, acc


def norm_stats(frames, rng, features, n=200_000):
    idx = np.sort(rng.choice(len(frames) - 1, n, replace=False))
    f = np.asarray(frames[idx])
    num, _ = fe.assemble(fe.frame_parts(f, features), np.arange(len(f)), 0)
    return num.mean(0), np.maximum(num.std(0), 1e-3), f["me_pad"]


def lr_scale(step, steps, warmup, schedule, cooldown):
    """Learning-rate multiplier. cosine: down to 0.1 at the end. wsd: flat at 1, then linear to 0 over the
    last `cooldown` share, so a run can be extended or cut early by moving only the cool-down."""
    w = min(1, (step + 1) / warmup)
    if schedule == "wsd":
        return w * min(1, (steps - step) / (cooldown * steps))
    return w * (0.1 + 0.9 * 0.5 * (1 + math.cos(math.pi * min(1, step / steps))))


def make_optimizers(model, kind, lr):
    """AdamW everywhere, or Muon on the blocks' 2-D weight matrices (attention and MLP) with AdamW on
    embeddings, input, heads, norms and biases. Muon's update is rescaled to AdamW's size
    (adjust_lr_fn="match_rms_adamw"), so the same --lr works for both."""
    muon = [p for n, p in model.named_parameters() if kind == "muon" and n.startswith("blocks.") and p.dim() == 2]
    rest = [(n, p) for n, p in model.named_parameters() if all(p is not q for q in muon)]
    decay = [p for n, p in rest if p.dim() >= 2 and "weight" in n and "ln" not in n]
    other = [p for n, p in rest if p.dim() < 2 or "weight" not in n or "ln" in n]
    opts = [torch.optim.AdamW([dict(params=decay, weight_decay=0.05), dict(params=other, weight_decay=0)],
                              lr=lr, betas=(0.9, 0.95), fused=True)]
    if muon:
        opts.append(torch.optim.Muon(muon, lr=lr, weight_decay=0.05, adjust_lr_fn="match_rms_adamw"))
    return opts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("data_dir"); ap.add_argument("run_dir")
    ap.add_argument("--steps", type=int, default=30_000)
    ap.add_argument("--batch", type=int, default=64)
    ap.add_argument("--lr", type=float, default=3e-4)
    ap.add_argument("--layers", type=int, default=6); ap.add_argument("--width", type=int, default=256)
    ap.add_argument("--context", type=int, default=256)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--eval-every", type=int, default=1000)
    ap.add_argument("--overfit-game", type=int)
    ap.add_argument("--pos", choices=["rope", "learned"], default="rope")
    ap.add_argument("--compile", action="store_true")
    ap.add_argument("--init", help="checkpoint to fine-tune instead of training from scratch")
    ap.add_argument("--optim", choices=["adamw", "muon"], default="adamw",
                    help="muon: Muon on the transformer blocks' weight matrices, AdamW on the rest")
    ap.add_argument("--schedule", choices=["cosine", "wsd"], default="cosine",
                    help="wsd: warmup, constant, then a linear cool-down over the last --cooldown share of steps")
    ap.add_argument("--cooldown", type=float, default=0.2)
    ap.add_argument("--dropout", type=float, default=0.1)
    ap.add_argument("--delays", default=f"0-{fe.MAX_DELAY}",
                    help="input delays to train on, e.g. 2-4 to focus on netplay (the model still accepts 0-12)")
    ap.add_argument("--compile-mode", help="torch.compile mode, e.g. max-autotune-no-cudagraphs")
    a = ap.parse_args()
    delays = tuple(int(x) for x in a.delays.split("-"))
    if not 0 <= delays[0] <= delays[-1] <= fe.MAX_DELAY:
        raise SystemExit(f"--delays must be within 0-{fe.MAX_DELAY}")
    delays = (delays[0], delays[-1])

    os.makedirs(a.run_dir, exist_ok=True)
    torch.manual_seed(0)
    rng = np.random.default_rng(0)
    games = dict(np.load(os.path.join(a.data_dir, "games.npz")))
    frames = np.memmap(os.path.join(a.data_dir, "frames.bin"), FRAME, "r")
    meta_path = os.path.join(a.data_dir, "meta.json")
    features = json.load(open(meta_path)).get("features", "v1") if os.path.exists(meta_path) else "v1"
    init = None
    if a.init:
        model, init = load(a.init)
        if model.config.features != features:
            raise SystemExit(f"--init model reads features {model.config.features}, the data has {features}")
    else:
        mean, std, pads = norm_stats(frames, rng, features)
    if a.overfit_game is not None:
        train_g = val_g = subset(games, np.arange(len(games["length"])) == a.overfit_game)
        dropout = 0.0
    else:
        train_g, val_g, dropout = subset(games, games["val"] == 0), subset(games, games["val"] == 1), a.dropout

    if init:
        c = model.config
        centers = model.stick_centers.numpy()
    else:
        c = Config(layers=a.layers, width=a.width, heads=a.width // 32, context=a.context, dropout=dropout,
                   pos=a.pos, features=features)
        model = Policy(c)
        model.num_mean.copy_(torch.from_numpy(mean)); model.num_std.copy_(torch.from_numpy(std))
        centers = fe.kmeans_stick(pads, c.n_stick)
        model.stick_centers.copy_(torch.from_numpy(centers))
    dev = "cuda"
    model.to(dev)
    torch.set_float32_matmul_precision("high")
    fwd = torch.compile(model, mode=a.compile_mode) if a.compile else model   # `model` stays uncompiled for saving
    n_params = sum(p.numel() for p in model.parameters())
    print(f"{n_params / 1e6:.1f}M params, train {train_g['length'].sum() / 1e6:.0f}M frames "
          f"in {len(train_g['length'])} games, val {len(val_g['length'])} games", flush=True)

    opts = make_optimizers(model, a.optim, a.lr)
    warmup = min(1000, a.steps // 10)
    scheds = [torch.optim.lr_scheduler.LambdaLR(o, lambda s: lr_scale(s, a.steps, warmup, a.schedule, a.cooldown))
              for o in opts]

    loader = torch.utils.data.DataLoader(Windows(a.data_dir, train_g, centers, a.batch, c.context, 1, features, delays),
                                         batch_size=None, num_workers=a.workers, pin_memory=True,
                                         persistent_workers=True, prefetch_factor=4)
    val_maker = Windows(a.data_dir, val_g, centers, a.batch, c.context, 2, features, delays)
    val_batches = [val_maker.make(frames, np.random.default_rng(i)) for i in range(20)]

    def evaluate():
        model.eval()
        tot = {h: 0.0 for h in HEADS} | {f"acc_{h}": 0.0 for h in HEADS}
        with torch.no_grad(), torch.autocast("cuda", torch.bfloat16):
            for vb in val_batches:
                vb = {k: v.to(dev) for k, v in vb.items()}
                _, parts, acc = loss_fn(fwd(vb), vb)
                for h in HEADS:
                    tot[h] += parts[h].item() / len(val_batches)
                    tot[f"acc_{h}"] += acc[h].item() / len(val_batches)
        model.train()
        tot["loss"] = sum(tot[h] for h in HEADS)
        return tot

    log = open(os.path.join(a.run_dir, "log.jsonl"), "a")
    curve = open(os.path.join(a.run_dir, "train.jsonl"), "a")
    ranks = {r: int((train_g["rank"] == i).sum()) for i, r in enumerate(RANKS)}
    if init:  # rank embeddings the pretrain learned stay trained
        ranks = {r: ranks[r] + (init.get("ranks") or {}).get(r, 0) for r in RANKS}
    ranks["UNKNOWN"] = max(ranks["UNKNOWN"], 1)  # COND_DROP trains it on every dataset
    meta = dict(data_dir=os.path.abspath(a.data_dir), args=vars(a), params=n_params, ranks=ranks)
    if init:
        meta["init"] = dict(path=os.path.abspath(a.init), data_dir=init.get("data_dir"), step=init.get("step"))
    run_info = dict(meta, steps=a.steps, started_at=time.time(), train_frames=int(train_g["length"].sum()),
                    train_games=len(train_g["length"]), val_games=len(val_g["length"]))

    def write_run_info(**extra):
        with open(os.path.join(a.run_dir, "run.json"), "w") as fh:
            json.dump(dict(run_info, **extra), fh, indent=1)
    write_run_info()
    model.train()
    t0, seen, running = time.time(), 0, None
    for step, b in enumerate(loader, 1):
        b = {k: v.to(dev, non_blocking=True) for k, v in b.items()}
        with torch.autocast("cuda", torch.bfloat16):
            loss, parts, _ = loss_fn(fwd(b), b)
        for o in opts:
            o.zero_grad(set_to_none=True)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        for o, sc in zip(opts, scheds):
            o.step(); sc.step()
        seen += a.batch * c.context
        running = loss.item() if running is None else 0.98 * running + 0.02 * loss.item()
        if step % 100 == 0:
            el = time.time() - t0
            print(f"step {step} loss {running:.3f} lr {scheds[0].get_last_lr()[0]:.2e} "
                  f"{seen / el / 1e3:.0f}k frames/s, {el / 60:.1f} min", flush=True)
            curve.write(json.dumps(dict(step=step, loss=round(running, 4), lr=scheds[0].get_last_lr()[0],
                                        frames_per_s=round(seen / el), minutes=round(el / 60, 2))) + "\n")
            curve.flush()
        if step % a.eval_every == 0 or step == a.steps:
            v = evaluate()
            rec = dict(step=step, frames=seen, minutes=round((time.time() - t0) / 60, 2), train=round(running, 4),
                       **{k: round(x, 4) for k, x in v.items()})
            print(json.dumps(rec), flush=True)
            log.write(json.dumps(rec) + "\n"); log.flush()
            save(os.path.join(a.run_dir, "last.pt"), model, dict(meta, step=step, val=v))
        if step >= a.steps:
            write_run_info(finished_at=time.time())
            break


if __name__ == "__main__":
    main()
