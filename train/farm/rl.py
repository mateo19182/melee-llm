"""Yoshi RL in the simulator farm, after Faynt's Arena stage (Faynt paper, section 4.4 and appendix E.6).

    cd train && MELEE_WEB_DATA=~/projects/ai/melee-llm/data PYTHONPATH=. \\
        ../vendor/Faynt-Tournament/.venv/bin/python -m farm.rl RUN [--init 10M-Arena] [--pool ...] [--steps N]

The learner plays Yoshi in every lane, starting from Faynt 10M Arena, which is also the reference policy of the KL
leash. Lanes are split over a pool (`--pool NAME:LANES,...`): `self` lanes are Yoshi dittos with the learner on both
sides; any other name is a farm player (`phillip:MODEL/CHARACTER`, `faynt:VARIANT/CHARACTER`) on the other port.
Each RL step plays --frames frames in every lane, then updates the value network once per 128-frame rollout and the
policy with two PPO epochs. Settings default to the paper's 10M "leash" run (Table 2).

Writes data/train/runs/RUN/: run.json, rl.jsonl (one line per step; the web Training page reads both), ckpt/step-N
(a Faynt checkpoint directory, playable as `faynt:/abs/path`), last.pt (to resume), replays/ (sample games as .slp).
Lanes chosen with --publish appear on the web's All matches page while they play.

--check (with a few --steps) only measures: how well the learner reproduces the actor's action probabilities.
"""
import argparse
import collections
import json
import math
import os
import shutil
import time
import types
from pathlib import Path

import numpy as np

from . import common  # noqa: F401  (paths: melee_llm, melee_sim)
from .common import LIVE, Brain, Frame
from .run import DATA, RING, STAGES, TIMER, stage_of

POOL = ("self:32,phillip:fox_d18_vs_yoshi_v3/FOX:8,phillip:marth_d18_vs_yoshi_v3/MARTH:8,"
        "phillip:falco_d18_vs_yoshi/FALCO:4,phillip:sheik_d18_vs_yoshi/SHEIK:4,phillip:peach_d18_vs_yoshi_v3/PEACH:4,"
        "phillip:yoshi_d18_ditto/YOSHI:4")
HIST = 128  # frames before each rollout the value network reads
ROLL = 128  # frames per rollout


def parse_pool(text):
    out = []
    for item in text.split(","):
        name, _, lanes = item.rpartition(":")
        out.append((name, int(lanes)))
    return out


# ---------------------------------------------------------------- reward (Faynt eq. 6, slippi-ai's zero-sum reward)

def _slots(obs):
    return {int(s["source_player"]): s for s in obs["slots"] if s["source_player"] < 2}


def shaped(before, after, edge):
    """u for both source players of one lane over one transition (before -> after rows)."""
    import melee

    a, b = _slots(before), _slots(after)
    u = np.zeros(2)
    for p, q in ((0, 1), (1, 0)):
        pa, pb, qa = a[p], b[p], a[q]
        lost = max(0, int(pa["stocks"]) - int(pb["stocks"]))
        damage = 0.0 if lost else max(0.0, float(pb["percent"]) - float(pa["percent"]))
        x, y, ox = float(pb["pos_x"]), float(pb["pos_y"]), float(qa["pos_x"])
        grab = (int(pb["action_id"]) == melee.Action.EDGE_CATCHING.value
                and int(pa["action_id"]) != melee.Action.EDGE_CATCHING.value
                and not bool(qa["invulnerable"]) and (ox > -edge if x < 0 else ox < edge))
        dx, dy = max(0.0, abs(x) - edge), max(0.0, y - 60.0, -y)
        off = math.hypot(dx, dy) > 50
        to = np.array([float(qa["pos_x"]) - float(pa["pos_x"]), float(qa["pos_y"]) - float(pa["pos_y"])])
        move = np.array([x - float(pa["pos_x"]), y - float(pa["pos_y"])])
        norm = np.linalg.norm(to)
        approach = float(move @ to / norm) if norm > 1e-6 and not lost else 0.0
        u[p] = -lost - 0.01 * damage - 0.02 * grab - 0.1 / 60 * off + 0.001 * approach
    return u


# ---------------------------------------------------------------- the learner's seats

class Seats(Brain):
    """The learning policy on all its seats: one CUDA-graph step a frame, recording what RL needs."""

    def __init__(self, model, seats, seed):
        from .faynt import GraphStep

        super().__init__(seats)
        self.step = GraphStep(model, len(self.seats), 1.0, seed)
        self.paths = [p for p, _ in self.step.inputs]
        self.parsers = [None] * len(self.seats)

    def read(self, states, fresh):
        """Columns of this frame's inputs for every seat, and which seats start a game."""
        from slippi_db.parse_libmelee import Parser

        from .faynt import _column

        reset = np.zeros(len(self.seats), bool)
        games = []
        for i, (lane, port) in enumerate(self.seats):
            if fresh[lane] or self.parsers[i] is None:
                self.parsers[i], reset[i] = Parser(ports=(port, 3 - port)).get_game, True
            games.append(self.parsers[i](states[lane]))
        return {p: _column(games, p) for p in self.paths}, reset

    def act(self, columns, reset):
        from .faynt import press

        self.step.load_columns(columns)
        packed = self.step.step(reset)
        actions = packed.float().cpu().numpy()
        labels, logp = self.step.labels.cpu().numpy(), self.step.logp.cpu().numpy()
        for i, c in enumerate(actions):
            press(self.controllers[i], c)
            self.controllers[i].raw_input(self.rows[i])
            self.controllers[i].flush()
        return self.rows, labels, logp


class Buffers:
    """One RL step of every learner seat, HIST frames of history first and one bootstrap frame last."""

    def __init__(self, frames, seats):
        self.n, self.S = HIST + frames + 1, seats
        self.cols = None
        self.reset = np.zeros((self.n, seats), bool)
        self.valid = np.zeros((self.n, seats), bool)
        self.labels = np.zeros((self.n, seats, 2), np.int64)
        self.logp = np.zeros((self.n, seats), np.float32)
        self.reward = np.zeros((self.n, seats), np.float32)
        self.done = np.zeros((self.n, seats), bool)

    def put(self, i, columns, reset):
        if self.cols is None:
            # frames never played (history before the first step) hold the first frame: masked, but encodable
            self.cols = {p: np.repeat(c[None], self.n, axis=0) for p, c in columns.items()}
        for p, c in columns.items():
            self.cols[p][i] = c
        self.reset[i], self.valid[i] = reset, True

    def roll(self):
        """Keep the last HIST decision frames as the next step's history; the bootstrap frame becomes its first."""
        frames = self.n - HIST - 1
        for a in [*self.cols.values(), self.reset, self.valid, self.labels, self.logp, self.reward, self.done]:
            a[:HIST + 1] = a[frames:frames + HIST + 1].copy()


# ---------------------------------------------------------------- update

class Learner:
    def __init__(self, model, ref, value, args):
        import torch

        self.torch, self.model, self.ref, self.value, self.a = torch, model, ref, value, args
        self.opt_pi = torch.optim.Adam(model.parameters(), lr=args.lr)
        self.opt_v = torch.optim.Adam(value.parameters(), lr=args.lr)
        self.gamma = 2 ** (-1 / (60 * args.half_life))

    def game(self, buf, a, b):
        from .faynt import _leaves

        torch = self.torch
        g = self.model.example_inputs(buf.S, b - a, device="cuda")["game_state_t"]
        for path, t in _leaves(g):
            t.copy_(torch.from_numpy(np.ascontiguousarray(np.swapaxes(buf.cols[path][a:b], 0, 1))).to(t.dtype))
        return g

    def gpu(self, x, a, b):
        return self.torch.from_numpy(np.ascontiguousarray(np.swapaxes(x[a:b], 0, 1))).cuda()

    def values(self, buf, end, grad=False):
        """V for the ROLL frames ending at buffer index `end` (exclusive), reading HIST frames before them."""
        a = end - HIST - ROLL
        g = self.game(buf, a, end)
        with self.torch.set_grad_enabled(grad):
            v = self.value(g, g.p0.controller, self.gpu(buf.reset, a, end), self.gpu(buf.valid, a, end))
        return v[:, HIST:]

    def logits(self, net, buf, snap, r, grad=False):
        from farm import learner as L

        ControllerLabels = L.native(net.policy).ControllerLabels
        a, b = HIST + r * ROLL, HIST + (r + 1) * ROLL
        g = self.game(buf, a, b)
        lab = self.gpu(buf.labels, a, b)
        with self.torch.set_grad_enabled(grad):
            out = L.score(net.policy, g, g.p0.controller, ControllerLabels(lab[..., 0], lab[..., 1]),
                          self.gpu(buf.reset, a, b), snap)
        return L.log_probs(out), lab

    def update(self, buf, snaps, it):
        from farm import learner as L

        torch, a = self.torch, self.a
        n = len(snaps)
        m = collections.defaultdict(float)
        # value and returns
        V = [self.values(buf, HIST + (r + 1) * ROLL).detach() for r in range(n)]
        boot = self.values(buf, buf.n)[:, -1].detach()
        G, A = [], []
        for r in range(n):
            s = slice(HIST + r * ROLL, HIST + (r + 1) * ROLL)
            nxt = V[r + 1][:, 0] if r + 1 < n else boot
            g = L.returns(self.gpu(buf.reward, s.start, s.stop), self.gpu(buf.done, s.start, s.stop), V[r], nxt,
                          self.gamma)
            G.append(g)
            A.append(g - V[r])
        for r in range(n):
            loss = (self.values(buf, HIST + (r + 1) * ROLL, grad=True) - G[r]).pow(2).mean()
            self.opt_v.zero_grad()
            loss.backward()
            self.opt_v.step()
            m["value_loss"] += loss.item() / n
        m["advantage_abs"] = float(torch.cat(A).abs().mean())
        m["return_mean"] = float(torch.cat(G).mean())
        if it < a.value_warmup:
            m["phase"] = "value warm-up"
            return dict(m)
        # behaviour (old) and reference distributions, from the stored actor caches
        old, ref, labs = [], [], []
        for r in range(n):
            snap = snaps[r].to("cuda")
            o, lab = self.logits(self.model, buf, snap, r)
            old.append(o)
            ref.append(self.logits(self.ref, buf, snap, r)[0])
            labs.append(lab)
            s = slice(HIST + r * ROLL, HIST + (r + 1) * ROLL)
            actor = self.gpu(buf.logp, s.start, s.stop)
            mine = L.chosen(o, lab[..., 0], lab[..., 1])
            m["actor_logp_gap"] += float((actor - mine).abs().mean()) / n
            m["kl_ref_now"] += float(L.kl(o, ref[-1]).mean()) / n
        if it < a.value_warmup + a.zero_steps:
            m["phase"] = "zero-lr"
            return dict(m)
        m["phase"] = "ppo"
        start = ({k: v.clone() for k, v in self.model.state_dict().items()}, _copy_opt(self.opt_pi))
        for epoch in range(a.epochs):
            self.opt_pi.zero_grad()
            for r in range(n):
                new, lab = self.logits(self.model, buf, snaps[r].to("cuda"), r, grad=True)
                loss, parts = L.policy_loss(new, old[r], ref[r], lab[..., 0], lab[..., 1], A[r], eps=a.eps,
                                            w_pg=a.w_pg, beta=a.beta, lam_fwd=a.lam_fwd, lam_rev=a.lam_rev)
                (loss / n).backward()
                if epoch == a.epochs - 1:
                    for k, v in parts.items():
                        m[k] += float(v.detach()) / n
            self.opt_pi.step()
        with torch.no_grad():
            moved = sum(float(L.kl(old[r], self.logits(self.model, buf, snaps[r].to("cuda"), r)[0]).mean())
                        for r in range(0, n, 4)) / len(range(0, n, 4))
        m["kl_step"] = moved
        if moved > a.guard:
            self.model.load_state_dict(start[0])
            self.opt_pi.load_state_dict(start[1])
            m["guard"] = 1
        return dict(m)


def _copy_opt(opt):
    import copy

    return copy.deepcopy(opt.state_dict())


# ---------------------------------------------------------------- main loop

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run")
    ap.add_argument("--init", default="10M-Arena", help="starting policy (released variant or checkpoint directory)")
    ap.add_argument("--ref", default="10M-Arena", help="reference policy for the KL leash")
    ap.add_argument("--pool", default=POOL)
    ap.add_argument("--frames", type=int, default=2048, help="frames per lane per RL step (a multiple of 128)")
    ap.add_argument("--steps", type=int, default=1000)
    ap.add_argument("--lr", type=float, default=1e-4)
    ap.add_argument("--w-pg", type=float, default=3.0)
    ap.add_argument("--beta", type=float, default=0.3, help="behaviour KL weight")
    ap.add_argument("--lam-fwd", type=float, default=0.003, help="KL(pi || ref) weight")
    ap.add_argument("--lam-rev", type=float, default=0.003, help="KL(ref || pi) weight")
    ap.add_argument("--eps", type=float, default=0.01, help="log-ratio clip")
    ap.add_argument("--half-life", type=float, default=8.0, help="reward half-life in seconds")
    ap.add_argument("--epochs", type=int, default=2)
    ap.add_argument("--guard", type=float, default=0.005, help="undo a step whose KL(old || new) exceeds this")
    ap.add_argument("--value-warmup", type=int, default=20, help="value-only steps first")
    ap.add_argument("--zero-steps", type=int, default=3, help="then steps that only measure")
    ap.add_argument("--save-every", type=int, default=25)
    ap.add_argument("--replay-minutes", type=float, default=20, help="record one game per pool group this often")
    ap.add_argument("--publish", type=int, default=1, help="lanes per pool group shown on the All matches page")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    assert a.frames % ROLL == 0
    if a.check:
        a.value_warmup, a.zero_steps = 0, 10**9

    import melee
    import melee_sim as msl
    import torch
    from transformers import AutoModel

    from melee_llm.sim.slippi import Encoder
    from melee_llm.sim.state import SIM_STAGE

    from . import learner as L
    from .faynt import weights
    from .remote import RemoteBrain

    torch.manual_seed(a.seed)
    run = LIVE / "data/train/runs" / a.run
    (run / "ckpt").mkdir(parents=True, exist_ok=True)
    (run / "replays").mkdir(exist_ok=True)
    pool = parse_pool(a.pool)
    lanes = sum(n for _, n in pool)
    group = [g for g, (_, n) in enumerate(pool) for _ in range(n)]
    names = [name.split("/")[0].split(":")[-1] if name != "self" else "self" for name, _ in pool]
    opp_char = [name.partition("/")[2] or "YOSHI" if name != "self" else "YOSHI" for name, _ in pool]
    me_port = [1 + lane % 2 for lane in range(lanes)]
    seats, opp = [], collections.defaultdict(list)
    for lane in range(lanes):
        name = pool[group[lane]][0]
        if name == "self":
            seats += [(lane, 1), (lane, 2)]
        else:
            seats.append((lane, me_port[lane]))
            opp[name.partition("/")[0]].append((lane, 3 - me_port[lane]))

    model = AutoModel.from_pretrained(weights(a.init), trust_remote_code=True).eval().cuda()
    ref = AutoModel.from_pretrained(weights(a.ref), trust_remote_code=True).eval().cuda().requires_grad_(False)
    value = L.Value(model).cuda()
    learner = Learner(model, ref, value, a)
    it, frames_total = 0, 0
    if (run / "last.pt").exists():
        state = torch.load(run / "last.pt", map_location="cuda", weights_only=False)
        model.load_state_dict(state["model"])
        value.load_state_dict(state["value"])
        learner.opt_pi.load_state_dict(state["opt_pi"])
        learner.opt_v.load_state_dict(state["opt_v"])
        it, frames_total = state["it"], state["frames"]
        print(f"resumed at step {it}", flush=True)
    me = Seats(model, seats, a.seed + it)
    others = {spec: RemoteBrain(spec.partition(":")[0], spec, s, a.seed + it) for spec, s in opp.items()}
    S = len(seats)
    lane_seats = collections.defaultdict(list)
    for i, (lane, port) in enumerate(seats):
        lane_seats[lane].append((i, port))
    if not (run / "run.json").exists() or it == 0:
        (run / "run.json").write_text(json.dumps(dict(
            kind="rl", algo="faynt-ppo", args=vars(a), init=weights(a.init) + "/model.safetensors",
            pool=names, lanes={n: k for n, (_, k) in zip(names, pool)}, seats=S, envs=lanes, delay=0,
            replays=str(run / "replays"), params=sum(p.numel() for p in model.parameters()),
            started_at=time.time()), indent=1))

    env = msl.EnvBatch(batch_size=lanes, length=RING, action_format="raw", data_dir=str(DATA),
                       ucf_cardinals_1_0_enabled=True)
    game_no = [it * lanes + lane for lane in range(lanes)]
    next_game = it * lanes + lanes
    rng = np.random.default_rng(a.seed + it)

    def configure(lane):
        chars = ["YOSHI", opp_char[group[lane]]]
        if me_port[lane] == 2:
            chars.reverse()
        stage = melee.Stage[stage_of(game_no[lane] + int(rng.integers(6)) * 2, STAGES)]
        env.configure_matches([msl.MatchConfig(
            stage=SIM_STAGE[stage], seed=(a.seed + game_no[lane]) % 2**32, max_frame=TIMER,
            ucf_cardinals_1_0_enabled=True,
            players=tuple(msl.PlayerConfig(melee.Character[c].value, controller_port=i) for i, c in enumerate(chars)))],
            env_ids=[lane])
        return stage

    stage = [configure(lane) for lane in range(lanes)]
    env.reset_all()
    edge = {s: melee.stages.EDGE_POSITION[s] for s in set(stage) | {melee.Stage[x] for x in STAGES}}
    inputs = np.zeros(lanes, dtype=env.raw_action_view.dtype)
    has_input, fresh, active = np.zeros(lanes, bool), np.ones(lanes, bool), np.ones(lanes, bool)
    buf = Buffers(a.frames, S)

    # watching: live lanes on the All matches page, sample .slp games
    from melee_llm.matches import MatchPublisher

    def agent(name, char):
        return types.SimpleNamespace(name=name, character=melee.Character[char], cpu_level=0)

    pubs = {}
    for g, (name, _) in enumerate(pool):
        for lane in [x for x in range(lanes) if group[x] == g][:a.publish]:
            ag = {me_port[lane]: agent(f"learner step {it}", "YOSHI"),
                  3 - me_port[lane]: agent("learner" if name == "self" else names[g], opp_char[g])}
            pubs[lane] = MatchPublisher(ag, stage[lane], "sim", 10**6, 60000 + lane, None,
                                        meta=dict(source="training", label=f"RL {a.run}: Yoshi vs {names[g]}"))
    pub_game = collections.Counter()
    record, last_arm = {}, 0.0  # lane -> (name, encoder, chunks)

    def finish_publish(lane, ob):
        sl = _slots(ob)
        ports = {1: 0, 2: 1}
        st = {p: int(sl[ports[p]]["stocks"]) for p in (1, 2)}
        pc = {p: float(sl[ports[p]]["percent"]) for p in (1, 2)}
        win = 1 if (st[1], -pc[1]) > (st[2], -pc[2]) else 2 if (st[2], -pc[2]) > (st[1], -pc[1]) else None
        pubs[lane].game_end(pub_game[lane], types.SimpleNamespace(
            winner=win, stocks=st, percent=pc, frames=int(ob["frame_id"]) + 123,
            seconds=(int(ob["frame_id"]) + 123) / 60, replay=None))

    stats = collections.defaultdict(lambda: collections.defaultdict(float))
    log = open(run / "rl.jsonl", "a")
    pending = None  # (columns, reset, states) of the bootstrap frame, the next step's first frame
    first = True
    try:
        while it < a.steps:
            t0 = time.monotonic()
            snaps = []
            ep = collections.defaultdict(float)  # reward sums per group
            for k in range(a.frames + 1):
                if env.t >= env.length:
                    env.reset_cursor()
                obs = env.current_frame
                if pending is not None and k == 0:
                    columns, reset, states = pending
                else:
                    frame = Frame(obs, inputs, has_input, fresh, active)
                    states = me.states(frame)
                    columns, reset = me.read(states, fresh)
                    if first:
                        reset[:] = True
                        first = False
                buf.put(HIST + k, columns, reset)
                if k == a.frames:
                    pending = (columns, reset, states)
                    break
                for lane, p in pubs.items():
                    if fresh[lane]:
                        pub_game[lane] += 1
                        pubs[lane].status["stage"] = stage[lane].name
                        pubs[lane].status["players"][str(me_port[lane])]["name"] = f"learner step {it}"
                        pubs[lane].game_start(pub_game[lane], states[lane], None)
                    else:
                        p.frame(states[lane])
                if k % ROLL == 0:
                    snaps.append(L.Snapshot.take(me.step.cache).to("cpu"))
                frame = Frame(obs, inputs, has_input, fresh, active)
                for br in others.values():
                    br.submit(frame)
                before = obs.copy()
                raw = env.raw_action_view[env.t]
                rows, labels, logp = me.act(columns, reset)
                for (lane, port), r in zip(seats, rows):
                    raw[lane]["players"][port - 1] = r
                for spec, br in others.items():
                    for (lane, port), r in zip(opp[spec], br.collect()):
                        raw[lane]["players"][port - 1] = r
                buf.labels[HIST + k], buf.logp[HIST + k] = labels, logp
                t = env.t
                env.step(active.astype(np.uint8))
                np.copyto(inputs, raw)
                has_input[:] = True
                fresh[:] = False
                after = env.current_frame
                for lane in record:
                    record[lane][2].append(record[lane][1].frame(after[lane], inputs[lane]))
                done = env.terminal_view[t]["done"].astype(bool)
                for lane in range(lanes):
                    u = shaped(before[lane], after[lane], edge[stage[lane]])
                    for i, port in lane_seats[lane]:
                        R = u[port - 1] - u[2 - port]
                        buf.reward[HIST + k, i] = R
                        buf.done[HIST + k, i] = done[lane]
                        ep[group[lane]] += R
                frames_total += lanes
                if not done.any():
                    continue
                restart = []
                for lane in np.flatnonzero(done):
                    ob = after[lane]
                    sl = _slots(ob)
                    mine, theirs = me_port[lane] - 1, 2 - me_port[lane]
                    margin = int(sl[mine]["stocks"]) - int(sl[theirs]["stocks"])
                    lead = margin or (float(sl[theirs]["percent"]) - float(sl[mine]["percent"]))
                    st = stats[group[lane]]
                    st["played"] += 1
                    st["won"] += 0.5 if lead == 0 else float(lead > 0)
                    st["margin"] += margin
                    if lane in pubs:
                        finish_publish(lane, ob)
                    if lane in record:
                        name, enc, chunks = record.pop(lane)
                        chunks.append(enc.game_end())
                        from meleebot.rl.replays import write_slp
                        write_slp(run / "replays" / f"{time.strftime('%Y%m%dT%H%M%S')}-{name}.slp", b"".join(chunks),
                                  int(ob["frame_id"]))
                    game_no[lane], next_game = next_game, next_game + 1
                    stage[lane] = configure(lane)
                    restart.append(lane)
                env.reset_matches(restart)
                fresh[restart], has_input[restart] = True, False
                if time.monotonic() - last_arm > a.replay_minutes * 60:
                    last_arm = time.monotonic()
                    # record the next game of each group's first restarting lane
                    for g in range(len(pool)):
                        cand = [x for x in restart if group[x] == g and x not in record]
                        if cand:
                            x = cand[0]
                            enc = Encoder(stage[x], [1, 2])
                            nm = f"step{it:05d}-yoshi-vs-{names[g]}"
                            record[x] = (nm, enc, [enc.frame(env.current_frame[x], None)])
            collect_s = time.monotonic() - t0
            t1 = time.monotonic()
            m = learner.update(buf, snaps, it)
            update_s = time.monotonic() - t1
            buf.roll()
            it += 1
            seat_frames = a.frames * S
            line = dict(iter=it, frames=frames_total, fps=round(a.frames * lanes / collect_s),
                        collect_s=round(collect_s, 1), update_s=round(update_s, 1), time=time.time(),
                        reward_per_min=float(sum(ep.values()) / (seat_frames / 3600)),
                        kl=m.get("kl_ref", m.get("kl_ref_now", 0.0)),
                        played={names[g]: int(s["played"]) for g, s in stats.items()},
                        won={names[g]: float(s["won"]) for g, s in stats.items()},
                        margin={names[g]: float(s["margin"]) for g, s in stats.items()},
                        **{k: (round(v, 6) if isinstance(v, float) else v) for k, v in m.items()})
            stats.clear()
            print(json.dumps(line), flush=True)
            log.write(json.dumps(line) + "\n")
            log.flush()
            if a.check:
                print(f"actor vs learner: mean |log p difference| {m.get('actor_logp_gap', float('nan')):.2e}")
                continue
            if it % a.save_every == 0 or it == a.steps:
                save(run, it, frames_total, model, value, learner, a.init)
    finally:
        for br in others.values():
            br.close()
        for p in pubs.values():
            p.close()
        env.close()
        log.close()


def save(run, it, frames, model, value, learner, init):
    import torch

    from .faynt import weights

    d = run / "ckpt" / f"step-{it:05d}"
    model.save_pretrained(d)
    for f in Path(weights(init)).glob("*.py"):
        shutil.copy2(f, d / f.name)
    tmp = run / "last.pt.tmp"
    torch.save(dict(model=model.state_dict(), value=value.state_dict(), opt_pi=learner.opt_pi.state_dict(),
                    opt_v=learner.opt_v.state_dict(), it=it, frames=frames), tmp)
    os.replace(tmp, run / "last.pt")


if __name__ == "__main__":
    main()
