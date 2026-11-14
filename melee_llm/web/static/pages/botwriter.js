// Bot-writer: agent sessions (model, cost, time) and ladder boards. /ladder/<name> shows one board in full.
import { navigate } from "../app.js";
import { api, emptyState, fmt, h, heat, link, mount, table } from "../lib.js";

const pct = (v) => heat(v, v === undefined || v === null ? undefined : `${Math.round(v * 100)}`);

const short = (o) => o.replace("agent:melee_llm.bots:", "").replace("baseline:", "");

function board(l, full) {
  if (l.error) return h("div.card", {}, h("h2", {}, l.name), h("div.error-box", {}, l.error));
  const b = l.board;
  const entrants = Object.entries(b.entrants).map(([name, r]) => ({ name, ...r }));
  const opps = [...b.config.roster, ...b.config.hard_tier];
  return h("div.card", {},
    h("h2", {}, full ? "Board" : link(`/ladder/${l.name}`, `Ladder ${l.name}`), h("span.spacer"),
      link(`/games?source=ladder:${l.name}`, h("span", { style: { font: "500 13px var(--sans)", textTransform: "none", letterSpacing: 0 } }, "Games →"))),
    h("div.dim", { style: { fontSize: "13px", margin: "-4px 0 14px" } },
      `${b.games} of ${b.jobs_total} games · ${b.errors} errors · ${b.config.character} on ${b.config.stages.map((s) => s.replace("_", " ").toLowerCase()).join(", ")} · updated ${b.updated_games ?? "–"}`),
    h("h3", {}, "Models"),
    table([
      { label: "Model", render: (m) => h("b", {}, m.name) }, { label: "Runs", cls: "num", key: "runs" },
      { label: "Roster score", cls: "num", render: (m) => `${m.roster_score_mean}${m.runs > 1 ? ` ± ${m.roster_score_sd}` : ""}` },
      { label: "Hard tier", cls: "num", key: "hard_score_mean" }, { label: "Elo", cls: "num", key: "elo_mean" },
      { label: "Best run", cls: "num", key: "best_run_score" },
    ], Object.entries(b.models).map(([name, m]) => ({ name, ...m }))),
    h("h3", { style: { marginTop: "20px" } }, "Entrants", full ? h("span.dim", {}, "  win % vs each opponent") : null),
    table([
      { label: "Entrant", render: (e) => h("span", {}, h("b", {}, e.name), e.flagged ? h("span.badge.bad", { style: { marginLeft: "8px" } }, "flagged") : null) },
      { label: "Score", cls: "num", render: (e) => h("span", { title: `95% CI ${e.roster_score_ci95?.join("–")}` }, e.roster_score) },
      { label: "Hard", cls: "num", render: (e) => e.hard_score ?? "–" },
      { label: "Elo", cls: "num", render: (e) => fmt.num(e.elo) },
      { label: "CPU lvl", cls: "num", key: "cpu_ladder_level" },
      { label: "Games", cls: "num", key: "games" },
      ...(full ? opps.map((o) => ({ label: short(o), cls: "num", render: (e) => pct(e.vs[o]) })) : []),
      { label: "Integrity", render: (e) => h("span.dim", { style: { fontSize: "12.5px" } },
        Object.entries(e.integrity || {}).filter(([k, v]) => v && k !== "frames").map(([k, v]) => `${k} ${v}`).join(", ") || "clean") },
    ], entrants),
    full ? [h("h3", { style: { marginTop: "20px" } }, "Roster Elo ", h("span.dim", {}, `anchor ${b.config.anchor} = 0`)),
      table([{ label: "Opponent", render: (r) => r.o }, { label: "Elo", cls: "num", render: (r) => fmt.num(r.elo) }],
        Object.entries(b.roster_elo).map(([o, elo]) => ({ o: short(o), elo })))] : null);
}

export default async function botwriter(root, { name }) {
  const [sessions, ladders] = await Promise.all([name ? [] : api("/api/botwriter/sessions"), api("/api/ladders")]);
  if (name) {
    const l = ladders.find((x) => x.name === name);
    mount(root, h("div.pagehead", {}, link("/botwriter", h("span.back", {}, "← Bot-writer")), h("h1", { style: { flexBasis: "100%" } }, `Ladder ${name}`)),
      l ? board(l, true) : h("div.card", {}, emptyState("No such ladder", name)));
    return;
  }
  mount(root, h("div.pagehead", {}, h("h1", {}, "Bot-writer"),
    h("div.lede", {}, "Coding agents write a Melee bot under a time budget; the ladder ranks the final bots.")),
  h("div.card", {}, h("h2", {}, "Sessions"), table([
    { label: "Started", cls: "when", render: (s) => s.started_at },
    { label: "Name", render: (s) => link(`/botwriter/${s.id}`, s.name || s.id) },
    { label: "Harness", key: "harness" }, { label: "Model", render: (s) => h("span.mono", {}, s.model) },
    { label: "Budget", cls: "num", render: (s) => `${s.minutes ?? "–"} min${s.budget_usd ? ` · $${s.budget_usd}` : ""}` },
    { label: "Wall time", cls: "num", render: (s) => s.wall_s ? fmt.secs(s.wall_s) : h("span.badge.live", {}, "running") },
    { label: "Cost", cls: "num", render: (s) => fmt.usd(s.cost_usd) },
    { label: "Turns", cls: "num", render: (s) => s.num_turns ?? "–" },
    { label: "Bot", render: (s) => s.bot_lines ? `${s.bot_lines} lines` : "–" },
    { label: "Check", render: (s) => s.valid === true ? h("span.badge.ok", {}, "valid") : s.valid === false ? h("span.badge.bad", {}, "invalid") : "–" },
    { label: "Exit", render: (s) => h("span.dim", {}, s.exit ?? "") },
  ], sessions, { onRow: (s) => navigate(`/botwriter/${s.id}`), rowClass: () => "clickable", empty: "No sessions yet." })),
  h("div.stack", { style: { marginTop: "18px" } }, ladders.map((l) => board(l, false))));
}
