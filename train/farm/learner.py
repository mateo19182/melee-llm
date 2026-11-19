"""Faynt's RL learner (Faynt paper, section 4.4 and appendix E.6): score stored rollouts, PPO with KL leashes.

The actor plays with a rolling 256-frame attention cache. To score a 128-frame rollout with exactly the history the
actor had, the learner keeps a copy of that cache from the rollout's first frame and runs the rollout in parallel
against it (`score`): frame t sees the cached frames younger than 256 - t and the rollout frames up to t, with game
boundaries cutting both. At unchanged weights this reproduces the actor's distributions (`python -m farm.rl --check`).

The value network is separate (two Transformer blocks of width 128 with its own frame encoder, as in the paper) and
reads the 128 frames before each rollout together with the rollout.
"""
import dataclasses
import sys

import torch
import torch.nn.functional as F


def native(policy):
    """Faynt's faynt_native module, which transformers loads under its own package name."""
    return sys.modules[type(policy).__module__]


@dataclasses.dataclass
class Snapshot:
    """An actor cache at a rollout's first frame, as chronological per-layer keys and values (newest last)."""
    keys: torch.Tensor  # [layers, seats, capacity, kv_heads, head_dim]
    values: torch.Tensor
    length: torch.Tensor  # [seats] valid entries, aligned to the end
    position: torch.Tensor  # [seats] RoPE position of the next frame

    @classmethod
    def take(cls, cache):
        """Copy a ring cache, in the slot order farm.faynt.batched_cache writes (fills from 0, wraps)."""
        cap = cache.capacity
        idx = (cache.write_position[:, None] - cap + torch.arange(cap, device=cache.keys.device)) % cap  # [S, C]
        gather = idx[None, :, :, None, None].expand(cache.keys.shape[0], -1, -1, *cache.keys.shape[3:])
        return cls(keys=cache.keys.gather(2, gather), values=cache.values.gather(2, gather),
                   length=cache.valid_length.clone(), position=cache.next_position.clone())

    def to(self, device):
        return Snapshot(*(t.to(device, non_blocking=True) for t in dataclasses.astuple(self)))


def _attention(layer, normed, positions, prefix_k, prefix_v, mask):
    """One GroupedQueryCausalAttention over [prefix keys (stored, already rotated) + this rollout's keys]."""
    att = layer.attention
    q, k, v = att._project(normed, positions)  # [S, H, T, D], [S, Hkv, T, D]
    k = torch.cat([prefix_k.permute(0, 2, 1, 3).to(k.dtype), k], dim=2)
    v = torch.cat([prefix_v.permute(0, 2, 1, 3).to(v.dtype), v], dim=2)
    out = att._sdpa(q, k, v, attention_mask=mask, is_causal=False)
    return att._apply_output_gate(out, normed)


def score(policy, game, prev, target, reset, snap, valid=None):
    """Teacher-forced controller logits for a rollout. `game`: tensor_batch game states [S, T]; `prev`: the
    controller labels the model reads at each frame (p0's current controller); `target`: the sampled labels;
    `reset[s, t]`: a game starts at frame t; `snap`: the actor's cache at frame 0. Returns {buttons, main_stick}."""
    backbone, head = policy.backbone, policy.controller_head
    S, T = reset.shape
    dev = reset.device
    labels = native(policy)._controller_labels(policy.codec, prev)
    encoded = policy.encoder(game, labels)
    projected = backbone.input_projection(encoded)

    t = torch.arange(T, device=dev)
    last_reset = torch.cummax(torch.where(reset, t, -1), dim=1).values  # [S, T]
    positions = torch.where(last_reset >= 0, t - last_reset, snap.position[:, None] + t)
    C = snap.keys.shape[2]
    j = torch.arange(C, device=dev)
    prefix_ok = ((last_reset < 0)[:, :, None] & (j[None, None, :] >= C - snap.length[:, None, None])
                 & (j[None, None, :] >= t[None, :, None] + 1))  # [S, T, C]: younger than 256 - t, same game
    seg = torch.cumsum(reset.long(), dim=1)
    own_ok = (seg[:, :, None] == seg[:, None, :]) & (t[None, :, None] >= t[None, None, :])
    if valid is not None:
        own_ok = own_ok & valid[:, None, :]
    mask = torch.cat([prefix_ok, own_ok], dim=2)[:, None]  # [S, 1, T, C + T]

    values = [projected]
    for i, layer in enumerate(backbone.layers):
        x = layer.attention_residual(values)
        values.append(layer.attention_dropout(_attention(layer, layer.attention_norm(x), positions,
                                                         snap.keys[i], snap.values[i], mask)))
        values.append(backbone._ffn_transform(layer, layer.ffn_residual(values)))
    hidden = backbone.final_norm(backbone.output_residual(values))
    return head(hidden, previous_controller=prev, teacher_forcing_targets=target).logits


def log_probs(logits):
    return {k: F.log_softmax(v.float(), dim=-1) for k, v in logits.items()}


def chosen(logp, buttons, stick):
    """log pi(a) of the sampled (buttons, main stick) pair."""
    return (logp["buttons"].gather(-1, buttons[..., None])[..., 0]
            + logp["main_stick"].gather(-1, stick[..., None])[..., 0])


def kl(p, q):
    """KL(p || q) per decision, summed over both heads; the stick term is at the sampled joint category (all three
    distributions were teacher-forced with it), as in the paper."""
    return sum((p[k].exp() * (p[k] - q[k])).sum(-1) for k in ("buttons", "main_stick"))


def entropy(p):
    return sum(-(p[k].exp() * p[k]).sum(-1) for k in ("buttons", "main_stick"))


class Value(torch.nn.Module):
    """V(history): a small Faynt-architecture backbone with its own encoder and a scalar head."""

    def __init__(self, model):
        super().__init__()
        cfg = dataclasses.replace(model.config.to_native_config(), n_layers=2, d_model=128, d_ff=256, n_heads=2,
                                  n_kv_heads=1, head_dim=64)
        net = native(model.policy).MeleePolicy(cfg)
        self.encoder, self.backbone, self.codec = net.encoder, net.backbone, net.codec
        self.head = torch.nn.Linear(128, 1)
        torch.nn.init.zeros_(self.head.weight)
        torch.nn.init.zeros_(self.head.bias)

    def forward(self, game, prev, reset, valid):
        encoded = self.encoder(game, native(self.backbone)._controller_labels(self.codec, prev))
        hidden, _ = self.backbone(encoded, reset_mask=reset, padding_mask=valid)
        return self.head(hidden)[..., 0].float()


def returns(reward, done, value, bootstrap, gamma):
    """Bootstrapped discounted returns over one rollout. reward/done/value: [S, T]; bootstrap: [S], V after the last
    frame. A done frame's transition ends its game: nothing after it counts."""
    G = torch.empty_like(reward)
    g = bootstrap
    for t in range(reward.shape[1] - 1, -1, -1):
        g = reward[:, t] + gamma * torch.where(done[:, t], 0.0, g)
        G[:, t] = g
    return G


def policy_loss(new, old, ref, buttons, stick, adv, *, eps, w_pg, beta, lam_fwd, lam_rev):
    """Faynt eq. 7: log-space clipped PPO, a behaviour KL to the rollout policy and two KLs to the reference."""
    log_ratio = chosen(new, buttons, stick) - chosen(old, buttons, stick)
    ratio, clipped = log_ratio.exp(), log_ratio.clamp(-eps, eps).exp()
    pg = -torch.minimum(ratio * adv, clipped * adv)
    to_old, to_ref, from_ref = kl(old, new), kl(new, ref), kl(ref, new)
    loss = w_pg * pg + beta * to_old + lam_fwd * to_ref + lam_rev * from_ref
    return loss.mean(), dict(pg=pg.mean(), kl_behaviour=to_old.mean(), kl_ref=to_ref.mean(),
                             kl_ref_rev=from_ref.mean(), clip_frac=(log_ratio.abs() > eps).float().mean(),
                             entropy=entropy(new).mean())
