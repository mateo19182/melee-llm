// Live page: LL-HLS video of display :99, a broadcast scorebug and the decision feed.
//
// Sync: every SSE event carries the server wall-clock time it happened (`ts`). mediamtx stamps HLS segments
// with EXT-X-PROGRAM-DATE-TIME from the same clock, so hls.playingDate is "server time currently on screen".
// Events wait in a queue until the video reaches them; "instant" shows them on arrival.
import Hls from "../vendor/hls.min.mjs";
import { recordCard, steerCard } from "../decisions.js";
import { api, emptyState, every, fmt, h, link, mount, statusBadge, stocks, toast } from "../lib.js";

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
  const scorebug = h("div.scorebug", {}, h("div.sb-idle", {}, h("span.dim", {}, "Connecting…")));
  const video = h("video", { muted: true, autoplay: true, playsInline: true, disablePictureInPicture: true });
  const videoMsg = h("div.video-msg", {}, "Starting stream…");
  const delayInfo = h("span.lag", {}, "");
  const jumpLive = () => { if (hls?.liveSyncPosition) video.currentTime = hls.liveSyncPosition; video.play().catch(() => {}); };
  const playBtn = h("button.vp-btn", { title: "Play / pause (space)", onclick: () => (video.paused ? video.play().catch(() => {}) : video.pause()) });
  const liveBtn = h("button.vp-live", { title: "Jump to live", onclick: jumpLive }, h("span.vp-dot"), "Live");
  const fsBtn = h("button.vp-btn", { title: "Fullscreen (f)", onclick: () => toggleFullscreen() });
  const videoWrap = h("div.video-wrap", { tabIndex: 0 },
    video, videoMsg,
    h("div.vp-bar", {}, playBtn, liveBtn, delayInfo, h("span.spacer"), fsBtn));
  const syncToggle = h("div.toggle", {},
    h("button", { onclick: () => setInstant(false), title: "Hold each decision until the video shows that moment" }, "Synced"),
    h("button", { onclick: () => setInstant(true), title: "Show decisions as they arrive, ahead of the video" }, "Instant"));
  const steerBox = h("div.steer-box");
  const events = h("div.feed");
  const empty = h("div.panel-empty", {}, "Waiting for the live game…");
  const pending = h("div.panel-sub");
  const queueBox = h("div");
  const arenaToggle = h("input", { type: "checkbox", onchange: async (e) => {
    await api("/api/settings", { method: "POST", body: { arena: e.target.checked } });
    toast(e.target.checked ? "Arena will fill the live slot when the queue is empty" : "Arena paused after the current game");
  } });

  mount(root, h("div.live-layout", {},
    h("div.live-main", {},
      scorebug,
      videoWrap,
      h("div.video-bar", {}, h("span.spacer"),
        h("label.check", {}, arenaToggle, "Arena fills idle time"), link("/launch", h("button.primary.small", {}, "Launch a match"))),
      h("div.queue-strip", {}, h("h3", {}, "Up next"), queueBox)),
    h("div.card.panel", {},
      h("div.panel-head", {}, h("h2", {}, "Decisions"), h("span.spacer"), syncToggle, pending),
      h("div.panel-body", {}, steerBox, empty, events))));

  function setInstant(v) {
    instant = v;
    localStorage.setItem("melee.instant", v ? "1" : "0");
    syncToggle.children[0].classList.toggle("on", !v);
    syncToggle.children[1].classList.toggle("on", v);
  }
  setInstant(instant);

  // ---------------------------------------------------------------- video
  const ICON = {
    play: '<svg viewBox="0 0 24 24"><path d="M7 4.5v15l13-7.5z"/></svg>',
    pause: '<svg viewBox="0 0 24 24"><path d="M6 4h4.5v16H6zM13.5 4H18v16h-4.5z"/></svg>',
    full: '<svg viewBox="0 0 24 24"><path d="M4 9V4h5v2H6v3zm11-5h5v5h-2V6h-3zM6 15v3h3v2H4v-5zm12 0h2v5h-5v-2h3z"/></svg>',
    exit: '<svg viewBox="0 0 24 24"><path d="M7 4h2v5H4V7h3zm8 0h2v3h3v2h-5zM4 15h5v5H7v-3H4zm11 0h5v2h-3v3h-2z"/></svg>',
  };
  const syncControls = () => {
    playBtn.innerHTML = video.paused ? ICON.play : ICON.pause;
    fsBtn.innerHTML = document.fullscreenElement === videoWrap ? ICON.exit : ICON.full;
    videoWrap.classList.toggle("paused", video.paused);
  };
  for (const ev of ["play", "pause", "playing"]) video.addEventListener(ev, syncControls);
  document.addEventListener("fullscreenchange", syncControls, { signal });
  syncControls();
  const toggleFullscreen = () => (document.fullscreenElement ? document.exitFullscreen() : videoWrap.requestFullscreen()).catch(() => {});
  video.addEventListener("click", () => playBtn.click());
  video.addEventListener("dblclick", toggleFullscreen);
  videoWrap.addEventListener("keydown", (e) => {
    if (e.key === " " || e.key === "k") { e.preventDefault(); playBtn.click(); }
    else if (e.key === "f") toggleFullscreen();
  });
  // Controls fade out while the mouse rests on a playing video.
  let idleTimer = 0;
  const wake = () => {
    videoWrap.classList.add("active");
    clearTimeout(idleTimer);
    idleTimer = setTimeout(() => videoWrap.classList.remove("active"), 2500);
  };
  videoWrap.addEventListener("mousemove", wake);
  videoWrap.addEventListener("mouseleave", () => { clearTimeout(idleTimer); videoWrap.classList.remove("active"); });

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
    const lag = v ? serverNow() - v : null;
    delayInfo.textContent = lag !== null ? `${lag.toFixed(1)} s behind the game` : "";
    liveBtn.classList.toggle("behind", lag === null || lag > (hls?.targetLatency ?? 2) + 1.5);
    pending.textContent = queue.length && !instant ? `${queue.length} waiting for the video to catch up` : instant ? "Instant: entries ahead of the video are dimmed" : "";
    markOnScreen(v);
  }, 100);
  signal.addEventListener("abort", () => clearInterval(tick));

  // Entries whose moment the video has reached; per port, the newest of them is what's acting on screen now.
  let shown = [];
  function addEvent(el, ts, port) {
    if (!el) return;
    empty.remove();
    events.append(el);
    if (ts && port && !el.classList.contains("sys")) shown.push({ el, ts, port });
    while (events.children.length > MAX_EVENTS) events.firstChild.remove();
    if (shown.length > MAX_EVENTS) shown = shown.filter((x) => x.el.isConnected);
  }
  function markOnScreen(v) {
    const newest = {};
    for (const x of shown) {
      const reached = v !== null && x.ts <= v;
      x.el.classList.toggle("ahead", v !== null && !reached);
      if (reached && (!newest[x.port] || x.ts >= newest[x.port].ts)) newest[x.port] = x;
    }
    const on = new Set(Object.values(newest).map((x) => x.el));
    for (const x of shown) x.el.classList.toggle("onscreen", on.has(x.el));
  }

  function renderStatus(s) {
    shownStatus = s;
    const key = s.source === "idle" ? "idle" : `${s.source}|${s.job_id}|${s.started}|${s.game}`;
    if (key !== gameKey) {
      gameKey = key;
      steerBox.replaceChildren();
      if (s.source !== "idle" && s.players) {
        addEvent(h("div.ev.sys.divider", {}, `${s.source === "job" ? `Job #${s.job_id}` : "Arena"} · ${s.players["1"].label} vs ${s.players["2"].label} · game ${s.game + 1}/${s.games}`));
        const quiet = Object.values(s.players).every((p) => p.kind === "cpu" || p.kind === "bot" || p.kind === "shine" || p.kind === "idle");
        if (quiet) addEvent(h("div.ev.sys", {}, "No LLM in this game. Learned bots show their steer state above; CPUs show nothing."));
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
      videoWrap.classList.remove("loading");
      mount(scorebug, h("div.sb-idle", {}, h("div", {}, h("b", {}, "Nothing on the live slot"), s.next ? h("div.dim", {}, s.next) : null),
        link("/launch", h("button.primary.small", {}, "Launch a match"))));
      if (!events.children.length) mount(empty, emptyState("Idle", "Launch a match, or turn the arena on to fill the slot."));
      return;
    }
    const side = (p) => {
      const pl = s.players[p];
      const pct = s.percent?.[p];
      const st = s.stocks?.[p];
      const color = p === "1" ? "var(--p1)" : "var(--p2)";
      return h(`div.sb-side.p${p}`, {},
        h("div.sb-who", {}, h("div.sb-name", { title: pl.spec || "" }, pl.label),
          h("div.sb-sub", {}, pl.char_name, s.elo ? h("span.elo", {}, ` · ${s.elo[p]} Elo`) : null)),
        h("div.sb-score", {}, h("div.sb-pct", {}, pct !== undefined ? [String(Math.round(pct)), h("small", {}, "%")] : "–"),
          st !== undefined ? stocks(st, color) : null));
    };
    videoWrap.classList.toggle("loading", s.phase === "starting");
    const phase = { starting: "loading Dolphin", in_game: s.frame ? fmt.frames(s.frame) : "in game", between: "between games", finished: "finished" }[s.phase] || s.phase;
    mount(scorebug, side("1"),
      h("div.sb-mid", {},
        h("div.sb-game", {}, `Game ${s.game + 1}`, s.games > 1 ? h("span.of", {}, ` / ${s.games}`) : null),
        h("div.sb-stage", {}, s.stage_name),
        h("div.sb-phase", {}, `${s.mode} · ${s.source === "job" ? `job #${s.job_id}` : `arena #${s.arena_game ?? ""}`} · ${phase}`)),
      side("2"));
    if (s.phase === "finished" && s.error) addEvent(h("div.ev.sys.err", {}, `Stopped: ${s.error}`));
  }

  function connect() {
    const es = new EventSource("/api/live/events");
    es.addEventListener("hello", (e) => {
      offset = JSON.parse(e.data).server_time - Date.now() / 1000;
      queue = [];
      shown = [];
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
      enqueue(rec.ts, () => addEvent(recordCard(rec, port, kind), rec.ts, port));
    });
    signal.addEventListener("abort", () => es.close());
  }
  connect();

  // ---------------------------------------------------------------- queue
  every(4000, async () => {
    const { jobs, arena } = await api("/api/jobs?limit=5");
    arenaToggle.checked = arena === "on";
    const active = jobs.filter((j) => j.status === "running" || j.status === "queued");
    mount(queueBox, active.length ? active.map((j) => h("div.queue-item", {},
      link(`/job/${j.id}`, `#${j.id}`), statusBadge(j.status),
      h("span", {}, h("span.port.p1", {}, "P1"), ` ${j.label1} `, h("span.dim", {}, j.char1_name), h("span.faint", {}, "  vs  "),
        h("span.port.p2", {}, "P2"), ` ${j.label2} `, h("span.dim", {}, j.char2_name)),
      h("span.spacer"), h("span.dim", {}, `${j.mode}${j.lane === "headless" ? " · headless" : ""}`)))
      : h("div.dim", {}, arena === "on" ? "Queue empty. The arena is playing." : "Queue empty."));
  }, signal);
}
