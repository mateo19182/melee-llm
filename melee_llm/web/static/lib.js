// Small DOM and fetch helpers shared by every page.

export function h(tag, attrs = {}, ...children) {
  const [name, ...classes] = tag.split(".");
  const el = document.createElement(name || "div");
  if (classes.length) el.className = classes.join(" ");
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === undefined || v === null || v === false) continue;
    if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "class") el.className += (el.className ? " " : "") + v;
    else if (k === "style" && typeof v === "object") {
      for (const [sk, sv] of Object.entries(v)) sk.startsWith("--") ? el.style.setProperty(sk, sv) : (el.style[sk] = sv);
    }
    else if (k in el && k !== "list") el[k] = v;
    else el.setAttribute(k, v === true ? "" : v);
  }
  append(el, children);
  return el;
}

function append(el, children) {
  for (const c of children.flat(Infinity)) {
    if (c === null || c === undefined || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
}

export function mount(el, ...children) {
  el.replaceChildren();
  append(el, children);
  return el;
}

export async function api(path, opts = {}) {
  const init = { headers: {}, ...opts };
  if (opts.body && typeof opts.body !== "string") {
    init.body = JSON.stringify(opts.body);
    init.headers["Content-Type"] = "application/json";
  }
  const r = await fetch(path, init);
  const data = await r.json().catch(() => ({}));
  if (!r.ok && !opts.allowError) throw Object.assign(new Error(data.error || r.statusText), { data, status: r.status });
  return opts.allowError ? { ok: r.ok, status: r.status, data } : data;
}

export function link(href, ...children) {
  return h("a", { href, "data-link": "" }, ...children);
}

export const fmt = {
  num: (n, d = 0) => (n === null || n === undefined ? "–" : Number(n).toLocaleString(undefined, { maximumFractionDigits: d, minimumFractionDigits: d })),
  pct: (n) => (n === null || n === undefined ? "–" : `${Math.round(n)}%`),
  secs: (s) => {
    if (s === null || s === undefined) return "–";
    s = Math.round(s);
    if (s < 60) return `${s}s`;
    if (s < 3600) return `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, "0")}s`;
    return `${Math.floor(s / 3600)}h ${String(Math.floor((s % 3600) / 60)).padStart(2, "0")}m`;
  },
  frames: (f) => (f === null || f === undefined ? "–" : fmt.secs(f / 60)),
  time: (ts) => (ts ? new Date(ts * 1000).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "–"),
  ago: (ts) => {
    if (!ts) return "–";
    const s = Date.now() / 1000 - ts;
    if (s < 60) return "just now";
    if (s < 3600) return `${Math.floor(s / 60)} min ago`;
    if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
    return fmt.time(ts);
  },
  usd: (x) => (x === null || x === undefined ? "–" : x < 0.01 ? `$${x.toFixed(4)}` : `$${x.toFixed(2)}`),
  tokens: (t) => (t ? `${fmt.k(t.prompt)} in / ${fmt.k(t.completion)} out` : "–"),
  k: (n) => (n >= 1e6 ? `${(n / 1e6).toFixed(1)}M` : n >= 1e3 ? `${(n / 1e3).toFixed(1)}k` : String(n ?? 0)),
};

export function badge(text, kind = "") {
  return h(`span.badge${kind ? "." + kind : ""}`, {}, text);
}

export function statusBadge(status) {
  return badge(status, { running: "live", queued: "warn", done: "ok", failed: "bad", cancelled: "muted" }[status] || "");
}

export function stocks(n, color) {
  const el = h("span.stocks");
  for (let i = 0; i < 4; i++) el.append(h(`span.stock${i < n ? "" : ".lost"}`, { style: { "--c": color } }));
  return el;
}

export function playerLine(g, p) {
  return h("span.player", {}, h(`span.port.p${p}`, {}, `P${p}`), " ", g[`label${p}`] ?? g[`p${p}`],
    h("span.dim", {}, ` (${g[`char${p}_name`] ?? g[`char${p}`] ?? "?"})`));
}

export function resultText(g) {
  if (!g.stocks) return "–";
  const s1 = g.stocks["1"], s2 = g.stocks["2"];
  const w = g.winner ? `P${g.winner} wins` : "draw";
  return `${w} · ${Math.round(s1 ?? 0)}–${Math.round(s2 ?? 0)} stocks`;
}

export function toast(msg, kind = "") {
  const el = h(`div.toast${kind ? "." + kind : ""}`, {}, msg);
  document.body.append(el);
  setTimeout(() => el.classList.add("show"), 10);
  setTimeout(() => { el.classList.remove("show"); setTimeout(() => el.remove(), 400); }, 4000);
}

export function details(summary, ...body) {
  return h("details", {}, h("summary", {}, summary), ...body);
}

export function table(cols, rows, opts = {}) {
  return h("div.table-wrap", {}, h(`table${opts.cls ? "." + opts.cls : ""}`, {},
    h("thead", {}, h("tr", {}, cols.map((c) => h("th", { class: c.cls }, c.label)))),
    h("tbody", {}, rows.length ? rows.map((r) => h("tr", { class: opts.rowClass?.(r), onclick: opts.onRow ? (e) => { if (!e.target.closest("a, button, input")) opts.onRow(r); } : undefined },
      cols.map((c) => h("td", { class: c.cls }, c.render ? c.render(r) : r[c.key] ?? "–"))))
      : h("tr", {}, h("td.empty", { colSpan: cols.length }, opts.empty || "nothing yet")))));
}

// Periodic refresh that stops when the page changes.
export function every(ms, fn, signal) {
  fn();
  const id = setInterval(fn, ms);
  signal.addEventListener("abort", () => clearInterval(id));
}
