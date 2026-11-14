// Arena: Elo standings, head-to-head scores and recent games.
import { navigate } from "../app.js";
import { api, every, fmt, h, heat, link, mount, resultText, table, toast } from "../lib.js";

export default async function arena(root, _p, signal) {
  const box = h("div.stack");
  mount(root, box);
  every(15000, async () => {
    const [a, s] = await Promise.all([api("/api/arena"), api("/api/settings")]);
    const maxElo = Math.max(...a.table.map((r) => r.elo), 1600), minElo = Math.min(...a.table.map((r) => r.elo), 1400);
    const specs = a.table.map((r) => r.spec);
    const toggle = h("label.check", {}, h("input", { type: "checkbox", checked: s.arena, onchange: async (e) => {
      await api("/api/settings", { method: "POST", body: { arena: e.target.checked } });
      toast(e.target.checked ? "Arena on" : "Arena paused after the current game");
    } }), "Arena fills the live slot when the queue is empty");
    const winPct = (r) => (100 * (r.wins + r.draws / 2)) / Math.max(1, r.wins + r.losses + r.draws);
    const who = (r, p) => h("span", { class: r.winner === p ? "win" : "" }, r[`label${p}`], h("span.dim", {}, ` ${r[`char${p}_name`]}`));
    mount(box,
      h("div.pagehead", {}, h("h1", {}, "Arena"), h("span.dim", {}, `${a.games} games · updated ${a.updated.replace("T", " ")}`), h("span.spacer"), toggle),
      h("div.grid2", { style: { gridTemplateColumns: "minmax(0, 1fr) minmax(0, 1.15fr)" } },
        h("div.card", {}, h("h2", {}, "Standings"), table([
          { label: "", render: (r) => { const i = a.table.indexOf(r) + 1; return h(`span.rank${i === 1 ? ".first" : ""}`, {}, i); }, cls: "rank-cell" },
          { label: "Bot", render: (r) => h("span.name", {}, r.entrant) },
          { label: "Elo", cls: "num", render: (r) => h("span.elo", {}, r.elo) },
          { label: "", cls: "bar-cell", render: (r) => h("div.bar", { style: { width: `${8 + ((r.elo - minElo) / (maxElo - minElo || 1)) * 92}%` } }) },
          { label: "W–L–D", cls: "num", render: (r) => h("span.dim", {}, `${r.wins}–${r.losses}–${r.draws}`) },
          { label: "Win", cls: "num", render: (r) => fmt.pct(winPct(r)) },
        ], a.table, { cls: "board", empty: "No arena games yet." })),
        h("div.card", {}, h("h2", {}, "Head to head ", h("span.dim", {}, "row's score vs column")),
          table([{ label: "", render: (r) => h("b", {}, r.entrant) },
            ...a.table.map((c) => ({ label: c.entrant, cls: "num", render: (r) => {
              const cell = a.h2h[`${r.spec}|${c.spec}`];
              if (r.spec === c.spec || !cell) return h("span.faint", {}, "·");
              const el = heat(cell.score / cell.n);
              el.title = `${cell.score}/${cell.n}`;
              return el;
            } }))], a.table.filter((r) => specs.includes(r.spec))))),
      h("div.section-title", {}, h("h2", {}, "Recent games")),
      h("div.card", {}, table([
        { label: "When", cls: "when", render: (r) => r.time.replace("T", " ").slice(5, 16) },
        { label: "P1", render: (r) => who(r, 1) },
        { label: "P2", render: (r) => who(r, 2) },
        { label: "Stage", render: (r) => r.stage_name },
        { label: "Result", render: (r) => resultText(r) },
        { label: "Length", cls: "num", render: (r) => fmt.frames(r.frames) },
        { label: "", cls: "num", render: (r) => r.id ? link(`/game/${r.id}`, "Replay") : "" },
      ], a.recent, { onRow: (r) => r.id && navigate(`/game/${r.id}`), rowClass: () => "clickable", empty: "No games yet." })));
  }, signal);
}
