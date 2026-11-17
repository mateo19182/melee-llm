// Frame-by-frame player for the simulator traces in clips.json (written by scripts/optimal_play_animations.py).
// One player shows one scene: its clips as tabs, or as the cells of a solved guess (scene.grid) with both mixes.
// A scene with a `setup` clip also offers the lead-in from the match start: a thinned recording (clip.frames says
// which match frame each row is) drawn on the whole stage and played fast.
// Each Fox is drawn in his true pose (action and animation frame) at the simulator's coordinates by Slippi Lab's
// character renderer (/slippilab-live.js, built from patches/slippilab.patch), with its shield bubble and reflector,
// on Final Destination. Reach ticks, hit bursts and labels are drawn here. The poses are not the game's hitboxes.

const SHINE = new Set([360, 361, 365, 366]), SHIELD = new Set([178, 179, 181, 182]);
const FOX = 1; // internal character id
// The renderer with Fox's animations loaded, or null: the Foxes are then plain capsules.
let lab;
const renderer = () => (lab ??= import("/slippilab-live.js")
  .then(async (m) => (m.drawFighter && await m.preload(FOX) ? m : null)).catch((e) => { console.error(e); return null; }));
const FONT = "Barlow, system-ui, sans-serif";

const el = (tag, cls, html) => {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (html != null) e.innerHTML = html;
  return e;
};

function inputText(b, sx, sy) {
  const parts = [..."RBXAZ"].filter((k) => b.includes(k));
  if (sy < 0) parts.push("↓"); if (sy > 0) parts.push("↑"); if (sx < 0) parts.push("←"); if (sx > 0) parts.push("→");
  return parts.join(" + ");
}

function inputMeaning(b, sx, sy) {
  const has = (k) => b.includes(k);
  if (has("B") && sy < 0) return "shine";
  if (has("R") && has("X")) return "jump";
  if (has("R") && has("A")) return "grab";
  if (has("R") && sy < 0) return "spotdodge";
  if (has("R") && sx) return "roll";
  if (has("R")) return "shield";
  if (has("A") && sy > 0) return "up smash";
  if (has("A")) return "jab";
  if (has("X")) return "jump";
  if (sx) return Math.abs(sx) < 50 ? "stick, gently" : "stick, hard";
  return "";
}

// What decided the clip: every frame on which someone's percent went up, and the frame someone left the stage unhit.
function eventsOf(clip, ledge) {
  const out = [];
  for (let i = 1; i < clip.rows.length; i++) for (const p of [0, 1]) {
    const now = clip.rows[i][p], was = clip.rows[i - 1][p], gain = Math.round((now[5] - was[5]) * 10) / 10;
    if (gain > 0) out.push({ i, p, text: `${gain}%`, hit: true });
    else if (Math.abs(now[0]) > ledge && Math.abs(was[0]) <= ledge && now[5] === 0) out.push({ i, p, text: "off the stage", off: true });
  }
  return out;
}

export function mountPlayer(root, scene, D, signal) {
  const names = D.names.map((n) => n.split(" ")[0]);
  const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
  let clip = scene.clips[0], events = [], i = 0, playing = false, timer = 0, fps = 8, auto = !reduced;
  let R = null;
  const viewOf = (clips) => {
    let lo = 1e9, hi = -1e9, top = 0;
    clips.forEach((c) => c.rows.forEach((r) => r.forEach((p) => { lo = Math.min(lo, p[0]); hi = Math.max(hi, p[0]); top = Math.max(top, p[1]); })));
    return { x0: lo - 9, x1: Math.max(hi + 7, D.ledge + 5), up: Math.max(20, top + 19) };
  };
  const all = scene.setup ? [...scene.clips, scene.setup] : scene.clips;
  // one view for the scene's clips, so switching between them does not move the picture; the lead-in has its own
  const views = new Map(scene.clips.map((c) => [c, viewOf(scene.clips)]));
  if (scene.setup) views.set(scene.setup, viewOf([scene.setup]));
  let view = views.get(clip);
  // The pose of an action that turns Fox around is drawn facing the way he faced when it began.
  all.forEach((c) => [0, 1].forEach((p) => {
    let began = 0;
    c.starts = c.starts || [];
    c.rows.forEach((r, k) => {
      const was = c.rows[k - 1]?.[p];
      if (!was || was[2] !== r[p][2] || r[p][3] < was[3]) began = r[p][4];
      (c.starts[k] ||= [])[p] = began ? 1 : -1;
    });
  }));
  const frameNo = (k) => clip.frames ? clip.frames[k] : k - clip.lead;

  root.classList.add("bp");
  const tabs = el("div", scene.grid ? "bp-grid" : "bp-tabs");
  tabs.setAttribute("role", "tablist");
  const tabBtns = [];
  const pick = (k) => () => { select(k); auto = false; play(true); };
  if (scene.grid) {
    const g = scene.grid;
    tabs.style.gridTemplateColumns = `auto repeat(${g.cols.length}, minmax(0, 1fr))`;
    tabs.append(el("div", "bp-corner", `<b>${g.value}</b>red's chance`));
    g.cols.forEach((c) => tabs.append(el("div", "bp-h bp-c2", `${c.label}<i>${c.p}%</i>`)));
    scene.clips.forEach((c, k) => {
      if (k % g.cols.length === 0) { const r = g.rows[k / g.cols.length]; tabs.append(el("div", "bp-h bp-row bp-c1", `${r.label}<i>${r.p}%</i>`)); }
      const b = el("button", `bp-cell ${c.value === 1 ? "v1" : c.value === 0 ? "v0" : "vm"}`, `<b>${c.tag}</b><span>red scores ${c.value}</span>`);
      b.onclick = pick(k); b.dataset.k = k; tabs.append(b); tabBtns.push(b);
    });
  } else if (scene.clips.length > 1) {
    scene.clips.forEach((c, k) => { const b = el("button", "small", c.title); b.onclick = pick(k); b.dataset.k = k; tabs.append(b); tabBtns.push(b); });
  }
  const caption = el("p", "bp-caption");
  const canvas = el("canvas"); canvas.setAttribute("role", "img");
  const beat = el("div", "bp-beat", '<div class="bp-frame"></div><div class="bp-note" aria-live="off"></div>');
  const hud = el("div", "bp-hud");
  const cards = [0, 1].map((p) => {
    const c = el("div", `bp-who bp-p${p + 1}`, `<div class="bp-name"><span>${D.names[p]}</span><span class="bp-pct"></span></div>
      <div class="bp-act"></div><div class="bp-in"><span class="bp-stick"><i></i></span><b></b><span></span></div><div class="bp-bar" title="shield health"><i></i></div>`);
    hud.append(c);
    return { pct: c.querySelector(".bp-pct"), act: c.querySelector(".bp-act"), dot: c.querySelector(".bp-stick i"),
      keys: c.querySelector(".bp-in b"), mean: c.querySelector(".bp-in span:last-child"), bar: c.querySelector(".bp-bar i") };
  });
  const ctl = el("div", "bp-ctl", `<button type="button" class="small ghost" aria-label="Previous frame">❘◀</button>
    <button type="button" class="small bp-play" aria-label="Play">▶</button><button type="button" class="small ghost" aria-label="Next frame">▶❘</button>
    <div class="bp-track"><input type="range" min="0" value="0" step="1" aria-label="Frame"></div>
    <select aria-label="Playback speed"><option value="4">4 fps</option><option value="8">8 fps</option><option value="20">20 fps</option><option value="60">60 fps</option></select>`);
  const [prevB, playB, nextB] = ctl.querySelectorAll("button");
  const range = ctl.querySelector("input"), track = ctl.querySelector(".bp-track"), speed = ctl.querySelector("select");
  if (tabBtns.length) root.append(tabs);
  if (scene.setup) {
    const last = scene.setup.frames.at(-1);
    const b = el("button", "bp-setup", `<b>▶ From the match start</b><span>how play gets to this position: ${last} frames, sped up</span>`);
    b.onclick = pick(scene.clips.length); b.dataset.k = scene.clips.length;
    root.append(b); tabBtns.push(b);
  }
  tabBtns.forEach((b) => { b.type = "button"; b.setAttribute("role", "tab"); });
  root.append(caption, canvas, beat, hud, ctl);
  const ctx = canvas.getContext("2d");

  function select(k) {
    clip = all[k]; view = views.get(clip); events = eventsOf(clip, D.ledge); i = 0;
    fps = clip.fps || 8; speed.value = fps;
    tabBtns.forEach((b) => { const on = +b.dataset.k === k; b.setAttribute("aria-selected", on); b.classList.toggle("on", on); });
    const bad = events.length > 0, setup = clip === scene.setup;
    const res = setup ? "" : bad ? events.map((e) => e.hit ? `${names[e.p]} takes ${e.text} on frame ${frameNo(e.i)}.`
      : `${names[e.p]} slides off the stage on frame ${frameNo(e.i)}.`).join(" ") : "Nobody is hit.";
    caption.innerHTML = (clip.caption ? clip.caption + " " : "") + `<span class="bp-result${bad ? " hit" : ""}">${res}</span>`;
    canvas.setAttribute("aria-label", `${clip.title}. ${clip.caption} ${res}`);
    range.max = clip.rows.length - 1;
    track.querySelectorAll(".bp-mk").forEach((m) => m.remove());
    const mark = (idx, cls) => { const m = el("span", "bp-mk " + cls); m.style.left = `calc(8px + (100% - 16px) * ${idx / (clip.rows.length - 1)})`; track.append(m); };
    if (clip.lead > 0) mark(clip.lead + 1, "");
    events.forEach((e) => mark(e.i, "hit"));
    render();
  }

  function size() {
    const w = canvas.clientWidth, s = Math.min(w / (view.x1 - view.x0), 300 / view.up), h = Math.round(view.up * s + 56), dpr = window.devicePixelRatio || 1;
    canvas.style.height = h + "px";
    if (canvas.width !== Math.round(w * dpr) || canvas.height !== Math.round(h * dpr)) { canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr); }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    return [w, h, s];
  }

  function draw() {
    const [W, H, s] = size();
    if (!W) return;
    const cs = getComputedStyle(document.documentElement), col = (n) => cs.getPropertyValue(n).trim();
    const C = { p: [col("--p1"), col("--p2")], hit: col("--warn"), stage: col("--title"), muted: col("--dim"), ink: col("--text"), card: col("--bg") };
    const base = H - 46;
    const x0 = view.x1 - W / s, X = (x) => (x - x0) * s, Y = (y) => base - y * s;
    const row = clip.rows[i];
    ctx.clearRect(0, 0, W, H);
    ctx.lineJoin = ctx.lineCap = "round";
    ctx.font = `600 11px ${FONT}`;

    // the stage: Final Destination's outline, or a slab between the two ledges
    const left = Math.max(0, X(-D.ledge)), right = X(D.ledge), fd = R?.STAGES.FINAL_DESTINATION.main;
    ctx.beginPath();
    if (fd) fd.forEach(([x, y]) => ctx.lineTo(X(x), Y(y))); else ctx.rect(left, base, right - left, 9);
    const body = ctx.createLinearGradient(0, base, 0, H);
    body.addColorStop(0, C.stage); body.addColorStop(1, "transparent");
    ctx.fillStyle = body; ctx.globalAlpha = .3; ctx.fill();
    ctx.globalAlpha = 1; ctx.strokeStyle = C.stage; ctx.lineWidth = 2;
    if (!fd) { ctx.beginPath(); ctx.moveTo(left, base + 9); ctx.lineTo(left, base); ctx.lineTo(right, base); ctx.lineTo(right, base + 9); }
    ctx.stroke();
    ctx.fillStyle = C.muted; ctx.textAlign = "right"; ctx.fillText("ledge", right - 4, base + 37); // under the reach labels

    // reach ticks, measured from red toward blue
    const dir = Math.sign(clip.rows[Math.max(0, clip.lead)][1][0] - clip.rows[Math.max(0, clip.lead)][0][0]) || 1;
    clip.marks.forEach(([d, text], k) => {
      const tx = X(row[0][0] + dir * d);
      ctx.strokeStyle = C.p[0]; ctx.fillStyle = C.p[0]; ctx.lineWidth = 2;
      ctx.beginPath(); ctx.moveTo(tx, base + 2); ctx.lineTo(tx, base + 11); ctx.stroke();
      ctx.textAlign = clip.marks.length === 1 ? "center" : k ? "left" : "right";
      ctx.fillText(text, tx + (clip.marks.length === 1 ? 0 : k ? -2 : 2), base + 23);
    });
    if (clip.marks.length) {
      ctx.globalAlpha = .5; ctx.lineWidth = 1; ctx.setLineDash([2, 3]);
      ctx.beginPath(); ctx.moveTo(X(row[0][0]), base + 6); ctx.lineTo(X(row[0][0] + dir * clip.marks.at(-1)[0]), base + 6); ctx.stroke();
      ctx.setLineDash([]); ctx.globalAlpha = 1;
    }

    const feet = (p) => Math.abs(p[0]) < D.ledge ? Math.max(0, p[1]) : p[1]; // the origin dips under the floor just before landing
    const clank = row[0][7] > 0 && row[1][7] > 0 && SHINE.has(row[0][2]) && SHINE.has(row[1][2]);
    const dpr = window.devicePixelRatio || 1;
    const world = () => ctx.setTransform(dpr * s, 0, 0, -dpr * s, -dpr * x0 * s, dpr * base); // simulator units, y up

    row.forEach((p, k) => {
      const [x, , act, af, facing, , shield, hitlag, inv] = p, y = feet(p), f = facing ? 1 : -1, c = C.p[k];
      const jx = hitlag ? ((i + k) % 2 ? 1.5 : -1.5) : 0, was = clip.rows[i - 1]?.[k];
      const fox = { x: x + jx / s, y, facing: f, facingAtStart: clip.starts[i][k], actionId: act, actionFrame: af, charId: FOX, color: c,
        outline: inv ? c : C.card, outlineWidth: 15 / s, alpha: inv ? .35 : 1, dash: inv ? [45 / s, 40 / s] : [], // dashed while intangible
        from: was && [was[0], feet(was)] };
      ctx.save(); world();
      if (R && SHINE.has(act)) { // the reflector, behind him; brighter on the frame it comes out and can hit
        const out = (act === 360 || act === 365) && af === 1;
        if (out) { ctx.shadowColor = "#8abce9"; ctx.shadowBlur = 10 * dpr; }
        R.drawShine(ctx, fox, "#8abce9", out ? 1 : .6);
      }
      const drawn = R?.drawFighter(ctx, fox);
      if (R && SHIELD.has(act)) R.drawShield(ctx, fox, shield, .4);
      ctx.restore();
      if (drawn) return;

      // no renderer, or no animation for this action: a capsule with a mark on the side he faces
      const w = 5, h = 10, cx = X(x) + jx, cy = Y(y + 5);
      ctx.strokeStyle = c; ctx.fillStyle = c;
      if (SHIELD.has(act) || SHINE.has(act)) {
        ctx.globalAlpha = .9; ctx.lineWidth = 1.5; ctx.beginPath(); ctx.arc(cx, cy, 6.2 * s, 0, 7); ctx.stroke(); ctx.globalAlpha = 1;
      }
      ctx.save(); ctx.translate(cx, Y(y));
      ctx.beginPath(); ctx.roundRect(-w * s / 2, -h * s, w * s, h * s, w * s / 2);
      ctx.globalAlpha = inv ? .22 : .88; ctx.fill(); ctx.globalAlpha = 1;
      ctx.lineWidth = 2; if (inv) ctx.setLineDash([4, 3.5]); ctx.stroke(); ctx.setLineDash([]);
      ctx.fillStyle = inv ? c : C.card;
      ctx.beginPath(); ctx.arc(f * w * s * .2, -h * s + w * s * .55, Math.max(1.6, .55 * s), 0, 7); ctx.fill();
      ctx.restore();
    });

    const burst = (bx, by, r, color) => {
      ctx.fillStyle = color; ctx.beginPath();
      for (let a = 0; a < 16; a++) { const rr = a % 2 ? r * .45 : r, t = a * Math.PI / 8 + i; ctx.lineTo(bx + rr * Math.cos(t), by + rr * Math.sin(t)); }
      ctx.closePath(); ctx.fill();
    };
    if (clank) {
      const mx = (X(row[0][0]) + X(row[1][0])) / 2, my = Y(7);
      burst(mx, my, 2.6 * s, C.ink);
      ctx.fillStyle = C.ink; ctx.textAlign = "center"; ctx.font = `700 13px ${FONT}`; ctx.fillText("clank · 0%", mx, Y(17));
    }
    events.forEach((e) => {
      if (i < e.i || i > e.i + 12) return;
      const v = row[e.p], bx = Math.min(W - 44, X(v[0])), by = Y(feet(v) + 7);
      if (e.hit && v[7] > 0) burst(bx, by, 3 * s, C.hit);
      ctx.fillStyle = C.hit; ctx.textAlign = "center"; ctx.font = `800 15px ${FONT}`;
      ctx.fillText(e.text, bx, Y(Math.max(0, feet(v)) + 16) - (i - e.i) * 1.5);
    });
  }

  function render() {
    const n = frameNo(i), row = clip.rows[i];
    beat.firstChild.innerHTML = (n >= 1 ? `Frame ${n}` : clip.lead > 0 ? "Lead-in" : "Start") +
      `<small>gap ${Math.abs(row[1][0] - row[0][0]).toFixed(2)}</small>`;
    let note = "";
    for (const [f, t] of clip.notes) if (f <= n) note = t;
    beat.lastChild.textContent = note;
    row.forEach((p, k) => {
      const c = cards[k], keys = i ? inputText(p[9], p[10], p[11]) : "";
      c.pct.textContent = p[5] + "%"; c.pct.classList.toggle("on", p[5] > 0);
      c.act.textContent = D.actions[p[2]];
      c.dot.style.transform = `translate(${p[10] / 80 * 5}px, ${-p[11] / 80 * 5}px)`;
      c.keys.textContent = keys || "—"; c.mean.textContent = keys ? inputMeaning(p[9], p[10], p[11]) : "no input";
      c.bar.style.width = (p[6] / 60 * 100) + "%";
    });
    range.value = i;
    draw();
  }

  function play(on) {
    playing = on; clearTimeout(timer);
    playB.textContent = on ? "❚❚" : "▶"; playB.setAttribute("aria-label", on ? "Pause" : "Play");
    if (on) tick();
  }
  function tick() {
    timer = setTimeout(() => {
      if (!playing) return;
      i = i >= clip.rows.length - 1 ? 0 : i + 1; render(); tick();
    }, i >= clip.rows.length - 1 ? 1600 : 1000 / fps);
  }
  const jump = (k) => { auto = false; play(false); i = Math.max(0, Math.min(clip.rows.length - 1, k)); render(); };
  playB.onclick = () => { auto = false; if (!playing && i >= clip.rows.length - 1) i = 0; play(!playing); if (playing) render(); };
  prevB.onclick = () => jump(i - 1); nextB.onclick = () => jump(i + 1);
  range.oninput = () => jump(+range.value);
  speed.onchange = () => { fps = +speed.value; };
  renderer().then((m) => { if (m && !signal?.aborted) { R = m; draw(); } });
  const resize = new ResizeObserver(draw);
  resize.observe(canvas);
  const seen = new IntersectionObserver((es) => es.forEach((e) => { // play while on screen until the reader takes over
    if (e.isIntersecting && auto && !playing) play(true);
    else if (!e.isIntersecting && playing) play(false);
  }), { threshold: .55 });
  seen.observe(canvas);
  signal?.addEventListener("abort", () => { play(false); resize.disconnect(); seen.disconnect(); });
  select(0);
}
