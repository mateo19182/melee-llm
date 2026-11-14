// Router: history API, one module per page. Each page gets (root, params, signal) and stops its timers on abort.
import { api, h, mount } from "./lib.js";

const routes = [
  [/^\/(live)?$/, () => import("./pages/live.js")],
  [/^\/(launch|jobs)$/, () => import("./pages/launch.js")],
  [/^\/job\/(?<id>\d+)$/, () => import("./pages/job.js")],
  [/^\/games$/, () => import("./pages/games.js")],
  [/^\/game\/(?<id>[0-9a-f]+)$/, () => import("./pages/game.js")],
  [/^\/arena$/, () => import("./pages/arena.js")],
  [/^\/coach$/, () => import("./pages/coach.js")],
  [/^\/botwriter$/, () => import("./pages/botwriter.js")],
  [/^\/botwriter\/(?<id>[\w.-]+)$/, () => import("./pages/session.js")],
  [/^\/ladder\/(?<name>[\w.-]+)$/, () => import("./pages/botwriter.js")],
  [/^\/play$/, () => import("./pages/play.js")],
];

let current = null;

async function render() {
  current?.abort();
  current = new AbortController();
  const signal = current.signal;
  const root = document.getElementById("app");
  const path = location.pathname;
  for (const a of document.querySelectorAll("#nav a")) {
    const href = a.getAttribute("href");
    a.classList.toggle("active", path === href || (href !== "/live" && path.startsWith(href.replace(/s$/, ""))) || (href === "/live" && path === "/"));
  }
  for (const [re, load] of routes) {
    const m = path.match(re);
    if (!m) continue;
    root.className = "";
    mount(root, h("div.loading", {}, "Loading…"));
    try {
      const mod = await load();
      if (signal.aborted) return;
      await mod.default(root, { ...(m.groups || {}), query: new URLSearchParams(location.search) }, signal);
    } catch (e) {
      if (!signal.aborted) mount(root, h("div.error-box", {}, `Error: ${e.message}`));
      console.error(e);
    }
    return;
  }
  mount(root, h("div.error-box", {}, "Not found"));
}

export function navigate(href, replace = false) {
  if (replace) history.replaceState(null, "", href);
  else history.pushState(null, "", href);
  render();
  window.scrollTo(0, 0);
}

document.addEventListener("click", (e) => {
  const a = e.target.closest("a[data-link]");
  if (!a || e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
  e.preventDefault();
  navigate(a.getAttribute("href"));
});
window.addEventListener("popstate", render);

async function onAir() {
  const el = document.getElementById("onair");
  try {
    const { status: s } = await api("/api/live");
    if (s.source === "idle" || s.phase === "idle" || !s.players) {
      mount(el, h("span.dot.off"), "idle");
    } else {
      const src = s.source === "job" ? `job #${s.job_id}` : s.source;
      mount(el, h("span.dot"), `${s.players["1"].label} vs ${s.players["2"].label}`, h("span.dim", {}, ` · ${src}`));
    }
  } catch { mount(el, h("span.dot.off"), "offline"); }
}
setInterval(onAir, 5000);
onAir();
render();
