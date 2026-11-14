// Render decision-log records (llm_paused / llm_live / coach) as cards, shared by the live and game pages.
import { details, fmt, h } from "./lib.js";

function params(decision) {
  if (!decision) return "";
  const p = Object.entries(decision).filter(([k]) => k !== "action" && k !== "reason").map(([k, v]) => `${k}=${v}`);
  return p.length ? `(${p.join(", ")})` : "";
}

const lat = (s) => (s === null || s === undefined ? null : `${s.toFixed(2)} s`);

export function recordCard(rec, port, kind, opts = {}) {
  const cls = `div.ev.p${port}${rec.error ? ".err" : ""}${opts.onclick ? ".clickable" : ""}`;
  const tag = h("span.badge", { class: `p${port}` }, `P${port}`);
  const frame = rec.frame !== undefined && rec.frame !== null ? h("span.frame", {}, `f${rec.frame}`) : null;
  const attrs = { onclick: opts.onclick, "data-frame": rec.frame ?? "" };
  if (rec.type === "game_start") {
    const who = kind === "coach" ? `coach ${rec.coach} steering ${rec.body}` : `${rec.agent} · ${rec.model}`;
    return h("div.ev.sys", attrs, h("div.ev-head", {}, tag, h("b", {}, "Game start"), h("span", {}, who)),
      h("div", {}, `${rec.character} vs ${rec.opponent} on ${rec.stage}, decides every ${rec.interval} frames` +
        (rec.commands ? `, ${rec.commands} commands on the menu` : "")),
      rec.system_prompt ? details("system prompt", h("pre", {}, rec.system_prompt)) : null);
  }
  if (rec.type === "game_end") {
    const bits = [`${rec.decisions} decisions`, rec.changes !== undefined ? `${rec.changes} changes` : null,
      `${rec.errors} errors`, rec.mean_latency_s ? `mean latency ${rec.mean_latency_s.toFixed(2)} s` : null,
      rec.mean_stale_frames ? `mean staleness ${rec.mean_stale_frames} f` : null,
      `${fmt.k(rec.prompt_tokens)} / ${fmt.k(rec.completion_tokens)} tokens`].filter(Boolean);
    return h("div.ev.sys", attrs, h("div.ev-head", {}, tag, h("b", {}, "Game end"), frame), h("div", {}, bits.join(" · ")));
  }
  if (rec.type === "dropped") {
    return h(cls, attrs, h("div.ev-head", {}, tag, frame, h("span.ev-action.dim", {}, `dropped ${rec.decision?.action ?? "reply"}`),
      h("span.ev-meta", {}, `stale ${rec.stale_frames} f · ${lat(rec.latency_s)}`)),
      h("div.dim", {}, "the reply arrived too late and was discarded"));
  }
  if (rec.type !== "decision") return null;
  if (kind === "coach") {
    const r = rec.router;
    const meta = [lat(rec.latency_s), rec.latency_frames !== null && rec.latency_frames !== undefined ? `${rec.latency_frames} f` : null,
      rec.prompt_tokens ? `${fmt.k(rec.prompt_tokens)} tok` : null].filter(Boolean).join(" · ");
    return h(cls, attrs,
      h("div.ev-head", {}, tag, frame, h("span.ev-action", {}, rec.command),
        rec.changed ? h("span.badge.ok", {}, "changed") : h("span.badge", {}, "kept"), h("span.ev-meta", {}, meta)),
      rec.why ? h("div.ev-reason", {}, rec.why) : null,
      rec.phrase && rec.changed ? h("div.dim", {}, `→ "${rec.phrase}"`) : null,
      r ? h("div.dim", {}, `router: ${r.outcome}${r.name ? ` → ${r.name}` : ""}${r.score !== undefined ? ` (${Number(r.score).toFixed(2)})` : ""}`) : null,
      rec.error ? h("div.error", {}, rec.error) : null,
      rec.state ? details("state the coach saw", h("pre", {}, rec.state)) : null);
  }
  const meta = [lat(rec.latency_s),
    rec.stale_frames ? `stale ${rec.stale_frames} f` : null,
    rec.prompt_tokens ? `${fmt.k(rec.prompt_tokens)}+${rec.completion_tokens} tok` : null].filter(Boolean).join(" · ");
  return h(cls, attrs,
    h("div.ev-head", {}, tag, frame, h("span.ev-action", {}, `${rec.action ?? rec.decision?.action ?? "?"}${params(rec.decision)}`),
      h("span.ev-meta", {}, meta)),
    rec.reason ? h("div.ev-reason", {}, rec.reason) : null,
    rec.error ? h("div.error", {}, rec.error + (rec.raw ? `: ${rec.raw}` : "")) : null,
    rec.obs_text ? details("state the model saw", h("pre", {}, rec.obs_text)) : null);
}

export function steerCard(port, st, player) {
  const rows = Object.entries(st).filter(([k, v]) => k !== "router" && v !== null && v !== "");
  return h("div.ev.p" + port, {},
    h("div.ev-head", {}, h("span.badge", { class: `p${port}` }, `P${port}`), h("b", {}, player?.label ?? ""),
      h("span.ev-meta", {}, "steer state")),
    h("dl.steer", {}, rows.map(([k, v]) => [h("dt", {}, k), h("dd", {}, typeof v === "number" ? +v.toFixed(3) : String(v))]),
      st.router ? [h("dt", {}, "router"), h("dd", {}, `${st.router.outcome ?? ""} ${st.router.name ?? ""}`)] : null));
}
