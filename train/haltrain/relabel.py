"""What the no-delay teacher would have done on every frame of farm games played with delay (DIDA, docs/delay.md).

    python -m haltrain.relabel /mnt/data/melee/farm/student-1/d10-FOX ... [--return-target 40]

For each game of a farm folder (haltrain.farm --out), FOLDER/labels/<game>.npy gets one row per frame: the action
the released model, seeing the game up to frame f-1 with nothing pending, samples for frame f, as class indices
per controller group. Rows it has no label for (the first 129 frames, mostly the countdown) are -1.

A student trained for delay d pairs these with what it would have had at the time: the game up to f-d-1 and the d
actions that were already on their way.
"""
import argparse
import json
import time
from pathlib import Path

import numpy as np
import torch

from . import WEIGHTS, load_model, o59
from .dida import expert_actions
from .own import Games


def relabel(folder, teacher, artifact, return_target, micro, generator):
    m = o59()
    folder = Path(folder)
    (folder / "labels").mkdir(exist_ok=True)
    rows = [json.loads(line) for line in (folder / "results.jsonl").read_text().splitlines()]
    games = Games([(folder / r["tape"], f"p{r['a_port']}", r) for r in rows], artifact.statistics)
    cfg = games.cfg
    start, length = cfg.arch.direct_loss_start, cfg.arch.L_ctx
    positions = torch.arange(start, length, device="cuda")
    done = 0
    for g, (sample, _, row) in enumerate(games.samples):
        frames = int(games.frames[g])
        labels = np.full((frames, 4), -1, np.int16)
        starts = sorted({*range(0, frames - games.length + 1, length - start), frames - games.length})
        for i in range(0, len(starts), micro):
            chunk = starts[i:i + micro]
            batch = games.batch([games.window(g, s) for s in chunk]).to("cuda")
            where = positions.expand(len(chunk), -1)
            with torch.no_grad(), m.amp_context(cfg, "cuda"):
                history, _, _ = m.prepared_targets(teacher, batch)
                hidden = teacher(batch.context.features, batch.context.ctx_pad, None)
                picked = expert_actions(teacher.temporal, hidden, batch.context.ctx_pad, where, history,
                                        torch.full(where.shape, return_target, device="cuda"),
                                        torch.ones_like(where, dtype=torch.bool), generator)
            for s, rows_ in zip(chunk, picked.cpu().numpy()):
                labels[s + start + 1:s + length + 1] = rows_
        np.save(folder / "labels" / (Path(row["tape"]).stem + ".npy"), labels)
        done += frames
    return len(games.samples), done


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("folders", nargs="+", type=Path)
    ap.add_argument("--teacher", default=str(WEIGHTS))
    ap.add_argument("--return-target", type=float, default=40.0)
    ap.add_argument("--micro", type=int, default=8)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    torch.set_float32_matmul_precision("high")
    teacher, artifact = load_model(a.teacher)
    teacher.eval().requires_grad_(False)
    teacher.trunk.resolve_attention("cuda")
    generator = torch.Generator("cuda").manual_seed(a.seed)
    for folder in a.folders:
        if (folder / "labels" / "done").exists():
            continue
        started = time.monotonic()
        games, frames = relabel(folder, teacher, artifact, a.return_target, a.micro, generator)
        (folder / "labels" / "done").touch()
        print(f"{folder.name}: {games} games, {frames:,} frames in {(time.monotonic() - started) / 60:.1f} min", flush=True)


if __name__ == "__main__":
    main()
