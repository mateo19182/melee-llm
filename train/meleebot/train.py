"""Behaviour cloning on a dataset built by build_dataset.

    uv run python -m meleebot.train DATA_DIR RUN_DIR [--steps N] [--overfit-game G]

--overfit-game trains on one game only; the loss should fall close to zero, otherwise the
pipeline has a bug.
"""
import argparse, json, math, os, time

import numpy as np
import torch
import torch.nn.functional as F

from . import features as fe
from .model import HEADS, Config, Policy, save
from .schema import FRAME

COND_DROP = 0.1   # share of windows trained without rank / result, so both can be left unknown at play time


class Windows(torch.utils.data.IterableDataset):
    def __init__(self, data_dir, games, stick_centers, batch, context, seed):
        self.data_dir, self.g, self.centers = data_dir, games, stick_centers
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
        delay = rng.integers(0, fe.MAX_DELAY + 1, B)
        num = np.empty((B, T, fe.NUM), np.float32)
        actions = np.empty((B, T, 2), np.int64)
        target = np.empty((B, T), FRAME["me_pad"])
        for i in range(B):
            off = int(self.g["offset"][gi[i]])
            game = np.asarray(frames[off + within[i]: off + within[i] + fe.MAX_DELAY + T + 1])
            num[i], actions[i], target[i] = fe.window(game, fe.MAX_DELAY, T, delay[i])
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


def norm_stats(frames, rng, n=200_000):
    idx = np.sort(rng.choice(len(frames) - 1, n, replace=False))
    f = np.asarray(frames[idx])
    num = np.concatenate([fe.player_num(f["me"]), fe.player_num(f["opp"]),
                          fe.pad_num(f["me_pad"]), fe.pad_num(f["opp_pad"])], -1)
    return num.mean(0), np.maximum(num.std(0), 1e-3), f["me_pad"]


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
    a = ap.parse_args()

    os.makedirs(a.run_dir, exist_ok=True)
    torch.manual_seed(0)
    rng = np.random.default_rng(0)
    games = dict(np.load(os.path.join(a.data_dir, "games.npz")))
    frames = np.memmap(os.path.join(a.data_dir, "frames.bin"), FRAME, "r")
    mean, std, pads = norm_stats(frames, rng)
    if a.overfit_game is not None:
        train_g = val_g = subset(games, np.arange(len(games["length"])) == a.overfit_game)
        dropout = 0.0
    else:
        train_g, val_g, dropout = subset(games, games["val"] == 0), subset(games, games["val"] == 1), 0.1

    c = Config(layers=a.layers, width=a.width, heads=a.width // 32, context=a.context, dropout=dropout, pos=a.pos)
    model = Policy(c)
    model.num_mean.copy_(torch.from_numpy(mean)); model.num_std.copy_(torch.from_numpy(std))
    centers = fe.kmeans_stick(pads, c.n_stick)
    model.stick_centers.copy_(torch.from_numpy(centers))
    dev = "cuda"
    model.to(dev)
    fwd = torch.compile(model) if a.compile else model   # `model` stays uncompiled for saving
    n_params = sum(p.numel() for p in model.parameters())
    print(f"{n_params / 1e6:.1f}M params, train {train_g['length'].sum() / 1e6:.0f}M frames "
          f"in {len(train_g['length'])} games, val {len(val_g['length'])} games", flush=True)

    decay = [p for n, p in model.named_parameters() if p.dim() >= 2 and "weight" in n and "ln" not in n]
    other = [p for p in model.parameters() if all(p is not q for q in decay)]
    opt = torch.optim.AdamW([dict(params=decay, weight_decay=0.05), dict(params=other, weight_decay=0)],
                            lr=a.lr, betas=(0.9, 0.95), fused=True)
    warmup = min(1000, a.steps // 10)
    sched = torch.optim.lr_scheduler.LambdaLR(opt, lambda s: min(1, (s + 1) / warmup) * (
        0.1 + 0.9 * 0.5 * (1 + math.cos(math.pi * min(1, s / a.steps)))))

    loader = torch.utils.data.DataLoader(Windows(a.data_dir, train_g, centers, a.batch, c.context, 1),
                                         batch_size=None, num_workers=a.workers, pin_memory=True,
                                         persistent_workers=True, prefetch_factor=4)
    val_maker = Windows(a.data_dir, val_g, centers, a.batch, c.context, 2)
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
    meta = dict(data_dir=os.path.abspath(a.data_dir), args=vars(a), params=n_params)
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
        opt.zero_grad(set_to_none=True)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        opt.step(); sched.step()
        seen += a.batch * c.context
        running = loss.item() if running is None else 0.98 * running + 0.02 * loss.item()
        if step % 100 == 0:
            el = time.time() - t0
            print(f"step {step} loss {running:.3f} lr {sched.get_last_lr()[0]:.2e} "
                  f"{seen / el / 1e3:.0f}k frames/s, {el / 60:.1f} min", flush=True)
            curve.write(json.dumps(dict(step=step, loss=round(running, 4), lr=sched.get_last_lr()[0],
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
