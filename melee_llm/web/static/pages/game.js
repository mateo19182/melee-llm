// One game: Slippi Lab replay embed and the decision log as a timeline synced to the replay frame.
//
// The patched Slippi Lab (patches/slippilab.patch) posts {type: "slippilab:frame", frame} on every frame
// and accepts {type: "slippilab:seek", frame}. Without the patch, clicks reload the embed at #<frame index>.
import { recordCard } from "../decisions.js";
import { fmt, h, link, mount, playerLine, resultText, api } from "../lib.js";

const FIRST_FRAME = -123; // Slippi frame numbers start at -123; Slippi Lab's #N is an index from there

export default async function game(root, { id }, signal) {
  const g = await api(`/api/games/${id}`);
  const replayUrl = `/api/replay/${g.id}/${encodeURIComponent(g.name)}`;
  const base = `/slippilab/?replayUrl=${encodeURIComponent(replayUrl)}`;
  const iframe = h("iframe.replay-frame", { src: base, allow: "fullscreen" });
  let synced = false;
  let current = null;
  let follow = true;

  const recs = [];
  for (const lg of g.decision_logs) {
    const port = lg.port ?? (lg.name.match(/\.p(\d)\./)?.[1] ?? 1);
    for (const r of lg.records) recs.push({ r, port, kind: lg.kind });
  }
  const decisions = recs.filter((x) => x.r.type === "decision" || x.r.type === "dropped").sort((a, b) => a.r.frame - b.r.frame);
  const others = recs.filter((x) => x.r.type === "game_start" || x.r.type === "game_end");
  const last = Math.max(g.frames || 0, ...decisions.map((d) => d.r.frame), 1);

  function seek(frame) {
    frame = Math.max(FIRST_FRAME, frame);
    if (synced) iframe.contentWindow.postMessage({ type: "slippilab:seek", frame }, "*");
    else iframe.src = `${base}#${frame - FIRST_FRAME}`;
  }

  const cards = decisions.map((d) => {
    const el = recordCard(d.r, d.port, d.kind, { onclick: () => seek(d.r.asked_frame ?? d.r.frame) });
    d.el = el;
    return el;
  });
  const span = last - FIRST_FRAME;
  const pos = (f) => `${((f - FIRST_FRAME) / span) * 100}%`;
  const cursor = h("div.cursor", { style: { left: "0%" } });
  const bar = h("div.timeline-bar", { title: "click to seek", onclick: (e) => {
    const r = bar.getBoundingClientRect();
    seek(Math.round(FIRST_FRAME + ((e.clientX - r.left) / r.width) * span));
  } }, decisions.map((d) => h(`div.tick${d.r.changed ? ".changed" : ""}`, {
    style: { left: pos(d.r.frame), "--c": d.port == 1 ? "var(--p1)" : "var(--p2)" } })), cursor);
  const frameInfo = h("span.dim.mono", {}, "");
  const list = h("div.panel-body", {}, others.filter((x) => x.r.type === "game_start").map((x) => recordCard(x.r, x.port, x.kind)),
    cards, others.filter((x) => x.r.type === "game_end").map((x) => recordCard(x.r, x.port, x.kind)));

  function onFrame(frame) {
    cursor.style.left = pos(frame);
    frameInfo.textContent = `frame ${frame} · ${fmt.frames(Math.max(0, frame))}`;
    let idx = -1;
    for (let i = 0; i < decisions.length && decisions[i].r.frame <= frame; i++) idx = i;
    const d = decisions[idx];
    if (d === current) return;
    current?.el.classList.remove("current");
    current = d;
    if (d) {
      d.el.classList.add("current");
      if (follow) d.el.scrollIntoView({ block: "nearest", behavior: "smooth" });
    }
  }
  const onMsg = (e) => {
    if (e.source !== iframe.contentWindow || !e.data || typeof e.data !== "object") return;
    if (e.data.type === "slippilab:frame") { synced = true; onFrame(e.data.frame); }
  };
  window.addEventListener("message", onMsg);
  signal.addEventListener("abort", () => window.removeEventListener("message", onMsg));

  const t = g.tokens;
  const head = h("div.pagehead", {},
    h("h1", {}, playerLine(g, 1), h("span.dim", {}, " vs "), playerLine(g, 2)),
    h("span.badge", {}, g.stage_name), g.mode ? h("span.badge", {}, g.mode) : null,
    h("span", {}, resultText(g)), h("span.dim", {}, `${g.time} · ${fmt.frames(g.frames)}`),
    h("span.spacer"),
    g.job_id ? link(`/job/${g.job_id}`, `Job #${g.job_id}`) : h("span.dim", {}, g.source_label),
    h("a", { href: replayUrl, download: g.name }, "Download .slp"),
    h("a", { href: base, target: "_blank" }, "Open in Slippi Lab ↗"));

  if (!decisions.length && !others.length) {
    mount(root, head, iframe);
    return;
  }
  const followBox = h("label.check", { style: { fontSize: "12px" } }, h("input", { type: "checkbox", checked: true,
    onchange: (e) => { follow = e.target.checked; } }), "follow");
  mount(root, head, h("div.game-layout", {}, iframe,
    h("div.card.panel", { style: { height: "calc(100vh - 170px)", top: "72px" } },
      h("div.panel-head", { style: { flexDirection: "column", alignItems: "stretch" } },
        h("div.row", {}, h("h2", {}, `Decisions (${decisions.length})`), frameInfo, h("span.spacer"), followBox),
        bar,
        t ? h("div.dim", { style: { fontSize: "12px" } }, `${fmt.num(t.calls)} LLM calls · ${fmt.tokens(t)}`,
          t.est_usd !== null ? ` · ~${fmt.usd(t.est_usd)}` : "") : null,
        h("div.dim", { style: { fontSize: "12px" } }, "Click a decision to jump to the state the model saw.")),
      list)));
}
