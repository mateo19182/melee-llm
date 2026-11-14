// Coach pilot summaries: per run directory, one row per (condition, opponent).
import { api, emptyState, fmt, h, link, mount, table } from "../lib.js";

export default async function coach(root) {
  const pilots = await api("/api/coach");
  mount(root, h("div.pagehead", {}, h("h1", {}, "Coach pilots"),
    h("div.lede", {}, "scripts/coach_pilot.py runs under replays/coach-pilot/. Stock and percent differences are P1 (the coached side) minus the opponent.")),
  pilots.length ? null : h("div.card", {}, emptyState("No pilot runs yet", "Run scripts/coach_pilot.py to fill this page.")),
  h("div.stack", {}, pilots.map((p) => h("div.card", {},
    h("h2", {}, p.name, h("span.dim", {}, `${p.games} games · ${p.updated}`), h("span.spacer"),
      link(`/games?source=coach-pilot:${p.name}`, h("span", { style: { font: "500 13px var(--sans)", textTransform: "none", letterSpacing: 0 } }, "Games →"))),
    table([
      { label: "Condition", render: (c) => h("span", {}, h("b", {}, c.label), h("div.faint.mono", { style: { fontSize: "11px" } }, c.cond)) },
      { label: "vs", render: (c) => c.opp },
      { label: "n", cls: "num", key: "n" },
      { label: "W–L", cls: "num", render: (c) => `${c.wins}–${c.losses}` },
      { label: "Stock diff", cls: "num", render: (c) => c.stock_diff === null ? "–" : (c.stock_diff > 0 ? "+" : "") + c.stock_diff.toFixed(2) },
      { label: "% diff", cls: "num", render: (c) => c.pct_diff === null ? "–" : (c.pct_diff > 0 ? "+" : "") + Math.round(c.pct_diff) },
      { label: "Mean dist.", cls: "num", render: (c) => fmt.num(c.mean_dx, 1) },
      { label: "Laser", cls: "num", render: (c) => fmt.num(c.laser, 3) },
      { label: "Length", cls: "num", render: (c) => fmt.frames(c.frames) },
      { label: "Coach", render: (c) => c.coach ? h("span.dim", { style: { fontSize: "12.5px" } },
        `${c.coach.decisions} calls, ${c.coach.changes} changes, ${c.coach.errors} err, ${c.coach.mean_latency_s ?? "–"} s, `
        + `${fmt.k(c.coach.prompt_tokens)}/${fmt.k(c.coach.completion_tokens)} tok`) : "–" },
      { label: "Games", render: (c) => h("span", {}, c.games.filter(Boolean).map((id, i) => [link(`/game/${id}`, `${i + 1}`), " "])) },
    ], p.conditions)))));
}
