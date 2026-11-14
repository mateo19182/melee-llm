// Live page: LL-HLS video of display :99, the now-playing header and the LLM interaction panel.
//
// Sync: every SSE event carries the server wall-clock time it happened (`ts`). mediamtx stamps HLS segments
// with EXT-X-PROGRAM-DATE-TIME from the same clock, so hls.playingDate is "server time currently on screen".
// Events wait in a queue until the video reaches them; "instant" shows them on arrival.
import Hls from "../vendor/hls.min.mjs";
import { recordCard, steerCard } from "../decisions.js";
import { api, every, fmt, h, link, mount, stocks, toast } from "../lib.js";

const MAX_EVENTS = 300;

export default async function live(root, _params, signal) {
  root.className = "";
  let instant = localStorage.getItem("melee.instant") === "1";
  let offset = 0; // server clock - browser clock, seconds
  const serverNow = () => Date.now() / 1000 + offset;
  let queue = [];
  let shownStatus = null;
  let gameKey = null;

  // ---------------------------------------------------------------- layout
  const header = h("div.card.nowplaying", {}, h("div.dim", {}, "Connecting…"));
  const video = h("video", { muted: true, autoplay: true, playsInline: true, controls: true });
  const videoMsg = h("div.video-msg", {}, "Starting stream…");
  const delayInfo = h("span", {}, "");
  const goLive = h("button.small", { onclick: () => { if (hls?.liveSyncPosition) video.currentTime = hls.liveSyncPosition; video.play(); } }, "Jump to live");
  const syncToggle = h("div.toggle", {},
    h("button", { onclick: () => setInstant(false) }, "Synced to video"),
    h("button", { onclick: () => setInstant(true) }, "Instant"));
  const steerBox = h("div", { style: { display: "flex", flexDirection: "column", gap: "8px" } });
  const events = h("div", { style: { display: "flex", flexDirection: "column-reverse", gap: "8px" } });
  const empty = h("div.panel-empty", {}, "Waiting for the live game…");
  const pending = h("span.dim", { style: { fontSize: "12px" } });
  const queueBox = h("div.queue-mini");
  const arenaToggle = h("input", { type: "checkbox", onchange: async (e) => {
    await api("/api/settings", { method: "POST", body: { arena: e.target.checked } });
    toast(e.target.checked ? "Arena will fill the live slot when the queue is empty" : "Arena paused after the current game");
  } });

  mount(root, h("div.live-layout", {},
    h("div", {},
      header,
      h("div.video-wrap", {}, video, videoMsg),
      h("div.video-bar", {}, delayInfo, goLive, h("span.spacer"),
        h("label.check", {}, arenaToggle, "Arena fills idle time"), link("/launch", h("button.primary.small", {}, "Launch a match"))),
      h("div.card", { style: { marginTop: "12px" } }, h("h3", {}, "Queue"), queueBox)),
    h("div.card.panel", {},
      h("div.panel-head", {}, h("h2", {}, "LLM interaction"), pending, h("span.spacer"), syncToggle),
      h("div.panel-body", {}, steerBox, empty, events))));

  function setInstant(v) {
    instant = v;
    localStorage.setItem("melee.instant", v ? "1" : "0");
    syncToggle.children[0].classList.toggle("on", !v);
    syncToggle.children[1].classList.toggle("on", v);
  }
  setInstant(instant);

  // ---------------------------------------------------------------- video
  let hls = null;
  function startVideo() {
    if (signal.aborted) return;
    if (!Hls.isSupported()) {
      video.src = "/hls/index.m3u8"; // Safari: native HLS (no playingDate, so sync falls back to a fixed delay)
      return;
    }
    hls = new Hls({ lowLatencyMode: true, liveSyncDurationCount: 2, backBufferLength: 10, maxLiveSyncPlaybackRate: 1.1 });
    hls.loadSource("/hls/index.m3u8");
    hls.attachMedia(video);
    hls.on(Hls.Events.MANIFEST_PARSED, () => { videoMsg.textContent = ""; video.play().catch(() => {}); });
    hls.on(Hls.Events.ERROR, (_e, d) => {
      if (!d.fatal) return;
      videoMsg.textContent = "Stream unavailable, retrying…";
      hls.destroy();
      hls = null;
      setTimeout(startVideo, 3000);
    });
  }
  startVideo();
  signal.addEventListener("abort", () => { hls?.destroy(); video.removeAttribute("src"); });

  // Server time currently shown by the video, or null when the video isn't playing.
  function videoClock() {
    if (video.paused || video.readyState < 2) return null;
    if (hls?.playingDate) return hls.playingDate.getTime() / 1000;
    return serverNow() - (hls?.latency || 2.5);
  }
  function releaseClock() {
    if (instant) return Infinity;
    const t = videoClock();
    return t === null ? serverNow() - 2.0 : t; // no video: assume a typical HLS delay
  }

  // ---------------------------------------------------------------- events
  function enqueue(ts, apply) {
    const ev = { ts: ts || serverNow(), apply };
    let i = queue.length;
    while (i > 0 && queue[i - 1].ts > ev.ts) i--;
    queue.splice(i, 0, ev);
  }
  const tick = setInterval(() => {
    const t = releaseClock();
    while (queue.length && queue[0].ts <= t) queue.shift().apply();
    const v = videoClock();
    delayInfo.textContent = v ? `Video ${(serverNow() - v).toFixed(1)} s behind the game` : "Video not playing";
    pending.textContent = queue.length && !instant ? `${queue.length} pending until the video catches up` : "";
  }, 100);
  signal.addEventListener("abort", () => clearInterval(tick));

  function addEvent(el) {
    if (!el) return;
    empty.remove();
    events.append(el);
    while (events.children.length > MAX_EVENTS) events.firstChild.remove();
  }

  function renderStatus(s) {
    shownStatus = s;
    const key = s.source === "idle" ? "idle" : `${s.source}|${s.job_id}|${s.started}|${s.game}`;
    if (key !== gameKey) {
      gameKey = key;
      steerBox.replaceChildren();
      if (s.source !== "idle" && s.players) {
        addEvent(h("div.ev.sys", {}, h("b", {}, s.source === "job" ? `Job #${s.job_id}` : "Arena"),
          ` · ${s.players["1"].label} vs ${s.players["2"].label} · ${s.stage_name} · game ${s.game + 1}/${s.games}`));
        const quiet = Object.values(s.players).every((p) => p.kind === "cpu" || p.kind === "bot" || p.kind === "shine" || p.kind === "idle");
        if (quiet) addEvent(h("div.ev.sys", {}, "No LLM in this game: learned bots show their steer state above, CPUs show nothing."));
      }
    }
    for (const [port, st] of Object.entries(s.steer || {})) {
      const id = `steer-${port}`;
      const sig = JSON.stringify(st);
      const old = steerBox.querySelector(`#${id}`);
      if (old?.dataset.sig === sig) continue; // unchanged: keep the card (and its animation) as is
      const card = steerCard(port, st, s.players?.[port]);
      card.id = id;
      card.dataset.sig = sig;
      old ? old.replaceWith(card) : steerBox.append(card);
    }
    if (s.source === "idle" || !s.players) {
      mount(header, h("div.np-side", {}, h("div.np-name", {}, "Nothing on the live slot")),
        h("div.np-mid", {}, s.next || ""), h("div.np-side.right", {}, link("/launch", "Launch a match →")));
      if (!events.children.length) mount(empty, "Idle. Launch a match or turn the arena on.");
      return;
    }
    const side = (p, right) => {
      const pl = s.players[p];
      const pct = s.percent?.[p];
      const st = s.stocks?.[p];
      const color = p === "1" ? "var(--p1)" : "var(--p2)";
      const score = h("div.np-score", {}, h("span.np-pct", { style: { color } }, pct !== undefined ? `${Math.round(pct)}%` : "–"),
        st !== undefined ? stocks(st, color) : null);
      if (right) score.style.flexDirection = "row-reverse";
      return h(`div.np-side${right ? ".right" : ""}`, {},
        h("div.np-name", {}, h(`span.port.p${p}`, {}, `P${p}`), " ", pl.label, s.elo ? h("span.dim", {}, ` ${s.elo[p]}`) : null),
        h("div.np-char", {}, pl.char_name), score);
    };
    const phase = { starting: "loading Dolphin…", in_game: "in game", between: "between games", finished: "finished" }[s.phase] || s.phase;
    mount(header, side("1", false),
      h("div.np-mid", {}, h("div.vs", {}, "VS"), h("div", {}, s.stage_name),
        h("div", {}, `${s.mode} · ${s.source === "job" ? `job #${s.job_id}` : `arena game ${s.arena_game ?? ""}`}`),
        h("div", {}, s.games > 1 ? `game ${s.game + 1}/${s.games} · ` : "", phase, s.frame ? ` · ${fmt.frames(s.frame)}` : "")),
      side("2", true));
    if (s.phase === "finished" && s.error) addEvent(h("div.ev.sys.err", {}, `Stopped: ${s.error}`));
  }

  function connect() {
    const es = new EventSource("/api/live/events");
    es.addEventListener("hello", (e) => {
      offset = JSON.parse(e.data).server_time - Date.now() / 1000;
      queue = [];
      events.replaceChildren();
      gameKey = null;
    });
    es.addEventListener("status", (e) => {
      const s = JSON.parse(e.data);
      if (!shownStatus) return renderStatus(s); // first paint right away
      enqueue(s.updated, () => renderStatus(s));
    });
    es.addEventListener("log", (e) => {
      const { port, kind, rec } = JSON.parse(e.data);
      enqueue(rec.ts, () => addEvent(recordCard(rec, port, kind)));
    });
    signal.addEventListener("abort", () => es.close());
  }
  connect();

  // ---------------------------------------------------------------- queue
  every(4000, async () => {
    const { jobs, arena } = await api("/api/jobs?limit=5");
    arenaToggle.checked = arena === "on";
    const active = jobs.filter((j) => j.status === "running" || j.status === "queued");
    mount(queueBox, active.length ? h("ul", {}, active.map((j) => h("li", {},
      link(`/job/${j.id}`, `#${j.id}`), " ", h("span", { class: `badge ${j.status === "running" ? "live" : "warn"}` }, j.status), " ",
      `${j.label1} (${j.char1_name}) vs ${j.label2} (${j.char2_name})`, h("span.dim", {}, ` · ${j.mode} · ${j.lane}`))))
      : h("div.dim", {}, arena === "on" ? "Queue empty: the arena is playing." : "Queue empty."));
  }, signal);
}
