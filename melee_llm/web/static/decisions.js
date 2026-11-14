// Decision-log records (llm_paused / llm_live / coach) as compact feed entries, shared by the live and game pages.
// One line each: callsign, action chip, latency meta, one-line reason. Click expands the full state and reply.
import { fmt, h } from "./lib.js";

function params(decision) {
  if (!decision || typeof decision !== "object") return "";
  const p = Object.entries(decision).filter(([k]) => k !== "action" && k !== "reason").map(([k, v]) => `${k}=${v}`);
  return p.length ? `(${p.join(", ")})` : "";
}

const lat = (s) => (s === null || s === undefined ? null : `${Number(s).toFixed(2)}s`);

// "claude-haiku-4-5-20251001" → "haiku-4-5"
export function callsign(model) {
  if (!model) return null;
  return String(model).replace(/^(claude|anthropic)[-/]/, "").replace(/-\d{8}$/, "");
}

function block(label, body) {
  return h("div", {}, h("div.k", {}, label), body);
}

function entry(rec, port, attrs, head, reason, more) {
  const el = h(`div.ev.p${port}${rec.error ? ".err" : ""}`, { class: "clickable", "data-frame": rec.frame ?? "" },
    h("div.ev-head", {}, ...head, h("span.onscreen-tag", {}, "on screen")),
    reason ? h("div.ev-reason", { title: reason }, reason) : null,
    h("div.ev-more", {}, more));
  el.addEventListener("click", (e) => {
    if (e.target.closest(".ev-more")) return; // let people select text in the expanded state
    el.classList.toggle("open");
    attrs.onclick?.(e);
  });
  return el;
}

export function recordCard(rec, port, kind, opts = {}) {
  const frame = rec.frame !== undefined && rec.frame !== null ? `f${rec.frame}` : null;
  const attrs = { onclick: opts.onclick };
  const who = opts.callsign || callsign(rec.model) || (kind === "coach" ? "coach" : `P${port}`);
  const call = h("span.ev-call", {}, who);
  if (rec.type === "game_start") {
    const what = kind === "coach" ? `coach ${rec.coach} steering ${rec.body}` : `${rec.agent} · ${callsign(rec.model)}`;
    return h("div.ev.sys", {}, h("b", {}, "Game start"), `P${port} ${what} · ${rec.character} vs ${rec.opponent} on ${rec.stage}, every ${rec.interval} frames`,
      rec.commands ? `, ${rec.commands} commands` : "");
  }
  if (rec.type === "game_end") {
    const bits = [`${rec.decisions} decisions`, rec.changes !== undefined ? `${rec.changes} changes` : null, `${rec.errors} errors`,
      rec.mean_latency_s ? `mean ${Number(rec.mean_latency_s).toFixed(2)}s` : null,
      rec.mean_stale_frames ? `stale ${rec.mean_stale_frames}f` : null,
      `${fmt.k(rec.prompt_tokens)} / ${fmt.k(rec.completion_tokens)} tok`].filter(Boolean);
    return h("div.ev.sys", {}, h("b", {}, "Game end"), `P${port} · ${bits.join(" · ")}`);
  }
  if (rec.type === "dropped") {
    return entry(rec, port, attrs,
      [call, h("span.ev-action.dropped", {}, rec.decision?.action ?? "reply"), h("span.ev-meta", {}, [frame, `stale ${rec.stale_frames}f`, lat(rec.latency_s)].filter(Boolean).join(" · "))],
      "Arrived too late; discarded.", null);
  }
  if (rec.type !== "decision") return null;
  if (kind === "coach") {
    const r = rec.router;
    const meta = [frame, lat(rec.latency_s), rec.latency_frames !== null && rec.latency_frames !== undefined ? `${rec.latency_frames}f` : null].filter(Boolean).join(" · ");
    return entry(rec, port, attrs,
      [call, h(`span.ev-action${rec.changed ? "" : ".kept"}`, { title: rec.changed ? "new command" : "kept the current command" }, rec.command), h("span.ev-meta", {}, meta)],
      rec.why,
      [rec.phrase ? block("said", h("div", {}, `“${rec.phrase}”`)) : null,
        r ? block("router", h("div", {}, `${r.outcome}${r.name ? ` → ${r.name}` : ""}${r.score !== undefined ? ` (${Number(r.score).toFixed(2)})` : ""}`)) : null,
        rec.prompt_tokens ? block("tokens", h("div", {}, `${fmt.k(rec.prompt_tokens)} in · ${rec.completion_tokens} out`)) : null,
        rec.error ? h("div.error", {}, rec.error) : null,
        rec.state ? block("state the coach saw", h("pre", {}, rec.state)) : null]);
  }
  const action = rec.action ?? rec.decision?.action ?? "?";
  const meta = [frame, lat(rec.latency_s), rec.stale_frames ? `stale ${rec.stale_frames}f` : null].filter(Boolean).join(" · ");
  const p = params(rec.decision);
  return entry(rec, port, attrs,
    [call, h("span.ev-action", { title: `${action}${p}` }, action), h("span.ev-meta", {}, meta)],
    rec.reason,
    [p ? block("action", h("div.mono", {}, `${action}${p}`)) : null,
      rec.prompt_tokens ? block("tokens", h("div", {}, `${fmt.k(rec.prompt_tokens)} in · ${rec.completion_tokens} out`)) : null,
      rec.error ? h("div.error", {}, rec.error + (rec.raw ? `: ${rec.raw}` : "")) : null,
      rec.obs_text ? block("state the model saw", h("pre", {}, rec.obs_text)) : null]);
}

export function steerCard(port, st, player) {
  const rows = Object.entries(st).filter(([k, v]) => k !== "router" && v !== null && v !== "");
  return h(`div.steer-card.p${port}`, { style: { "--c": port == 1 ? "var(--p1)" : "var(--p2)" } },
    h("div.ev-head", {}, h("span.ev-call", {}, player?.label ?? `P${port}`), h("span.ev-meta", {}, "steer state")),
    h("div.steer", {}, rows.map(([k, v]) => h("span", {}, k, h("b", {}, typeof v === "number" ? +v.toFixed(3) : String(v)))),
      st.router ? h("span", {}, "router", h("b", {}, `${st.router.outcome ?? ""} ${st.router.name ?? ""}`)) : null));
}
