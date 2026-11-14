// Melee Bench: one rating scale per track for every kind of player, anchored to CPU 9 = 1500.
import { navigate } from "../app.js";
import { api, badge, details, every, fmt, h, heat, link, mount, table } from "../lib.js";

const CAT_KIND = { cpu: "", learned: "p2", scripted: "", written: "warn", llm: "hi", jev: "ok", coach: "p1", human: "live" };
const state = { track: "realtime", cats: new Set() };

const enc = (id) => id.split("/").map(encodeURIComponent).join("/");
const catBadge = (e) => badge(e.category_label, CAT_KIND[e.category]);

function ciBar(r, lo, hi) {
  const x = (v) => `${Math.max(0, Math.min(100, ((v - lo) / (hi - lo)) * 100))}%`;
  const a = r.elo_lo ?? r.elo - r.half_width, b = r.elo_hi ?? r.elo + r.half_width;
  const L = Math.min(a, r.elo - r.half_width), R = Math.max(b, r.elo + r.half_width);
  return h("div.ci", { title: `95% CI ${Math.round(L)}–${Math.round(R)}` },
    h("div.ci-range", { class: r.converged ? "ok" : "", style: { left: x(L), width: `calc(${x(R)} - ${x(L)})` } }),
    h("div.ci-dot", { style: { left: x(r.elo) } }));
}

function cost(sp) {
  if (!sp || !sp.games) return h("span.faint", {}, "free");
  const parts = [];
  if (sp.tokens_per_game) parts.push(`${fmt.k(sp.tokens_per_game)} tok`);
  if (sp.usd_per_game) parts.push(fmt.usd(sp.usd_per_game));
  if (sp.discarded_rate >= 0.05) parts.push(`${Math.round(100 * sp.discarded_rate)}% discarded`);
  return parts.length ? parts.join(" · ") : h("span.faint", {}, "free");
}

function spendLine(st) {
  const sp = st.spent_recounted || st.spent;
  if (!sp) return null;
  const prov = Object.entries(sp.by_provider || {}).map(([k, v]) => `${k} ${fmt.k(v)}`).join(", ");
  const jev = sp.usd_est?.jev ? ` + Jev ${fmt.usd(sp.usd_est.jev)}` : "";
  return `${fmt.k(sp.tokens ?? 0)} LLM tokens${prov ? ` (${prov})` : ""}${jev}`;
}

function outcome(st) {
  const r = st.stop_reason || "";
  if (r.startsWith("token budget reached") || r.startsWith("token cap reached"))
    return `Stopped at its ${fmt.k(st.budget_tokens)}-token cap. The bench now has no cap: it plays while games still narrow a rating.`;
  return r ? r[0].toUpperCase() + r.slice(1) + "." : "";
}

function progress(st, s) {
  const running = st.phase === "running";
  const phase = { running: "live", done: "ok", stopped: "muted", stale: "bad" }[st.phase] || "";
  const unconv = Object.values(st.unconverged || {}).flat();
  const settled = Object.values(st.settled || {}).flat();
  const list = (xs) => `${xs.slice(0, 8).join(", ")}${xs.length > 8 ? "…" : ""}`;
  return h("div.card.bench-progress", {},
    h("div.row", {}, badge(st.phase === "done" ? "finished" : st.phase || "not started", phase),
      h("span", { title: `${s.games.bench} played by the bench, ${s.games.imported} from earlier runs under the same rules` },
        `${(s.games.bench + s.games.imported).toLocaleString()} games`),
      h("span.dim", {}, spendLine(st)),
      running && st.running?.length ? h("span.dim", {}, `${st.running.length} playing now`) : null,
      h("span.spacer"),
      st.updated ? h("span.faint", {}, `${running ? "updated" : "finished"} ${fmt.ago(st.updated)}`) : null),
    running && st.budget_tokens ? h("div.budget", { style: { marginTop: "8px" } },
      h("div.bar", { style: { width: `${Math.min(100, (100 * (st.spent?.tokens ?? 0)) / st.budget_tokens)}%` } })) : null,
    h("div.small-meta", { style: { marginTop: "8px" } },
      running
        ? (unconv.length ? `Still narrowing (wider than ±${st.target}): ${list(unconv)}` : "Every rating is settled")
        : outcome(st),
      settled.length ? h("span.faint", {}, ` · more games would barely move: ${list(settled)}`) : null,
      running && st.waiting ? h("span.faint", {}, ` · waiting: ${st.waiting}`) : null));
}

function explainer() {
  return details("How the bench works",
    h("div.prose.bench-explain", {},
      h("p", {}, "Every player, CPU, learned bot, scripted or LLM-written bot, LLM, Jev or coach, plays the same standard game: ",
        h("b", {}, "Fox vs Fox, Battlefield or Final Destination, 4 stocks, 8 minutes"), ". Results go into one Bradley-Terry fit per track, on the Elo scale, with ",
        h("b", {}, "CPU 9 pinned at 1500"), ". 400 points apart means the higher one wins about 10 games in 11."),
      h("p", {}, h("b", {}, "Real time"), ": the game runs at 60 fps and does not wait. Live LLMs, Jev live and coaches decide on a background thread, so slow thinking costs game time. ",
        h("b", {}, "Untimed"), ": the game waits for every decision; it measures decision quality only. CPUs and bots behave the same in both, so their games count on both boards and tie the two scales together."),
      h("p", {}, "The scheduler picks the next game by ", h("b", {}, "expected information per token"), ": pairings with close ratings and wide intervals first, cheap players often, expensive LLMs only where they still need games. It stops when every interval is within the target or the token budget is spent."),
      h("p", {}, "Bars show the 95% interval (bootstrap, or the Laplace estimate if wider); cyan once within the target. Imported games are older full games under the same rules (bot-writer ladders, coach and Jev pilots). ",
        link("/docs/bench", "Full write-up →"))));
}

export default async function bench(root, p, signal) {
  if (p.id) return entrant(root, decodeURIComponent(p.id), signal);
  const box = h("div.stack");
  mount(root, box);
  let last = null;
  const render = () => {
    const { standings: s, status: st, categories } = last;
    const ents = s.entrants;
    const tr = s.tracks[state.track];
    const rows = tr.players.filter((r) => !state.cats.size || state.cats.has(ents[r.id]?.category));
    const rankOf = new Map(tr.players.map((r, i) => [r.id, i + 1]));
    const all = tr.players.flatMap((r) => [r.elo_lo ?? r.elo, r.elo_hi ?? r.elo, r.elo - r.half_width, r.elo + r.half_width]);
    const lo = Math.min(...all, 1000) - 20, hi = Math.max(...all, 2000) + 20;
    const present = new Set(tr.players.map((r) => ents[r.id]?.category));
    const running = new Set((st.running || []).flatMap((g) => [g.p1, g.p2]));
    const trackBtn = (t, label) => h("button", { class: state.track === t ? "on" : "", onclick: () => { state.track = t; render(); } }, label);
    const chip = (c) => h("button", { class: state.cats.has(c) ? "on" : "", onclick: () => { state.cats.has(c) ? state.cats.delete(c) : state.cats.add(c); render(); } }, categories[c]);
    mount(box,
      h("div.pagehead", {}, h("h1", {}, "Melee Bench"),
        h("span.dim", {}, "Fox ditto · Battlefield + Final Destination · full games · CPU 9 = 1500"),
        h("p.lede", {}, "One leaderboard for every kind of player: CPUs, learned bots, scripted and LLM-written bots, LLMs, Jev and LLM coaches of Reyn.")),
      progress(st, s),
      h("div.row.bench-filters", {},
        h("div.toggle", {}, trackBtn("realtime", "Real time"), trackBtn("untimed", "Untimed")),
        h("div.toggle", {}, Object.keys(categories).filter((c) => present.has(c)).map(chip)),
        h("span.spacer"), h("span.dim", {}, `${tr.games} games on this board`)),
      h("div.card", {}, table([
        { label: "", cls: "rank-cell", render: (r) => { const i = rankOf.get(r.id); return h(`span.rank${i === 1 ? ".first" : ""}`, {}, i); } },
        { label: "Entrant", render: (r) => { const e = ents[r.id] || { label: r.id, category: "?" };
          return h("div.bench-who", {}, h("div", {}, link(`/bench/${enc(r.id)}`, h("span.name", {}, e.label)), " ", catBadge(e),
            running.has(r.id) ? badge("playing", "live") : null, r.id === s.anchor.player ? badge("anchor", "hi") : null),
          h("div.bench-about", {}, e.about)); } },
        { label: "Elo", cls: "num", render: (r) => h("span.elo", {}, r.elo) },
        { label: "95% CI", cls: "ci-cell", render: (r) => ciBar(r, lo, hi) },
        { label: "±", cls: "num", render: (r) => h("span", { class: r.converged ? "" : "dim" }, r.id === s.anchor.player ? "–" : Math.round(r.half_width)) },
        { label: "W–L–D", cls: "num", render: (r) => h("span.dim", {}, `${r.wins}–${r.losses}–${r.draws}`) },
        { label: "Games", cls: "num", render: (r) => h("span", { title: `${r.imported_games} imported` }, r.games, r.imported_games ? h("span.faint", {}, ` (${r.imported_games} imp.)`) : null) },
        { label: "Cost / game", cls: "num", render: (r) => cost(s.spend?.[r.id]) },
      ], rows, { cls: "board bench-board", onRow: (r) => navigate(`/bench/${enc(r.id)}`), rowClass: () => "clickable", empty: "No rated games on this board yet." })),
      st.running?.length ? h("div.card", {}, h("h2", {}, "Playing now ", link("/matches", h("span.dim", {}, "watch on All matches →"))),
        table([
          { label: "Started", cls: "when", render: (g) => fmt.ago(g.started) },
          { label: "P1", render: (g) => ents[g.p1]?.label || g.p1 },
          { label: "P2", render: (g) => ents[g.p2]?.label || g.p2 },
          { label: "Stage", render: (g) => g.stage.replace("_", " ").toLowerCase() },
          { label: "Track", render: (g) => g.track },
          { label: "Est. tokens", cls: "num", render: (g) => (g.est_tokens ? fmt.k(g.est_tokens) : "–") },
        ], st.running)) : null,
      explainer(),
      st.events?.length ? details("Scheduler log", h("pre.prompt-box", {}, st.events.join("\n"))) : null,
      s.games.excluded && Object.keys(s.games.excluded).length ? details("Older games not imported",
        h("pre.prompt-box", {}, Object.entries(s.games.excluded).map(([k, v]) => `${String(v).padStart(4)}  ${k}`).join("\n"))) : null);
  };
  every(20000, async () => { last = await api("/api/bench"); if (!signal.aborted) render(); }, signal);
}

async function entrant(root, id, signal) {
  const d = await api(`/api/bench/entrant/${enc(id)}`);
  if (signal.aborted) return;
  const e = d.entrant, sp = d.spend;
  const trackCard = (t, r) => r ? h("div.stat", {}, h("b", {}, r.elo, h("span.faint", { style: { fontSize: "15px" } }, ` ±${Math.round(r.half_width)}`)),
    h("span", {}, `${t === "realtime" ? "real time" : "untimed"} · ${r.wins}–${r.losses}–${r.draws}`)) : null;
  const opp = (r) => Object.entries(r?.opponents || {}).map(([o, c]) => ({ o, ...c, n: c.w + c.l + c.d }))
    .sort((a, b) => b.n - a.n);
  const rows = [...new Map([...opp(d.tracks.realtime), ...opp(d.tracks.untimed)].map((x) => [x.o, x])).values()];
  mount(root, h("div.stack", {},
    link("/bench", h("span.back", {}, "← Bench")),
    h("div.pagehead", {}, h("h1", {}, e.label), catBadge(e), badge(e.track_label), e.wall_clock ? badge("wall clock") : null,
      h("p.lede", {}, e.about, h("span.faint.mono", {}, `  ${e.spec || e.id}`))),
    h("div.card", {}, h("div.stat-row", {},
      trackCard("realtime", d.tracks.realtime), trackCard("untimed", d.tracks.untimed),
      h("div.stat", {}, h("b", {}, d.total_games), h("span", {}, "games incl. imported")),
      sp ? h("div.stat", {}, h("b", {}, sp.tokens_per_game ? fmt.k(sp.tokens_per_game) : "0"), h("span", {}, "tokens / game")) : null,
      sp?.usd ? h("div.stat", {}, h("b", {}, fmt.usd(sp.usd_per_game)), h("span", {}, "est. $ / game")) : null,
      sp?.mean_latency_s ? h("div.stat", {}, h("b", {}, `${sp.mean_latency_s}s`), h("span", {}, "mean decision latency")) : null,
      sp?.discarded_rate ? h("div.stat", { title: `${sp.dropped} of ${sp.decisions + sp.dropped} replies arrived too late or were superseded; their tokens still count` },
        h("b", {}, `${Math.round(100 * sp.discarded_rate)}%`), h("span", {}, "replies discarded")) : null,
      sp ? h("div.stat", {}, h("b", {}, fmt.k(sp.tokens)), h("span", {}, "tokens spent on the bench")) : null)),
    h("div.grid2", {},
      h("div.card", {}, h("h2", {}, "Record vs opponents"), table([
        { label: "Opponent", render: (x) => link(`/bench/${enc(x.o)}`, d.labels[x.o] || x.o) },
        { label: "W–L–D", cls: "num", render: (x) => `${x.w}–${x.l}–${x.d}` },
        { label: "Score", cls: "num", render: (x) => heat((x.w + x.d / 2) / x.n) },
      ], rows, { empty: "No rated games yet." })),
      h("div.card", {}, h("h2", {}, "Sample decisions ", d.sample_game ? h("span.dim", {}, `vs ${d.sample_game.opponent}`) : null,
        d.sample_game?.game_id ? link(`/game/${d.sample_game.game_id}`, h("span.dim", {}, "replay →")) : null),
        d.samples.length ? h("div.bench-samples", {}, d.samples.map((x) => h("div.ev.open", {},
          h("div.ev-head", {}, h("span.ev-call", {}, `f${x.frame}`), h("span.ev-action", {}, x.action || "–"),
            x.phrase ? h("span.dim", {}, `"${x.phrase}"`) : null,
            h("span.ev-meta", {}, x.latency_s ? `${Number(x.latency_s).toFixed(2)}s` : "", x.latency_frames ? ` · ${x.latency_frames}f` : "")),
          x.reason ? h("div.ev-reason", {}, x.reason) : null,
          x.error ? h("div.error", {}, x.error) : null,
          details("state the model saw", h("pre", {}, x.state)))))
          : h("div.empty-state", {}, e.provider === "none" ? "No decisions to show: this player has no model." : "No bench games with a decision log yet."))),
    h("div.card", {}, h("h2", {}, "Recent games"), table([
      { label: "When", cls: "when", render: (g) => fmt.time(g.ts) },
      { label: "Opponent", render: (g) => link(`/bench/${enc(g.opponent)}`, g.opponent_label) },
      { label: "Port", render: (g) => h(`span.port.p${g.port}`, {}, `P${g.port}`) },
      { label: "Stage", render: (g) => (g.stage || "").replace("_", " ").toLowerCase() },
      { label: "Result", render: (g) => g.result ? h("span", { class: g.result === "win" ? "win" : "dim" }, g.result) : badge(g.status, "bad") },
      { label: "Stocks", cls: "num", render: (g) => g.stocks ? `${Math.round(g.stocks[String(g.port)] ?? 0)}–${Math.round(g.stocks[String(3 - g.port)] ?? 0)}` : "–" },
      { label: "Length", cls: "num", render: (g) => fmt.frames(g.frames) },
      { label: "FPS", cls: "num", render: (g) => g.fps ?? "–" },
      { label: "Tokens", cls: "num", render: (g) => (g.tokens ? fmt.k(g.tokens) : "–") },
      { label: "Source", render: (g) => g.imported ? badge(g.source.split("/")[0], "muted") : badge(g.mode || "bench") },
      { label: "", cls: "num", render: (g) => g.game_id ? link(`/game/${g.game_id}`, "Replay") : "" },
    ], d.games, { empty: "No games yet." }))));
}
