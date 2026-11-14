// One job: spec, per-game results with links to the game pages, token spend, process output.
import { api, emptyState, every, fmt, h, link, mount, resultText, statusBadge, table, toast } from "../lib.js";

export default async function job(root, { id }, signal) {
  const box = h("div.stack");
  mount(root, box);
  every(3000, async () => {
    const j = await api(`/api/jobs/${id}`);
    const active = j.status === "queued" || j.status === "running";
    const t = j.tokens;
    mount(box,
      h("div.pagehead", {}, h("h1", {}, `Job #${j.id}`), statusBadge(j.status), h("span.dim", {}, `${j.mode} · ${j.lane} · ${j.stage_name}`),
        h("span.spacer"), active ? h("button.danger", { disabled: !!j.cancel, onclick: async () => {
          await api(`/api/jobs/${j.id}/cancel`, { method: "POST" }); toast("Cancelling"); } }, j.cancel ? "Cancelling…" : "Cancel") : null,
        j.lane === "live" && j.status === "running" ? link("/live", h("button.primary", {}, "Watch live")) : null),
      h("div.matchup", {}, h("span.port.p1", { style: { fontSize: "16px" } }, "P1"), h("span.side.p1", {}, j.label1, h("span.char", {}, j.char1_name)),
        h("span.vs", {}, "vs"), h("span.port.p2", { style: { fontSize: "16px" } }, "P2"), h("span.side.p2", {}, j.label2, h("span.char", {}, j.char2_name))),
      h("div.grid2", {},
        h("div.card", {}, h("h2", {}, "Match"), h("dl.kv", {},
          h("dt", {}, "P1"), h("dd", {}, h("span.mono", {}, j.p1)),
          h("dt", {}, "P2"), h("dd", {}, h("span.mono", {}, j.p2)),
          h("dt", {}, "Games"), h("dd", {}, `${j.results.length} of ${j.games}`),
          h("dt", {}, "Queued"), h("dd", {}, fmt.time(j.created)),
          h("dt", {}, "Ran"), h("dd", {}, j.started ? `${fmt.time(j.started)} · ${fmt.secs((j.finished || Date.now() / 1000) - j.started)}` : "–"),
          h("dt", {}, "Slippi port"), h("dd", {}, j.port ?? "–"),
          j.error ? [h("dt", {}, "Error"), h("dd", { style: { color: "var(--bad)" } }, j.error)] : null)),
        h("div.card", {}, h("h2", {}, "LLM tokens"), t ? h("div", {},
          h("dl.kv", {}, h("dt", {}, "Calls"), h("dd", {}, fmt.num(t.calls)),
            h("dt", {}, "Prompt"), h("dd", {}, fmt.num(t.prompt)), h("dt", {}, "Completion"), h("dd", {}, fmt.num(t.completion)),
            h("dt", {}, "Estimated cost"), h("dd", {}, t.est_usd !== null ? `${fmt.usd(t.est_usd)} at list prices` : "unknown model price")),
          table([{ label: "Model", key: "m" }, { label: "Calls", key: "calls", cls: "num" },
            { label: "Prompt", cls: "num", render: (r) => fmt.num(r.prompt) }, { label: "Completion", cls: "num", render: (r) => fmt.num(r.completion) }],
          Object.entries(t.by_model).map(([m, v]) => ({ m, ...v }))))
          : emptyState("No LLM calls", "Nothing logged for this job (yet)."))),
      h("div.card", {}, h("h2", {}, "Games"), table([
        { label: "Game", render: (r) => `#${r.game + 1}` },
        { label: "Result", render: (r) => resultText(r) },
        { label: "Percent", render: (r) => `${Math.round(r.percent["1"])}% / ${Math.round(r.percent["2"])}%` },
        { label: "Length", render: (r) => fmt.frames(r.frames) },
        { label: "", render: (r) => r.gid ? link(`/game/${r.gid}`, "Replay & decisions →") : "–" },
      ], j.results.map((r, i) => ({ ...r, game: r.game ?? i, gid: j.game_ids[i] })), { empty: active ? "No finished game yet." : "No games." })),
      h("div.card", {}, h("h2", {}, "Output ", h("span.dim.mono", {}, j.dir)),
        h("pre.code", { style: { maxHeight: "40vh" } }, j.output_tail || "(empty)")));
  }, signal);
}
