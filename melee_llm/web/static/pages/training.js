// Own-bot training runs (lane B): progress, loss and per-head accuracy, refreshed every 5 s.
import { api, badge, emptyState, every, fmt, h, mount } from "../lib.js";

const HEADS = [["stick", "Main stick", "var(--hi)"], ["buttons", "Buttons", "var(--ok)"],
  ["shoulder", "Shoulder", "var(--warn)"], ["cstick", "C-stick", "var(--p2)"]];
const SVG = "http://www.w3.org/2000/svg";

function svg(tag, attrs = {}, ...children) {
  const el = document.createElementNS(SVG, tag);
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
  el.append(...children.flat().filter(Boolean));
  return el;
}

// series: [{label, color, points: [[x, y]], dots}]
function chart(series, { log = false, yFmt = (v) => v.toFixed(2), xMax } = {}) {
  const W = 560, H = 220, L = 46, R = 10, T = 10, B = 24;
  const all = series.flatMap((s) => s.points).filter(([, y]) => Number.isFinite(y) && (!log || y > 0));
  if (!all.length) return h("div.faint", { style: { padding: "40px 0", textAlign: "center" } }, "No points yet");
  const ty = log ? Math.log10 : (v) => v;
  let lo = Math.min(...all.map(([, y]) => ty(y))), hi = Math.max(...all.map(([, y]) => ty(y)));
  if (hi - lo < 1e-6) { lo -= 0.5; hi += 0.5; }
  const x1 = Math.max(xMax || 0, ...all.map(([x]) => x));
  const sx = (x) => L + (x / x1) * (W - L - R);
  const sy = (y) => T + (1 - (ty(y) - lo) / (hi - lo)) * (H - T - B);
  const grid = [];
  for (let i = 0; i <= 4; i++) {
    const v = log ? 10 ** (lo + (hi - lo) * i / 4) : lo + (hi - lo) * i / 4;
    grid.push(svg("line", { x1: L, x2: W - R, y1: sy(v), y2: sy(v), stroke: "rgba(150,175,255,.12)" }),
      svg("text", { x: L - 6, y: sy(v) + 4, "text-anchor": "end", fill: "#5b6494", "font-size": 11 }, yFmt(v)));
  }
  for (let i = 0; i <= 4; i++) {
    const x = x1 * i / 4;
    grid.push(svg("text", { x: sx(x), y: H - 6, "text-anchor": i === 0 ? "start" : i === 4 ? "end" : "middle", fill: "#5b6494", "font-size": 11 },
      x >= 1000 ? `${+(x / 1000).toFixed(1)}k` : Math.round(x)));
  }
  const lines = series.map((s) => {
    const pts = s.points.filter(([, y]) => Number.isFinite(y) && (!log || y > 0));
    return svg("g", {},
      svg("polyline", { points: pts.map(([x, y]) => `${sx(x).toFixed(1)},${sy(y).toFixed(1)}`).join(" "),
        fill: "none", style: `stroke: ${s.color}`, "stroke-width": 1.8, "stroke-linejoin": "round" }),
      s.dots ? pts.map(([x, y]) => svg("circle", { cx: sx(x), cy: sy(y), r: 2.6, style: `fill: ${s.color}` })) : null);
  });
  return h("div", {},
    svg("svg", { viewBox: `0 0 ${W} ${H}`, width: "100%", style: "display:block" }, grid, lines),
    h("div.row", { style: { gap: "14px", fontSize: "12px", marginTop: "4px" } },
      series.map((s) => h("span.dim", {}, h("span", { style: { color: s.color } }, "■ "), s.label))));
}

const STATE = { running: "live", done: "ok", stopped: "warn" };

function card(r) {
  const last = r.evals.at(-1);
  const pct = r.steps ? Math.min(100, (100 * r.step) / r.steps) : null;
  const a = r.args || {};
  const size = r.params ? `${(r.params / 1e6).toFixed(1)}M params` : r.summary;
  const shape = a.layers ? `${a.layers} layers × ${a.width}, context ${a.context}, batch ${a.batch}` : null;
  return h("div.card", {},
    h("h2", {}, r.name, badge(r.state, STATE[r.state]),
      h("span.dim", {}, [size, shape, a.overfit_game != null ? `overfit on game ${a.overfit_game}` : null].filter(Boolean).join(" · "))),
    h("div.row", { style: { gap: "14px", margin: "6px 0 14px", alignItems: "center" } },
      h("span.mono", {}, `step ${fmt.num(r.step)}${r.steps ? ` / ${fmt.num(r.steps)}` : ""}`),
      pct !== null ? h("div.budget", { style: { flex: "1 1 300px" } }, h("div.bar", { style: { width: `${pct}%` } })) : null,
      r.eta_s ? h("span.dim", {}, `${fmt.secs(r.eta_s)} left`) : null,
      r.frames_per_s ? h("span.dim", {}, `${fmt.k(r.frames_per_s)} frames/s`) : null,
      h("span.faint", {}, `updated ${fmt.ago(r.updated)}`)),
    last ? h("div.stat-row", {},
      h("div.stat", {}, h("b", {}, last.loss.toFixed(3)), h("span", {}, "val loss")),
      HEADS.map(([k, label]) => h("div.stat", {}, h("b", {}, `${(100 * last[`acc_${k}`]).toFixed(1)}%`), h("span", {}, label))))
      : null,
    h("div.grid2", {},
      h("div", {}, h("h3", {}, "Loss ", h("span.dim", {}, "(log scale; training is a running average)")),
        chart([{ label: "train", color: "var(--dim)", points: r.train.map((p) => [p.step, p.loss]) },
          { label: "validation", color: "var(--hi)", dots: true, points: r.evals.map((e) => [e.step, e.loss]) }],
        { log: true, xMax: r.steps })),
      h("div", {}, h("h3", {}, "Validation accuracy ", h("span.dim", {}, "(top guess = what the human pressed next frame)")),
        chart(HEADS.map(([k, label, color]) => ({ label, color, dots: true, points: r.evals.map((e) => [e.step, 100 * e[`acc_${k}`]]) })),
          { yFmt: (v) => `${v.toFixed(0)}%`, xMax: r.steps }))));
}

const POOL_COLORS = { teacher: "var(--warn)", self: "var(--hi)", other: "var(--p2)" };
const HOURS = 60 * 60 * 60;  // frames per hour of game time

// Rolling sums over the last `k` iterations: win rate per pool group and mean of a per-iteration value.
function rolling(points, k, f) {
  const out = [];
  for (let i = 0; i < points.length; i++) {
    const w = points.slice(Math.max(0, i - k + 1), i + 1);
    const y = f(w);
    if (y !== null) out.push([points[i].frames / HOURS, y]);
  }
  return out;
}

function rlCard(r) {
  const a = r.args || {};
  const last = r.train.at(-1) || {};
  const k = 50;
  const pool = r.pool || [];
  const winRate = (g) => (w) => {
    const n = w.reduce((s, p) => s + ((p.played || {})[g] || 0), 0);
    return n ? 100 * w.reduce((s, p) => s + ((p.won || {})[g] || 0), 0) / n : null;
  };
  const mean = (key, scale = 1) => (w) => w.length ? scale * w.reduce((s, p) => s + (p[key] || 0), 0) / w.length : null;
  const recent = r.train.slice(-k);
  const init = (r.init || "").split("/").at(-2) || "?";
  return h("div.card", {},
    h("h2", {}, r.name, badge(r.state, STATE[r.state]),
      h("span.dim", {}, [`self-play RL from ${init}`, `${a.envs} matches at once`, `delay ${a.delay}`,
        `opponents: ${pool.join(", ")}`].join(" · "))),
    h("div.row", { style: { gap: "14px", margin: "6px 0 14px", alignItems: "center" } },
      h("span.mono", {}, `iteration ${fmt.num(r.step)}`),
      h("span.dim", {}, `${((last.frames || 0) / HOURS).toFixed(1)} h of game time`),
      r.frames_per_s ? h("span.dim", {}, `${fmt.k(r.frames_per_s)} frames/s`) : null,
      h("span.faint", {}, `updated ${fmt.ago(r.updated)}`)),
    h("div.stat-row", {},
      pool.map((g) => {
        const v = winRate(g)(recent);
        return h("div.stat", {}, h("b", {}, v === null ? "–" : `${v.toFixed(0)}%`), h("span", {}, `wins vs ${g}`));
      }),
      h("div.stat", {}, h("b", {}, (mean("kl")(recent) ?? 0).toFixed(3)), h("span", {}, "KL to start model")),
      h("div.stat", {}, h("b", {}, (mean("reward_per_min")(recent) ?? 0).toFixed(2)), h("span", {}, "reward / min"))),
    h("div.grid2", {},
      h("div", {}, h("h3", {}, "Win rate ", h("span.dim", {}, `(last ${k} iterations; x: hours of game time)`)),
        chart(pool.map((g) => ({ label: `vs ${g}`, color: POOL_COLORS[g] || "var(--dim)", points: rolling(r.train, k, winRate(g)) })),
          { yFmt: (v) => `${v.toFixed(0)}%` })),
      h("div", {}, h("h3", {}, "Reward and drift ", h("span.dim", {}, "(stocks + damage per minute; KL × 10)")),
        chart([{ label: "reward / min", color: "var(--ok)", points: rolling(r.train, k, mean("reward_per_min")) },
          { label: "KL to start × 10", color: "var(--warn)", points: rolling(r.train, k, mean("kl", 10)) }]))),
    r.replays.length ? h("div", {}, h("h3", {}, "Sample games ", h("span.dim", {}, `(learner on port 1; ${r.n_replays} recorded)`)),
      h("div.row", { style: { gap: "8px", flexWrap: "wrap" } },
        r.replays.map((p) => h("a.chip", { href: `/game/${p.id}` }, p.name)))) : null);
}

export default async function training(root, _params, signal) {
  const list = h("div.stack");
  mount(root, h("div.pagehead", {}, h("h1", {}, "Training"),
    h("div.lede", {}, "Own-bot runs under data/train/runs/: behaviour cloning on replays, then self-play RL in the simulator. "
      + "Validation uses held-out games; accuracy is a sanity check, not strength: strength is measured on the Bench.")),
  list);
  every(5000, async () => {
    const { runs } = await api("/api/training");
    mount(list, runs.length ? runs.map((r) => (r.kind === "rl" ? rlCard(r) : card(r))) : h("div.card", {}, emptyState("No training runs yet", "Start one with python -m meleebot.train.")));
  }, signal);
}
