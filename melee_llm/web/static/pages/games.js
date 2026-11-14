// Every game the machine has played, from all sources, with filters.
import { navigate } from "../app.js";
import { api, fmt, h, link, mount, playerLine, resultText, table } from "../lib.js";

export default async function games(root, { query }) {
  const cat = await api("/api/catalog");
  const f = Object.fromEntries(["q", "source", "mode", "char", "stage", "since", "logs"].map((k) => [k, query.get(k) || ""]));
  let limit = 100;
  const list = h("div");
  const count = h("span.dim");
  const sourceSel = h("select", { onchange: (e) => set("source", e.target.value) }, h("option", { value: "" }, "all sources"));

  function set(k, v) {
    f[k] = v;
    const qs = new URLSearchParams(Object.entries(f).filter(([, v]) => v));
    history.replaceState(null, "", `/games${qs.toString() ? "?" + qs : ""}`);
    limit = 100;
    load();
  }
  const sel = (k, label, opts) => h("label.field", {}, label, h("select", { onchange: (e) => set(k, e.target.value) },
    h("option", { value: "" }, "any"), opts.map(([v, n]) => h("option", { value: v, selected: f[k] === v }, n))));

  mount(root, h("div.pagehead", {}, h("h1", {}, "Games"), count),
    h("div.filters", {},
      h("label.field", {}, "Player", h("input", { type: "search", value: f.q, placeholder: "hal, llm, coach, cpu:9, sonnet…",
        onchange: (e) => set("q", e.target.value) })),
      h("label.field", {}, "Source", sourceSel),
      sel("mode", "Mode", [["lockstep", "lockstep"], ["paused", "paused"], ["fast", "fast"]]),
      sel("char", "Character", cat.characters.map((c) => [c.id, c.name])),
      sel("stage", "Stage", cat.stages.map((s) => [s.id, s.name])),
      h("label.field", {}, "Since", h("input", { type: "date", value: f.since, onchange: (e) => set("since", e.target.value) })),
      h("label.check", {}, h("input", { type: "checkbox", checked: f.logs === "1", onchange: (e) => set("logs", e.target.checked ? "1" : "") }),
        "with LLM/coach logs")),
    h("div.card", {}, list));

  async function load() {
    const qs = new URLSearchParams({ ...Object.fromEntries(Object.entries(f).filter(([, v]) => v)), limit });
    const r = await api(`/api/games?${qs}`);
    count.textContent = `${fmt.num(r.total)} games`;
    if (sourceSel.options.length === 1) {
      for (const s of r.sources) sourceSel.append(h("option", { value: s, selected: f.source === s }, s));
    }
    mount(list, table([
      { label: "When", render: (g) => h("span.dim", {}, g.time) },
      { label: "Source", render: (g) => g.job_id ? link(`/job/${g.job_id}`, g.source_label) : g.source_label },
      { label: "Players", render: (g) => h("span", {}, playerLine(g, 1), h("span.dim", {}, "  vs  "), playerLine(g, 2)) },
      { label: "Stage", render: (g) => g.stage_name },
      { label: "Mode", render: (g) => g.mode || "–" },
      { label: "Result", render: (g) => resultText(g) },
      { label: "Length", cls: "num", render: (g) => fmt.frames(g.frames) },
      { label: "Logs", render: (g) => g.logs.length ? g.logs.map((l) => h("span.badge.ok", {}, l.kind)) : "" },
    ], r.games, { onRow: (g) => navigate(`/game/${g.id}`), rowClass: () => "clickable", empty: "No games match." }),
    r.total > r.games.length ? h("div", { style: { textAlign: "center", marginTop: "12px" } },
      h("button", { onclick: () => { limit += 200; load(); } }, `Show more (${r.total - r.games.length} left)`)) : null);
  }
  load();
}
