// One bot-writer session: metadata and the final bot source.
import { api, emptyState, fmt, h, link, mount } from "../lib.js";

export default async function session(root, { id }) {
  const s = await api(`/api/botwriter/sessions/${id}`);
  const m = s.meta;
  const rows = [["Name", m.name], ["Harness", m.harness], ["Model", m.model], ["Effort", m.effort], ["Budget", `${m.minutes} min${m.budget_usd ? `, $${m.budget_usd}` : ""}`],
    ["Invocations", m.invocations], ["Exit", m.exit],
    ["Started", fmt.time(m.started)], ["Bot", m.bot_lines ? `${m.bot_lines} lines, sha256 ${m.bot_sha256?.slice(0, 12)}` : null],
    ["Validation", m.validation ? `${m.validation.ok ? "ok" : "FAILED"} · p99 ${m.validation.ms_p99} ms · max ${m.validation.ms_max} ms · ${m.validation.frames_with_input_pct}% frames with input` : null],
    ["SmashBot similarity", m.smashbot_similarity ? `${m.smashbot_similarity.overlap_renamed} (renamed)${m.smashbot_similarity.flagged ? " FLAGGED" : ""}` : null],
    ["Usage", m.usage ? Object.entries(m.usage).map(([k, v]) => `${k.replace("_input_tokens", "").replace("_tokens", "")} ${fmt.k(v)}`).join(", ") : null]]
    .filter(([, v]) => v !== null && v !== undefined);
  const stat = (label, v) => h("div.stat", {}, h("b", {}, v ?? "–"), h("span", {}, label));
  mount(root, h("div.pagehead", {}, link("/botwriter", h("span.back", {}, "← Bot-writer")),
    h("h1", { style: { flexBasis: "100%" } }, m.name || id), h("span.faint.mono", { style: { fontSize: "12px", marginTop: "-10px" } }, id)),
    h("div.grid2", { style: { gridTemplateColumns: "minmax(0, 380px) minmax(0, 1fr)", alignItems: "start" } },
      h("div.card", {},
        h("div.stat-row", {}, stat("cost", fmt.usd(m.cost_usd)), stat("wall time", fmt.secs(m.wall_s)), stat("turns", m.num_turns),
          stat("lines", m.bot_lines)),
        h("dl.kv", {}, rows.map(([k, v]) => [h("dt", {}, k), h("dd", {}, String(v))])),
        h("h3", { style: { marginTop: "18px" } }, "Files"), h("ul.file-list", {}, s.files.map((f) => h("li", { title: f }, f))),
        m.prompt ? [h("h3", {}, "Prompt"), h("pre.prompt-box", {}, m.prompt)] : null),
      h("div.card", {}, h("h2", {}, h("span.mono", { style: { fontStyle: "normal", fontSize: "15px", textTransform: "none", letterSpacing: 0 } }, "final/bot.py")),
        s.source ? h("pre.code.lines", {}, s.source.split("\n").map((ln) => h("span.ln", {}, ln || " "))) : emptyState("No final bot yet", "The session hasn't written final/bot.py."))));
}
