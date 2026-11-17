"""Teach HAL's model to play with input delay from its own delayed games (DIDA, Liotet et al. 2022; docs/delay.md).

    python -m haltrain.dida RUN_DIR --players "hal:AMSA#0,return_target=40,delay=10" ... [--updates 2000]

With d frames of delay the bot, seeing the game up to frame t, has d actions on their way and picks the one for
t+d+1 from the model's "d+1 ahead" output (and, replanning every other frame, the one for t+d+2 from "d+2 ahead").
Human data cannot train that choice: its actions were all made with an up-to-date view. Here the model is trained
on games it played with delay. For a position t in such a game the input is what it had when it played (the game up
to t and the d actions that followed, which were already sent) and the label is an action sampled from a frozen
copy of the released model looking at the game up to t+d: what the no-delay bot would do, seeing the present.

Each update mixes --own microbatches of this loss with --human microbatches of HAL's own loss on aMSa's games, which
keeps the rest of the model (play without delay) where it was.

Games come from the league log: rows whose first player is one of --players, with `delay=N` in its spec; that
player is port 1. Every tenth game is held out and scored at each validation.
"""
import argparse
import json
import math
import re
import time
from pathlib import Path

import numpy as np
import torch

from . import WEIGHTS, load_model, save_bundle
from .finetune import HumanLoss, prepare
from .own import Games
from .validate import cohort, score

LEAGUE = Path.home() / "projects/ai/melee-llm/data/train/league/games.jsonl"
ARCHIVE = Path("/mnt/data/melee/league-replays")  # <worktree>/<folder>/Game_*.slp
LAST_DENSE = 12  # the model's outputs are one frame apart up to 12 ahead


def league_games(players, log=LEAGUE):
    """(replay, "p1", delay) for the league games of `players`. Replays of removed worktrees are in ARCHIVE."""
    archived = {p.name: p for p in ARCHIVE.glob("*/*/*.slp")}
    games = []
    for line in Path(log).read_text().splitlines():
        row = json.loads(line) if line.strip() else {}
        if row.get("a") in players and row.get("replay"):
            path = Path(row["replay"])
            path = path if path.exists() else archived.get(path.name)
            if path:
                games.append((path, "p1", int(re.search(r"delay=(\d+)", row["a"])[1])))
    return games


@torch.no_grad()
def expert_actions(temporal, hidden, ctx_pad, positions, observed, returns, present, generator):
    """An action for the frame after each position, sampled from the model's "1 ahead" output.

    The controller groups of one frame are decoded in order, each conditioned on the ones before, so this runs the
    decoder once per group and fills the frame in as it goes.
    """
    from hal.models.controller_codec import CONTROLLER_DECODE_ORDER, CONTROLLER_GROUP_INDEX

    targets = torch.zeros(*positions.shape, len(temporal.head_offsets), len(CONTROLLER_GROUP_INDEX),
                          dtype=torch.long, device=hidden.device)
    for name in CONTROLLER_DECODE_ORDER:
        logits = temporal.teacher_forced_logits_by_group(
            hidden, ctx_pad, positions, observed, targets, returns, present)[name][:, :, 0].float()
        picks = torch.multinomial(torch.softmax(logits.flatten(0, 1), -1), 1, generator=generator)
        targets[:, :, 0, CONTROLLER_GROUP_INDEX[name]] = picks.view(positions.shape)
    return targets[:, :, 0]


class DelayLoss:
    def __init__(self, m, cfg, teacher, return_target, prefixes, seed):
        self.m, self.cfg, self.teacher, self.return_target, self.prefixes = m, cfg, teacher, return_target, prefixes
        self.generator = torch.Generator("cuda").manual_seed(seed)

    def __call__(self, model, trunk_fn, temporal_fn, batch, delays, generator=None):
        """Bits per frame of the student's "d+1 ahead" (or "d+2 ahead") output on the expert's action."""
        m, cfg, generator = self.m, self.cfg, generator or self.generator
        batch = batch.to("cuda")
        start, length = cfg.arch.direct_loss_start, cfg.arch.L_ctx
        rows = torch.arange(len(delays), device="cuda")[:, None]
        d = torch.tensor(delays, device="cuda")[:, None]
        # the expert needs the game up to t+d+1, so t stops short of the end of the context
        t = torch.randint(start, length - LAST_DENSE, (len(delays), self.prefixes), device="cuda", generator=generator)
        # which of the two outputs the bot plays from this position trains: d+1 ahead, or d+2 where there is one
        second = (torch.rand(t.shape, device="cuda", generator=generator) < 0.5) & (d + 2 <= LAST_DENSE)
        ahead = d + 1 + second  # the expert looks at the game up to t + ahead - 1
        returns = torch.full(t.shape, self.return_target, device="cuda")
        present = torch.ones_like(t, dtype=torch.bool)
        history, targets, _ = m.prepared_targets(model, batch)
        with m.amp_context(cfg, "cuda"):
            with torch.no_grad():
                seen = t + ahead - 1
                labels = expert_actions(
                    self.teacher.temporal, self.teacher(batch.context.features, batch.context.ctx_pad, None),
                    batch.context.ctx_pad, seen, history[rows, seen - start], returns, present, generator)
            given = targets[rows, t - start].clone()  # the actions that followed t: sent already, up to t+d
            index = (ahead - 1)[..., None, None].expand(-1, -1, 1, given.shape[-1])
            given.scatter_(2, index, labels[:, :, None])
            nll = temporal_fn(trunk_fn(batch.context.features, batch.context.ctx_pad, None), batch.context.ctx_pad,
                              t, history[rows, t - start], given, returns, present)
            nll = nll[0] if isinstance(nll, tuple) else nll
        picked = nll.float().sum(-1).gather(2, (ahead - 1)[..., None])[..., 0]
        return picked.mean() / math.log(2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir", type=Path)
    ap.add_argument("--players", nargs="+", required=True, help="league specs of our bot, each with delay=N")
    ap.add_argument("--init", default=str(WEIGHTS))
    ap.add_argument("--teacher", default=str(WEIGHTS))
    ap.add_argument("--return-target", type=float, default=40.0, help="the steering both models play with")
    ap.add_argument("--data", default="/mnt/data/melee/hal-ft")
    ap.add_argument("--val", default="/mnt/data/melee/hal-val")
    ap.add_argument("--updates", type=int, default=2000)
    ap.add_argument("--micro", type=int, default=16)
    ap.add_argument("--own", type=int, default=2, help="microbatches of the delay loss per update")
    ap.add_argument("--human", type=int, default=2, help="microbatches of HAL's loss on aMSa's games per update")
    ap.add_argument("--prefixes", type=int, default=32, help="positions per window for the delay loss")
    ap.add_argument("--lr-scale", type=float, default=0.05)
    ap.add_argument("--warmup", type=int, default=100)
    ap.add_argument("--val-every", type=int, default=250)
    ap.add_argument("--log-every", type=int, default=25)
    ap.add_argument("--compile", action="store_true")
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    torch.manual_seed(a.seed)
    a.run_dir.mkdir(parents=True, exist_ok=True)
    m, cfg, model, artifact, optimizer, base, trunk_fn, temporal_fn = prepare(a.init, a.compile)
    teacher, _ = load_model(a.teacher)
    teacher.eval().requires_grad_(False)
    teacher.trunk.resolve_attention("cuda")
    listed = league_games(a.players)
    train = Games([g for i, g in enumerate(listed) if i % 10], artifact.statistics)
    held = Games([g for i, g in enumerate(listed) if i % 10 == 0], artifact.statistics)
    delay_loss = DelayLoss(m, cfg, teacher, a.return_target, a.prefixes, a.seed)
    human = HumanLoss(a.data, artifact.statistics, cfg, a.micro, a.seed) if a.human else None
    _, human_val = cohort(a.val, 0, only_amsa=True)
    rng = np.random.default_rng(a.seed)
    held_batches = [held.sample(a.micro, np.random.default_rng(1)) for _ in range(16)]
    log = open(a.run_dir / "log.jsonl", "a")
    setup = {"kind": "haltrain.dida", "args": {k: str(v) for k, v in vars(a).items()}, "started_at": time.time(),
             "games": {"train": len(train.samples), "held_out": len(held.samples),
                       "skipped": len(train.skipped) + len(held.skipped), "train_frames": int(train.frames.sum())}}
    (a.run_dir / "run.json").write_text(json.dumps(setup, indent=1))
    print(setup["games"], flush=True)

    def validate(update):
        model.eval()
        fixed = torch.Generator("cuda").manual_seed(1)
        with torch.no_grad():
            own = [float(delay_loss(model, trunk_fn, temporal_fn, b, d, fixed)) for b, d in held_batches]
        full = score(model, cfg, human_val, a.micro)
        model.train()
        row = {"update": update, "val": {"delay_bits": round(sum(own) / len(own), 4),
                                         "human_bits": round(m._validation_wandb_metrics(full, cfg)["nll"], 4),
                                         **{f"human_o{o}": round(full[f"nll_o{o:02d}"], 4) for o in (1, 11, 12)}}}
        log.write(json.dumps(row) + "\n"); log.flush(); print(row, flush=True)

    validate(0)
    started, acc, parts = time.monotonic(), {}, a.own + a.human
    try:
        for update in range(1, a.updates + 1):
            for g, lr in zip(optimizer.param_groups, base):
                g["lr"] = lr * a.lr_scale * min(1.0, update / max(a.warmup, 1))
            optimizer.zero_grad()
            for _ in range(a.own):
                loss = delay_loss(model, trunk_fn, temporal_fn, *train.sample(a.micro, rng))
                if not bool(torch.isfinite(loss)):
                    raise FloatingPointError(f"update {update}: delay loss is not finite")
                (loss / parts).backward()
                acc["delay_bits"] = acc.get("delay_bits", 0.0) + float(loss) / a.own
            for _ in range(a.human):
                loss, metrics = human(model, trunk_fn, temporal_fn)
                (loss / parts).backward()
                acc["human_bits"] = acc.get("human_bits", 0.0) + float(metrics["train/loss"]) / a.human
            acc["grad_norm"] = acc.get("grad_norm", 0.0) + float(
                torch.nn.utils.clip_grad_norm_(model.parameters(), cfg.grad_clip))
            optimizer.step()
            if update % a.log_every == 0:
                row = {"update": update, "minutes": round((time.monotonic() - started) / 60, 2),
                       "peak_gb": round(torch.cuda.max_memory_allocated() / 2**30, 2),
                       **{k: round(v / a.log_every, 4) for k, v in acc.items()}}
                log.write(json.dumps(row) + "\n"); log.flush(); print(row, flush=True)
                acc = {}
            if update % a.val_every == 0 or update == a.updates:
                validate(update)
    finally:
        if human:
            human.close()
    save_bundle(model, a.init, a.run_dir / "last.hal", name=a.run_dir.name)


if __name__ == "__main__":
    main()
