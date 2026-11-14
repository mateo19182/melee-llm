// One bot-writer session: metadata and the final bot source.
import { api, fmt, h, link, mount } from "../lib.js";

export default async function session(root, { id }) {
  const s = await api(`/api/botwriter/sessions/${id}`);
  const m = s.meta;
  const rows = [["Name", m.name], ["Harness", m.harness], ["Model", m.model], ["Effort", m.effort], ["Budget", `${m.minutes} min${m.budget_usd ? `, $${m.budget_usd}` : ""}`],
    ["Wall time", fmt.secs(m.wall_s)], ["Cost", fmt.usd(m.cost_usd)], ["Turns", m.num_turns], ["Invocations", m.invocations], ["Exit", m.exit],
    ["Started", fmt.time(m.started)], ["Bot", m.bot_lines ? `${m.bot_lines} lines, sha256 ${m.bot_sha256?.slice(0, 12)}` : null],
    ["Validation", m.validation ? `${m.validation.ok ? "ok" : "FAILED"} · p99 ${m.validation.ms_p99} ms · max ${m.validation.ms_max} ms · ${m.validation.frames_with_input_pct}% frames with input` : null],
    ["SmashBot similarity", m.smashbot_similarity ? `${m.smashbot_similarity.overlap_renamed} (renamed)${m.smashbot_similarity.flagged ? " FLAGGED" : ""}` : null],
    ["Usage", m.usage ? Object.entries(m.usage).map(([k, v]) => `${k.replace("_input_tokens", "").replace("_tokens", "")} ${fmt.k(v)}`).join(", ") : null]]
    .filter(([, v]) => v !== null && v !== undefined);
  mount(root, h("div.pagehead", {}, link("/botwriter", "← Bot-writer"), h("h1", {}, m.name || id), h("span.dim.mono", {}, id)),
    h("div.grid2", { style: { gridTemplateColumns: "minmax(0, 360px) minmax(0, 1fr)" } },
      h("div.card", {}, h("h2", {}, "Session"), h("dl.kv", {}, rows.map(([k, v]) => [h("dt", {}, k), h("dd", {}, String(v))])),
        h("h3", { style: { marginTop: "14px" } }, "Files"), h("ul.dim", { style: { paddingLeft: "18px", fontSize: "12.5px" } }, s.files.map((f) => h("li", {}, f))),
        m.prompt ? [h("h3", {}, "Prompt"), h("pre.dim", {}, m.prompt)] : null),
      h("div.card", {}, h("h2", {}, "final/bot.py"),
        s.source ? h("pre.code", {}, s.source.split("\n").map((ln) => h("span.ln", {}, ln || " "))) : h("div.dim", {}, "No final bot yet."))));
}
