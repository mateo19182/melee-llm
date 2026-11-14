// Router: history API, one module per page. Each page gets (root, params, signal) and stops its timers on abort.
import { api, h, mount } from "./lib.js";

const routes = [
  [/^\/bench(\/(?<id>.+))?$/, () => import("./pages/bench.js")],
  [/^\/(live)?$/, () => import("./pages/live.js")],
  [/^\/matches(\/(?<id>[\w.-]+))?$/, () => import("./pages/matches.js")],
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
  [/^\/training$/, () => import("./pages/training.js")],
  [/^\/docs(\/(?<name>[\w-]+))?$/, () => import("./pages/docs.js")],
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
  frameTitle();
  describe();
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

// Menu chrome: the frame's title tab names the current section, and its top edge steps up just past the title.
// The description box under the frame explains the menu item under the pointer, else the current one.
function frameTitle() {
  const title = document.getElementById("frame-title");
  title.textContent = document.querySelector("#nav a.active")?.textContent ?? "";
  document.getElementById("frame").style.setProperty("--sx", `${title.offsetWidth + 36}px`);
}
function describe(a = document.querySelector("#nav a.active")) {
  document.getElementById("desc").textContent = a?.dataset.desc ?? "";
}
document.fonts.ready.then(frameTitle);
document.getElementById("nav").addEventListener("mouseover", (e) => { const a = e.target.closest("a"); if (a) describe(a); });
document.getElementById("nav").addEventListener("mouseleave", () => describe());

async function onAir() {
  if (document.hidden) return;
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
document.addEventListener("visibilitychange", onAir);
onAir();
render();
