// All matches: every runner.play() on this host (web jobs, arena, bot-writer ladders, scripts), live.
//
// The registry streams recent frames per match (/api/matches/events); each card plays them back a few hundred
// ms behind with Slippi Lab's character renderer (/slippilab-live.js, built from patches/slippilab.patch).
// The live slot's card shows the HLS video instead (toggle to 2D). /matches/<id> is the focus view.
import Hls from "../vendor/hls.min.mjs";
import { fmt, h, link, mount, stocks } from "../lib.js";

const ENDED = ["finished", "failed", "crashed"];
const PHASE = { starting: "loading Dolphin…", in_game: "in game", between: "between games", finished: "finished",
  failed: "failed", crashed: "crashed" };
const COLORS = ["#f0605d", "#4fa3ff"];
const LAG_S = 0.35; // playback delay behind the newest frame: covers the 15 Hz registry writes and SSE jitter

let rendererMod = null;
const renderer = () => (rendererMod ??= import("/slippilab-live.js").catch((e) => { console.error(e); return null; }));

// Plays registry samples ([frame, p1, p2]) back at the match's own speed, LAG_S behind the newest one.
class Playback {
  constructor(canvas, stage) {
    this.canvas = canvas;
    this.stage = stage;
    this.buf = [];
    this.head = null;
    this.rate = 60;
    this.shown = null;
    this.view = null;
    renderer().then((m) => { if (m) this.view = new m.LiveView(canvas, { stage }); });
  }
  push(frames) {
    for (const f of frames) {
      if (this.buf.length && f[0] < this.buf.at(-1)[0] - 60) { this.buf = []; this.head = null; } // new game: frames restart
      if (!this.buf.length || f[0] > this.buf.at(-1)[0]) this.buf.push(f);
    }
    if (this.buf.length > 900) this.buf.splice(0, this.buf.length - 600);
  }
  tick(dt) {
    if (!this.view || !this.buf.length) return;
    const newest = this.buf.at(-1)[0];
    const target = newest - this.rate * LAG_S;
    if (this.head === null || Math.abs(this.head - target) > this.rate * 2) this.head = target;
    this.head += dt * this.rate + (target - this.head) * 0.03; // follow the stream, drift back to the target lag
    let i = this.buf.length - 1;
    while (i > 0 && this.buf[i][0] > this.head) i--;
    const s = this.buf[i];
    if (s !== this.shown || this.canvas.width !== Math.round(this.canvas.clientWidth * devicePixelRatio)) {
      this.shown = s;
      this.view.draw(s);
    }
    if (i > 30) this.buf.splice(0, i - 30);
  }
}

function speedBadge(m) {
  if (!m.speed || m.phase !== "in_game") return null;
  if (m.speed >= 1.3) return h("span.badge.speed", { title: `${m.fps} game frames per second` }, `×${m.speed.toFixed(m.speed >= 10 ? 0 : 1)}`);
  if (m.speed <= 0.8) return h("span.badge.warn", { title: `${m.fps} game frames per second` }, `slow ×${m.speed.toFixed(2)}`);
  return h("span.badge", { title: `${m.fps} game frames per second` }, "real time");
}

function sourceBadge(m) {
  const kind = { job: "live", arena: "ok", botwriter: "warn", coach: "p1" }[m.source] || "";
  return h(`span.badge${kind ? "." + kind : ""}`, { title: m.argv || "" }, m.label || m.source);
}

function playersLine(m, big = false) {
  const side = (p) => {
    const pl = m.players?.[p] || {};
    const pct = m.percent?.[p];
    const st = m.stocks?.[p];
    return h(`div.mc-player.p${p}`, {},
      h("div.mc-name", {}, h(`span.port.p${p}`, {}, `P${p}`), " ", pl.label ?? "?", h("span.dim", {}, ` ${pl.char_name ?? ""}`)),
      h("div.mc-score", {}, h("span.mc-pct", { style: { color: COLORS[p - 1] } }, pct !== undefined ? `${Math.round(pct)}%` : "–"),
        st !== undefined ? stocks(st, COLORS[p - 1]) : null));
  };
  return h(`div.mc-players${big ? ".big" : ""}`, {}, side("1"), side("2"));
}

function decisionLine(m) {
  const d = (m.decisions || []).slice().sort((a, b) => (b.ts || 0) - (a.ts || 0))[0];
  if (!d) return null;
  const what = d.kind === "coach" ? d.command : d.action;
  const why = d.kind === "coach" ? d.why : d.reason;
  return h("div.mc-decision", { title: why || "" }, h("span.badge", { class: `p${d.port}` }, `P${d.port} ${d.kind}`), " ",
    h("b.mono", {}, what ?? "?"), why ? h("span.dim", {}, ` — ${why}`) : null);
}

function links(m, focus) {
  return h("div.mc-links", {},
    focus ? link(`/matches/${m.id}`, "Focus") : link("/matches", "← All matches"),
    m.game_id ? link(`/game/${m.game_id}`, "Replay") : null,
    m.job_id ? link(`/job/${m.job_id}`, `Job #${m.job_id}`) : null,
    m.live_slot ? link("/live", "Live page") : null);
}

function meta(m) {
  const bits = [m.stage_name, m.mode, m.games > 1 ? `game ${m.game + 1}/${m.games}` : null, PHASE[m.phase] || m.phase,
    m.frame && m.phase === "in_game" ? fmt.frames(m.frame + 123) : null, m.stale ? "no update for 10 min" : null];
  return h("div.mc-meta", {}, bits.filter(Boolean).join(" · "));
}

// One running match: header, stage view (canvas, or video for the live slot), score, latest decision.
class Card {
  constructor(m, { big = false } = {}) {
    this.id = m.id;
    this.big = big;
    this.canvas = h("canvas.mc-canvas");
    this.play = new Playback(this.canvas, m.stage);
    this.overlay = h("div.mc-overlay");
    this.stage = h("div.mc-stage", {}, this.canvas, this.overlay);
    this.head = h("div.mc-head");
    this.foot = h("div.mc-foot");
    this.el = h(`div.card.mc${big ? ".big" : ""}`, {}, this.head, this.stage, this.foot);
    this.mode2d = !m.live_slot || localStorage.getItem("melee.matches.video") === "0";
    this.update(m);
  }
  update(m) {
    this.m = m;
    if (m.fps) this.play.rate = m.fps;
    const toggle = m.live_slot ? h("div.toggle", {},
      h("button", { class: this.mode2d ? "" : "on", onclick: () => this.setVideo(true) }, "Video"),
      h("button", { class: this.mode2d ? "on" : "", onclick: () => this.setVideo(false) }, "2D")) : null;
    mount(this.head, h("div.mc-title", {}, sourceBadge(m), speedBadge(m), m.live_slot ? h("span.badge.live", {}, "on stream") : null,
      h("span.spacer"), toggle), meta(m));
    mount(this.foot, playersLine(m, this.big), decisionLine(m), links(m, !this.big));
    this.overlay.textContent = m.phase === "in_game" ? "" : m.phase === "between" ? "between games…" : PHASE[m.phase] || "";
    this.overlay.classList.toggle("on", m.phase !== "in_game");
    if (m.live_slot && !this.mode2d && !this.video) this.startVideo();
  }
  setVideo(on) {
    this.mode2d = !on;
    localStorage.setItem("melee.matches.video", on ? "1" : "0");
    if (on) this.startVideo(); else this.stopVideo();
    this.update(this.m);
  }
  startVideo() {
    const video = h("video.mc-video", { muted: true, autoplay: true, playsInline: true });
    this.stage.append(video);
    this.video = video;
    if (!Hls.isSupported()) { video.src = "/hls/index.m3u8"; return; }
    this.hls = new Hls({ lowLatencyMode: true, liveSyncDurationCount: 2, backBufferLength: 10 });
    this.hls.loadSource("/hls/index.m3u8");
    this.hls.attachMedia(video);
    this.hls.on(Hls.Events.MANIFEST_PARSED, () => video.play().catch(() => {}));
    this.hls.on(Hls.Events.ERROR, (_e, d) => { if (d.fatal) { this.stopVideo(); this.mode2d = true; this.update(this.m); } });
  }
  stopVideo() {
    this.hls?.destroy();
    this.hls = null;
    this.video?.remove();
    this.video = null;
  }
  destroy() {
    this.stopVideo();
    this.el.remove();
  }
}

function finishedCard(m) {
  const r = (m.results || []).at(-1);
  const pl = m.players || {};
  const winner = r?.winner ? `${pl[r.winner]?.label ?? `P${r.winner}`} wins` : r ? "draw" : (PHASE[m.phase] || m.phase);
  const score = r ? `${r.stocks["1"]}–${r.stocks["2"]} stocks` : m.error || "";
  return h(`div.card.mc-done${m.phase === "finished" ? "" : ".bad"}`, {},
    h("div.mc-title", {}, sourceBadge(m), h("span.spacer"), h("span.dim", {}, fmt.ago(m.finished || m.updated))),
    h("div.mc-done-players", {}, `${pl["1"]?.label ?? "?"} (${pl["1"]?.char_name ?? ""}) vs ${pl["2"]?.label ?? "?"} (${pl["2"]?.char_name ?? ""})`),
    h("div", {}, h("b", {}, winner), h("span.dim", {}, ` · ${score}${m.results?.length > 1 ? ` · ${m.results.length} games` : ""}`)),
    h("div.dim", {}, `${m.stage_name} · ${m.mode}`),
    h("div.mc-links", {}, m.game_id ? link(`/game/${m.game_id}`, "Replay") : null, m.job_id ? link(`/job/${m.job_id}`, `Job #${m.job_id}`) : null));
}

export default async function matches(root, params, signal) {
  const focus = params.id || null;
  const cards = new Map();
  const all = new Map();
  const grid = h("div.mc-grid");
  const done = h("div.mc-done-strip");
  const empty = h("div.card.dim", { style: { textAlign: "center", padding: "30px" } }, "Nothing running right now.");
  const count = h("span.dim");
  const missing = h("div.card.dim", {}, "This match is not in the registry (it ended a while ago?). ", link("/matches", "All matches →"));
  const doneBox = h("div", {}, h("h2", { style: { marginTop: "22px" } }, "Recently finished"), done);
  root.className = "";
  if (focus) mount(root, grid);
  else mount(root, h("div.pagehead", {}, h("h1", {}, "All matches"), count, h("span.spacer"),
    h("span.dim", { style: { fontSize: "12.5px" } }, "every runner.play() on this host: jobs, arena, bot-writer ladders, scripts")), grid, doneBox);
  if (focus) grid.className = "mc-focus";

  function render() {
    dirty = false;
    const running = [...all.values()].filter((m) => !ENDED.includes(m.phase));
    const ended = [...all.values()].filter((m) => ENDED.includes(m.phase)).sort((a, b) => (b.finished || 0) - (a.finished || 0));
    for (const [id, c] of cards) {
      if (!running.some((m) => m.id === id) && !(focus && all.has(id))) { c.destroy(); cards.delete(id); }
    }
    const shown = focus ? [...all.values()] : running;
    shown.sort((a, b) => (b.live_slot - a.live_slot) || (a.started - b.started));
    for (const m of shown) {
      let c = cards.get(m.id);
      if (!c) { c = new Card(m, { big: !!focus }); cards.set(m.id, c); }
      else c.update(m);
      grid.append(c.el); // re-appending keeps the order without rebuilding
    }
    if (!focus) {
      if (!running.length) grid.append(empty); else empty.remove();
      count.textContent = `${running.length} running`;
      mount(done, ended.length ? ended.slice(0, 15).map(finishedCard) : h("div.dim", {}, "None in the last hours."));
    } else if (!all.size) grid.append(missing);
    else missing.remove();
  }

  let dirty = false;
  const es = new EventSource(`/api/matches/events${focus ? `?id=${encodeURIComponent(focus)}` : ""}`);
  es.addEventListener("match", (e) => { const m = JSON.parse(e.data); all.set(m.id, m); dirty = true; });
  es.addEventListener("frames", (e) => {
    const { id, frames } = JSON.parse(e.data);
    if (dirty) render(); // a card for a match announced just before its frames
    cards.get(id)?.play.push(frames);
  });
  es.addEventListener("gone", (e) => { all.delete(JSON.parse(e.data).id); dirty = true; });
  es.addEventListener("hello", () => { all.clear(); dirty = true; });
  signal.addEventListener("abort", () => es.close());
  setTimeout(() => { if (!all.size) render(); }, 1500);

  let last = performance.now();
  const loop = (t) => {
    if (signal.aborted) return;
    const dt = Math.min(0.25, (t - last) / 1000);
    last = t;
    if (dirty) render();
    for (const c of cards.values()) if (c.mode2d || !c.video) c.play.tick(dt);
    requestAnimationFrame(loop);
  };
  requestAnimationFrame(loop);
  signal.addEventListener("abort", () => { for (const c of cards.values()) c.destroy(); });
}
