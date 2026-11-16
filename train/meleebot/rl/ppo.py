"""Self-play PPO in melee-sim-light, starting from a behaviour-cloned run.

    uv run python -m meleebot.rl.ppo INIT_CKPT RUN_DIR [--envs 256] [--iters 1000] [--pool teacher:0.5,self:0.5]

The learner plays Yoshi on side 0 of every match, at a fixed input delay. Side 1 is an opponent from the pool;
each match slot keeps its opponent group:
- teacher: the starting model, frozen, as Yoshi (the learner must stay better than where it started)
- self: a copy of the learner refreshed every --snapshot-every iterations, as Yoshi
- other: the --other-run checkpoint (e.g. the all-character pretrain) as one of --other-chars

Each iteration plays --unroll frames in every match, then updates on windows of the previous and current
unroll (the previous one is context only). Old log-probabilities and values are recomputed on those windows
before the update, so PPO's ratio compares like with like. Loss: dual-clipped policy loss + KL(learner || teacher)
* --kl, which keeps it near human-like play, - an entropy bonus that only switches on while entropy is below
--entropy-target (the first run collapsed to a near-deterministic policy and then diverged); a separate value
head reads the trunk without training it. Steps with a non-finite loss or gradient are skipped and counted.
Reward per frame: stocks taken - stocks lost + --damage * (damage dealt - taken).

Writes RUN_DIR/rl.jsonl (one line per iteration), last.pt (a normal meleebot checkpoint, playable by the
league and bots), value.pt, snap-NNNNN.pt every --save-every iterations, run.json, and .slp replays (--replay-dir): one game per
pool group every --replay-minutes, the learner on port 1.
"""
import argparse
import copy
import json
import os
import time

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

from .. import features as fe
from ..model import HEADS, load, save
from ..schema import CHARACTERS
from .env import STAGE_IDS, SelfPlay, reward, to_inputs
from .policy import Actor
from .replays import Recorder


def parse_pool(spec):
    out = []
    for part in spec.split(","):
        name, _, w = part.partition(":")
        out.append((name, float(w or 1)))
    total = sum(w for _, w in out)
    return [(n, w / total) for n, w in out]


def logits_for(model, b, mask, pos):
    """Per-head logits with teacher forcing on the chosen classes in b, plus the trunk output."""
    h = model.trunk(b, pos, mask=mask)
    out, x = [], h
    for i, name in enumerate(HEADS):
        out.append(model.out[i](x).float())
        if i < len(model.given):
            x = x + model.given[i](b[name])
    return out, h


def logprob(logits, b):
    return sum(F.log_softmax(lg, -1).gather(-1, b[name][..., None])[..., 0] for lg, name in zip(logits, HEADS))


def kl(logits, ref):
    """KL(p || q) summed over heads, each conditioned on the same chosen earlier heads."""
    total = 0
    for lp, lq in zip(logits, ref):
        lp, lq = F.log_softmax(lp, -1), F.log_softmax(lq, -1)
        total = total + (lp.exp() * (lp - lq)).sum(-1)
    return total


def entropy(logits):
    return sum(-(F.softmax(lg, -1) * F.log_softmax(lg, -1)).sum(-1) for lg in logits)


class Value(nn.Module):
    def __init__(self, w):
        super().__init__()
        self.net = nn.Sequential(nn.LayerNorm(w), nn.Linear(w, w), nn.GELU(), nn.Linear(w, w), nn.GELU(), nn.Linear(w, 1))

    def forward(self, h):
        return self.net(h.float())[..., 0]


def window_mask(game, active):
    """(B,1,T,T): causal, within one game, only active tokens (each token always sees itself), as the ring does."""
    T = game.shape[1]
    causal = torch.ones(T, T, dtype=torch.bool, device=game.device).tril()
    same = (game[:, :, None] == game[:, None, :]) & active[:, None, :]
    return ((same & causal) | torch.eye(T, dtype=torch.bool, device=game.device))[:, None]


def gae(r, v, terminal, active, gamma, lam):
    """r, v, terminal, active: (U, n). Returns advantages and returns for tokens 0..U-2 (the last one only
    bootstraps). A terminal token's next value is 0; tokens after a game's end belong to the next game."""
    U = r.shape[0]
    adv = np.zeros((U - 1,) + r.shape[1:], np.float32)
    nxt = np.zeros(r.shape[1:], np.float32)
    for u in range(U - 2, -1, -1):
        go_on = (~terminal[u]) & active[u + 1]
        delta = r[u] + gamma * v[u + 1] * go_on - v[u]
        nxt = np.where(active[u], delta + gamma * lam * go_on * nxt, 0)
        adv[u] = nxt
    return adv, adv + v[:-1]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("init", help="checkpoint to start from (also the frozen teacher)")
    ap.add_argument("run_dir")
    ap.add_argument("--envs", type=int, default=256)
    ap.add_argument("--unroll", type=int, default=128)
    ap.add_argument("--iters", type=int, default=1000)
    ap.add_argument("--delay", type=int, default=3)
    ap.add_argument("--pool", default="teacher:0.4,self:0.6")
    ap.add_argument("--other-run", help="checkpoint for the `other` pool group")
    ap.add_argument("--other-chars", default="FOX,FALCO,MARTH,SHEIK,FALCON,PUFF,PEACH")
    ap.add_argument("--snapshot-every", type=int, default=20)
    ap.add_argument("--save-every", type=int, default=50)
    ap.add_argument("--lr", type=float, default=1e-5)
    ap.add_argument("--value-lr", type=float, default=3e-4)
    ap.add_argument("--value-warmup", type=int, default=10, help="iterations that train only the value head")
    ap.add_argument("--epochs", type=int, default=2)
    ap.add_argument("--minibatch", type=int, default=32, help="windows per gradient step")
    ap.add_argument("--clip", type=float, default=0.2)
    ap.add_argument("--kl", type=float, default=0.1)
    ap.add_argument("--dual-clip", type=float, default=3.0, help="bound on the loss of negative-advantage tokens whose ratio blew up")
    ap.add_argument("--entropy-target", type=float, default=0.3,
                    help="summed over heads; an entropy bonus grows while the policy is below it (0: off)")
    ap.add_argument("--gamma", type=float, default=0.997)
    ap.add_argument("--lam", type=float, default=0.95)
    ap.add_argument("--damage", type=float, default=0.01)
    ap.add_argument("--max-frame", type=int, default=8 * 3600)
    ap.add_argument("--replay-minutes", type=float, default=10, help="record one game per pool group this often")
    ap.add_argument("--replay-dir", help="default: the live repo's replays/rl/<run name>, which the web UI lists")
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    os.makedirs(a.run_dir, exist_ok=True)
    dev = torch.device("cuda")
    torch.manual_seed(a.seed)
    torch.set_float32_matmul_precision("high")

    model, ck = load(a.init, dev)
    teacher = copy.deepcopy(model).requires_grad_(False)
    snapshot = copy.deepcopy(model).requires_grad_(False)
    value = Value(model.config.width).to(dev)
    other = load(a.other_run, dev)[0].requires_grad_(False) if a.other_run else None
    opt = torch.optim.AdamW(model.parameters(), lr=a.lr, weight_decay=0.0)
    vopt = torch.optim.AdamW(value.parameters(), lr=a.value_lr)

    # match slots -> opponent group
    pool = parse_pool(a.pool)
    counts = np.floor(np.array([w for _, w in pool]) * a.envs).astype(int)
    counts[0] += a.envs - counts.sum()
    group = np.repeat(np.arange(len(pool)), counts)
    yoshi = CHARACTERS.index("YOSHI")
    other_chars = [CHARACTERS.index(c) for c in a.other_chars.split(",")]

    def matchup(rng, i):
        name = pool[group[i]][0]
        opp = rng.choice(other_chars) if name == "other" else yoshi
        return rng.choice(STAGE_IDS), yoshi, opp

    env = SelfPlay(a.envs, matchup, seed=a.seed, max_frame=a.max_frame)
    nets = {"teacher": teacher, "self": snapshot, "other": other}
    learner = Actor(model, ck, np.arange(a.envs), 0, delay=a.delay)
    opponents = []
    for g, (name, _) in enumerate(pool):
        if nets[name] is None:
            raise SystemExit(f"pool group {name} needs --other-run")
        idx = np.flatnonzero(group == g)
        if len(idx):
            opponents.append((name, Actor(nets[name], ck, idx, 1, delay=a.delay)))

    replay_dir = a.replay_dir or os.path.expanduser(f"~/projects/ai/melee-llm/replays/rl/{os.path.basename(os.path.abspath(a.run_dir))}")
    recorder = Recorder(env, replay_dir)
    first = {g: int(np.flatnonzero(group == g)[0]) for g in range(len(pool)) if (group == g).any()}
    last_armed = -1e9
    U, n = a.unroll, a.envs
    inputs = np.zeros((n, 2), env.env.raw_action_view.dtype["players"].base)
    frames, fid = env.frames.copy(), env.frame_id.copy()
    last_done = np.zeros(n, bool)
    prev = None  # previous unroll's records: context for this one's windows
    stats = dict(games=0, wins=np.zeros(len(pool)), played=np.zeros(len(pool)))
    log = open(os.path.join(a.run_dir, "rl.jsonl"), "a")
    with open(os.path.join(a.run_dir, "run.json"), "w") as f:
        json.dump(dict(kind="rl", args=vars(a), params=sum(p.numel() for p in model.parameters()), replays=replay_dir,
                       init=os.path.abspath(a.init), pool=[name for name, _ in pool], started_at=time.time()), f, indent=1)
    meta = {k: v for k, v in ck.items() if k not in ("config", "state")} | dict(rl=vars(a), init=os.path.abspath(a.init))
    t_start, frames_total = time.time(), 0
    ent_coef = 0.0
    keys = ("num", "actions", "me_char", "opp_char", "stage", "delay", "rank", "win")

    for it in range(1, a.iters + 1):
        t0 = time.time()
        rec = {k: [] for k in (*keys, *HEADS, "reward", "terminal", "active", "game", "age")}
        model.eval()
        for u in range(U):
            start, active = fid == 0, (fid >= 0) & ~last_done
            tok = learner.tokens(frames[:, 0], start, env.chars, env.stage)
            choice = learner.act(tok, start, active)
            to_inputs(choice, learner.centers, inputs[:, 0])
            for name, actor in opponents:
                i = actor.idx
                otok = actor.tokens(frames[i, 1], start[i], env.chars[i, ::-1], env.stage[i])
                inputs[i, 1] = to_inputs(actor.act(otok, start[i], active[i]), actor.centers, np.zeros(len(i), inputs.dtype))
            for k in keys:
                rec[k].append(tok[k])
            for k in HEADS:
                rec[k].append(choice[k])
            rec["active"].append(active)
            rec["game"].append(learner.game.cpu().numpy())
            rec["age"].append(learner.age.copy())
            before = frames
            out, done, fresh = env.step(inputs)
            if time.time() - last_armed > a.replay_minutes * 60:
                last_armed = time.time()
                for g, i in first.items():
                    recorder.arm(i, f"it{it:05d}-yoshi-vs-{pool[g][0]}")
            recorder.after_step(done, fresh)
            frames = out.copy()
            r = reward(before[:, 0], frames[:, 0], a.damage)
            r[fresh] = 0
            rec["reward"].append(np.where(active, r, 0).astype(np.float32))
            rec["terminal"].append(done)
            for i in np.flatnonzero(done):
                g = group[i]
                stats["played"][g] += 1
                stats["wins"][g] += {0: 1.0, 1: 0.0, -1: 0.5}[env.winner(i)]
            last_done, fid = done, env.frame_id.copy()
        frames_total += U * n
        t_roll = time.time() - t0
        cur = {k: np.stack(v, 1) for k, v in rec.items()}   # (n, U, ...)
        ctx = prev if prev is not None else {k: v[:, :0] for k, v in cur.items()}
        prev = cur
        win = {k: np.concatenate([ctx[k], cur[k]], 1) for k in cur}   # (n, C+U, ...)
        C = ctx["active"].shape[1]
        def batch(ix):  # conditions stay per token: a window may span two games with different matchups
            b = {k: torch.as_tensor(win[k][ix], device=dev) for k in (*keys, *HEADS)}
            game = torch.as_tensor(win["game"][ix], device=dev)
            act = torch.as_tensor(win["active"][ix], device=dev)
            pos = torch.as_tensor(win["age"][ix], device=dev)
            return b, window_mask(game, act), pos

        # old log-probs, teacher logits and values on the windows, before any update
        old_lp, vals = np.zeros((n, U), np.float32), np.zeros((n, U), np.float32)
        with torch.no_grad(), torch.autocast("cuda", torch.bfloat16):
            for s in range(0, n, a.minibatch):
                ix = np.arange(s, min(n, s + a.minibatch))
                b, mask, pos = batch(ix)
                lg, h = logits_for(model, b, mask, pos)
                old_lp[ix] = logprob(lg, b)[:, C:].float().cpu().numpy()
                vals[ix] = value(h)[:, C:].float().cpu().numpy()
        adv, ret = gae(cur["reward"].T, vals.T, cur["terminal"].T, cur["active"].T, a.gamma, a.lam)
        adv, ret = adv.T, ret.T   # (n, U-1)
        train_mask = cur["active"][:, :-1]

        pol = it > a.value_warmup
        model.eval()   # no dropout: the policy that acted is the one we score
        agg = dict(pg=0.0, vf=0.0, kl=0.0, ent=0.0, clip=0.0, steps=0, pol_steps=0, skipped=0)
        for _ in range(a.epochs):
            for s in np.random.permutation(range(0, n, a.minibatch)):
                ix = np.arange(s, min(n, s + a.minibatch))
                b, mask, pos = batch(ix)
                m = torch.as_tensor(train_mask[ix], device=dev).float()
                if m.sum() == 0:
                    continue
                A = torch.as_tensor(adv[ix], device=dev)
                A = (A - (A * m).sum() / m.sum()) / (((A - (A * m).sum() / m.sum()) ** 2 * m).sum() / m.sum()).sqrt().clamp_min(1e-6)
                R = torch.as_tensor(ret[ix], device=dev)
                olp = torch.as_tensor(old_lp[ix, :-1], device=dev)
                with torch.autocast("cuda", torch.bfloat16):
                    lg, h = logits_for(model, b, mask, pos)
                    v = value(h.detach())[:, C:-1]
                    vf = (((v - R) ** 2) * m).sum() / m.sum()
                    if pol:
                        with torch.no_grad():
                            tlg, _ = logits_for(teacher, b, mask, pos)
                        lg_new = [x[:, C:-1] for x in lg]
                        lp = logprob(lg_new, {k: b[k][:, C:-1] for k in HEADS})
                        ratio = (lp - olp).clamp(max=20).exp()   # bounded so a rare action's huge ratio can't overflow
                        surr = torch.min(ratio * A, ratio.clamp(1 - a.clip, 1 + a.clip) * A)
                        surr = torch.where(A < 0, torch.max(surr, a.dual_clip * A), surr)
                        pg = -(surr * m).sum() / m.sum()
                        k_l = (kl(lg_new, [x[:, C:-1] for x in tlg]) * m).sum() / m.sum()
                        ent = (entropy(lg_new) * m).sum() / m.sum()
                        loss = pg + a.kl * k_l - ent_coef * ent
                        opt.zero_grad(set_to_none=True)
                        loss.backward()
                        gn = torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                        if torch.isfinite(loss) and torch.isfinite(gn):
                            opt.step()
                            agg["pg"] += pg.item(); agg["kl"] += k_l.item(); agg["ent"] += ent.item()
                            agg["clip"] += (((ratio - 1).abs() > a.clip).float() * m).sum().item() / m.sum().item()
                            agg["pol_steps"] += 1
                        else:
                            agg["skipped"] += 1
                vopt.zero_grad(set_to_none=True)
                vf.backward()
                vopt.step()
                agg["vf"] += vf.item(); agg["steps"] += 1
        if pol and it % a.snapshot_every == 0:
            snapshot.load_state_dict(model.state_dict())

        n_pol, skipped = agg.pop("pol_steps"), agg.pop("skipped")
        steps, pol_steps = max(agg.pop("steps"), 1), max(n_pol, 1)
        if n_pol and a.entropy_target > 0:   # multiplicative controller on the bonus, like SAC's temperature
            ent_coef = min(max(ent_coef, 1e-4) * (1.5 if agg["ent"] / pol_steps < a.entropy_target else 1 / 1.5), 0.1)
            ent_coef = 0.0 if ent_coef < 1e-4 else ent_coef
        line = dict(iter=it, frames=frames_total, minutes=round((time.time() - t_start) / 60, 2),
                    fps=round(U * n / (time.time() - t0)), rollout_s=round(t_roll, 2),
                    reward_per_min=round(float(cur["reward"].sum() / max(cur["active"].sum(), 1) * 3600), 4),
                    vf=round(agg.pop("vf") / steps, 5), **{k: round(v / pol_steps, 5) for k, v in agg.items()},
                    ent_coef=round(ent_coef, 5), skipped=skipped,
                    games=int(stats["played"].sum()),
                    played={pool[g][0]: int(stats["played"][g]) for g in range(len(pool))},
                    won={pool[g][0]: float(stats["wins"][g]) for g in range(len(pool))})
        stats["wins"][:], stats["played"][:] = 0, 0
        print(json.dumps(line), flush=True)
        log.write(json.dumps(line) + "\n"); log.flush()
        if it % a.save_every == 0 or it == a.iters:
            extra = dict(meta, step=it, frames=frames_total)
            save(os.path.join(a.run_dir, "last.pt"), model, extra)
            torch.save(value.state_dict(), os.path.join(a.run_dir, "value.pt"))
            if it % a.save_every == 0:
                save(os.path.join(a.run_dir, f"snap-{it:05d}.pt"), model, extra)


if __name__ == "__main__":
    main()
