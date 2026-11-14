// Arena: Elo standings, head-to-head scores and recent games.
import { navigate } from "../app.js";
import { api, every, fmt, h, link, mount, resultText, table, toast } from "../lib.js";

function heat(score) {
  const hue = Math.round(score * 120); // red → green
  return { background: `hsl(${hue} 55% 22%)`, color: `hsl(${hue} 80% 75%)` };
}

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
    mount(box,
      h("div.pagehead", {}, h("h1", {}, "Arena"), h("span.dim", {}, `${a.games} games · updated ${a.updated}`), h("span.spacer"), toggle),
      h("div.grid2", {},
        h("div.card", {}, h("h2", {}, "Standings"), table([
          { label: "#", render: (r) => a.table.indexOf(r) + 1 },
          { label: "Bot", render: (r) => h("b", {}, r.entrant) },
          { label: "Elo", cls: "num", render: (r) => h("span", {}, r.elo) },
          { label: "", render: (r) => h("div.bar", { style: { width: `${10 + ((r.elo - minElo) / (maxElo - minElo || 1)) * 90}%` } }) },
          { label: "W–L–D", cls: "num", render: (r) => `${r.wins}–${r.losses}–${r.draws}` },
          { label: "Win %", cls: "num", render: (r) => fmt.pct((100 * (r.wins + r.draws / 2)) / Math.max(1, r.wins + r.losses + r.draws)) },
        ], a.table)),
        h("div.card", {}, h("h2", {}, "Head to head ", h("span.dim", { style: { fontWeight: 400, fontSize: "12px" } }, "row's score vs column")),
          table([{ label: "", render: (r) => h("b", {}, r.entrant) },
            ...a.table.map((c) => ({ label: c.entrant, cls: "num", render: (r) => {
              const cell = a.h2h[`${r.spec}|${c.spec}`];
              if (r.spec === c.spec || !cell) return h("span.dim", {}, "·");
              return h("span.heat", { style: heat(cell.score / cell.n), title: `${cell.score}/${cell.n}` }, `${Math.round((100 * cell.score) / cell.n)}%`);
            } }))], a.table.filter((r) => specs.includes(r.spec))))),
      h("div.card", {}, h("h2", {}, "Recent games"), table([
        { label: "When", render: (r) => h("span.dim", {}, r.time.replace("T", " ")) },
        { label: "P1", render: (r) => h("span", { class: r.winner === 1 ? "win" : "" }, `${r.label1} (${r.char1_name})`) },
        { label: "P2", render: (r) => h("span", { class: r.winner === 2 ? "win" : "" }, `${r.label2} (${r.char2_name})`) },
        { label: "Stage", render: (r) => r.stage_name },
        { label: "Result", render: (r) => resultText(r) },
        { label: "Length", cls: "num", render: (r) => fmt.frames(r.frames) },
        { label: "", render: (r) => r.id ? link(`/game/${r.id}`, "replay →") : "" },
      ], a.recent, { onRow: (r) => r.id && navigate(`/game/${r.id}`), rowClass: () => "clickable" })));
  }, signal);
}
