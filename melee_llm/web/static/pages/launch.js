// Match launcher and the job list (queued, running, finished; cancel).
import { navigate } from "../app.js";
import { api, every, fmt, h, link, mount, resultText, statusBadge, table, toast } from "../lib.js";

const STORE = "melee.launch";

export default async function launch(root, _params, signal) {
  const cat = await api("/api/catalog");
  const kinds = Object.fromEntries(cat.kinds.map((k) => [k.kind, k]));
  let saved = null;
  try { saved = JSON.parse(localStorage.getItem(STORE) || "null"); } catch { /* ignore */ }
  if (saved && !(kinds[saved.players?.[1]?.kind] && kinds[saved.players?.[2]?.kind])) saved = null;
  const state = saved || {
    players: { 1: { kind: "llm_paused", arg: kinds.llm_paused.arg.default, options: "", char: "FOX" },
               2: { kind: "cpu", arg: "5", options: "", char: "FALCO" } },
    stage: "BATTLEFIELD", mode: "paused", games: 1, preempt: false,
  };

  const spec = (p) => {
    const s = state.players[p];
    const k = kinds[s.kind];
    if (!k) return s.kind;
    const arg = (s.arg ?? "").trim();
    const opts = k.options !== undefined ? (s.options ?? "").trim().replace(/^,|,$/g, "") : "";
    if (!arg && !opts) return s.kind;
    return `${s.kind}:${arg}${opts ? "," + opts : ""}`;
  };

  function allowedChars(p) {
    const s = state.players[p];
    if (s.kind === "phillip") return cat.constraints.phillip[s.arg || "gm"] || [];
    if (s.kind === "mimic") return s.arg ? [cat.constraints.mimic[s.arg]] : [...new Set(Object.values(cat.constraints.mimic))];
    return cat.characters.map((c) => c.id);
  }
  const charName = Object.fromEntries(cat.characters.map((c) => [c.id, c.name]));

  const msgs = h("div.msgs");
  const submit = h("button.primary.big", { onclick: send }, "Queue match");
  const p1 = h("div.card.pcard.p1");
  const p2 = h("div.card.pcard.p2");
  const matchBox = h("div.card.match-card");
  const jobsBox = h("div");

  function playerCard(p) {
    const s = state.players[p];
    const k = kinds[s.kind];
    const el = p === 1 ? p1 : p2;
    const kindSel = h("select", { onchange: (e) => {
      const nk = kinds[e.target.value];
      Object.assign(s, { kind: nk.kind, arg: nk.arg?.default ?? "", options: "" });
      if (nk.mode && state.mode === "lockstep") state.mode = nk.mode;
      renderAll();
    } }, cat.kinds.map((x) => h("option", { value: x.kind, selected: x.kind === s.kind }, x.label)));
    let argEl = null;
    if (k.arg) {
      if (k.arg.type === "select") {
        argEl = h("select", { onchange: (e) => { s.arg = e.target.value; renderAll(); } },
          k.arg.options.map((o) => h("option", { value: o, selected: o === s.arg }, o || `(${k.arg.blank || "default"})`)));
      } else {
        const listId = `opts-${p}-${s.kind}`;
        argEl = h("span", { style: { display: "flex" } }, h("input", { value: s.arg ?? "", placeholder: k.arg.placeholder || "", list: listId, style: { width: "100%" },
          oninput: (e) => { s.arg = e.target.value; changed(); } }),
          k.arg.options ? h("datalist", { id: listId }, k.arg.options.map((o) => h("option", { value: o }))) : null);
      }
    }
    const allowed = allowedChars(p);
    if (!allowed.includes(s.char)) s.char = allowed[0] || "FOX";
    const charTiles = h("div.tiles", { role: "radiogroup", "aria-label": `P${p} character` }, cat.characters.map((c) => {
      const ok = allowed.includes(c.id);
      return h(`button.tile${c.id === s.char ? ".on" : ""}${ok ? "" : ".off"}`, { type: "button", disabled: !ok, title: ok ? c.name : `${c.name}: not available for this player`,
        onclick: () => { s.char = c.id; renderAll(); } }, c.name);
    }));
    const argLabel = { cpu: "Level", llm_paused: "Model", llm_live: "Model", coach: "Coach model", hal: "Identity",
      phillip: "Model", mimic: "Checkpoint", faynt: "Variant", reyn: "Command" }[s.kind] || "Argument";
    const who = [k.label.replace(/ \(.*\)$/, ""), s.arg ? (s.kind === "cpu" ? `level ${s.arg}` : s.arg) : null].filter(Boolean).join(" · ");
    mount(el,
      h("div.pc-head", {}, h("div.pc-port", {}, `P${p}`),
        h("div.pc-title", {}, h("div.pc-char", {}, charName[s.char] || s.char), h("div.pc-kind", { title: k.label }, who))),
      h("div.pc-body", {},
        h("div.fields", {},
          h("label.field.wide", {}, "Player", kindSel),
          argEl ? h("label.field", { class: k.arg.type === "text" || !k.options ? "wide" : "" }, argLabel, argEl) : null,
          k.options !== undefined ? h("label.field", { class: k.arg?.type === "text" ? "wide" : "" }, "Options",
            h("input", { value: s.options ?? "", placeholder: k.options, title: "key=value, comma separated", oninput: (e) => { s.options = e.target.value; changed(); } })) : null),
        h("div", {}, h("h3", { style: { marginBottom: "8px" } }, "Character"), charTiles),
        h("div.spec-preview", { id: `spec-${p}` }, spec(p))));
  }

  function matchCard() {
    const live = state.mode !== "fast";
    mount(matchBox,
      h("div.match-grid", {},
        h("div", {}, h("h3", {}, "Stage"), h("div.tiles.stage-tiles", {}, cat.stages.map((st) =>
          h(`button.tile${st.id === state.stage ? ".on" : ""}`, { type: "button", onclick: () => { state.stage = st.id; renderAll(); } }, st.name))),
          h("div.launch-foot", {},
            h("label.field", {}, "Games", h("input", { type: "number", min: 1, max: 50, value: state.games,
              oninput: (e) => { state.games = +e.target.value || 1; changed(); } })),
            live ? h("label.check", { style: { paddingBottom: "9px" } }, h("input", { type: "checkbox", checked: state.preempt,
              onchange: (e) => { state.preempt = e.target.checked; changed(); } }), "Start now (abort the running arena game)") : null,
            h("span.spacer"), submit, msgs)),
        h("div", {}, h("h3", {}, "Mode"), h("div.modes", {}, cat.modes.map((m) => h(`div.mode${state.mode === m.id ? ".on" : ""}`, {
          onclick: () => { state.mode = m.id; renderAll(); } }, h("b", {}, m.id), h("span", {}, m.desc)))))));
  }

  function renderAll() {
    playerCard(1);
    playerCard(2);
    matchCard();
    changed();
  }

  const body = () => ({ p1: spec(1), p2: spec(2), char1: state.players[1].char, char2: state.players[2].char,
    stage: state.stage, mode: state.mode, games: state.games, preempt: state.preempt });

  let timer = null;
  function changed() {
    localStorage.setItem(STORE, JSON.stringify(state));
    for (const p of [1, 2]) { const el = document.getElementById(`spec-${p}`); if (el) el.textContent = spec(p); }
    clearTimeout(timer);
    timer = setTimeout(async () => {
      const r = await api("/api/jobs", { method: "POST", body: { ...body(), dry_run: true }, allowError: true });
      showMsgs(r.data);
    }, 250);
  }

  function showMsgs(d) {
    mount(msgs, (d.errors || []).map((e) => h("div.e", {}, "✕ ", e)), (d.warnings || []).map((w) => h("div.w", {}, "! ", w)));
    submit.disabled = !!(d.errors && d.errors.length);
  }

  async function send() {
    submit.disabled = true;
    const r = await api("/api/jobs", { method: "POST", body: body(), allowError: true });
    submit.disabled = false;
    if (!r.ok) return showMsgs(r.data);
    toast(`Queued job #${r.data.job.id}${r.data.job.lane === "live" ? " on the live slot" : " (headless)"}`, "ok");
    if (r.data.job.lane === "live") navigate("/live");
    else refreshJobs();
  }

  async function cancel(j) {
    await api(`/api/jobs/${j.id}/cancel`, { method: "POST" });
    toast(`Cancelling job #${j.id}`);
    refreshJobs();
  }

  async function refreshJobs() {
    const { jobs } = await api("/api/jobs?limit=60");
    mount(jobsBox, table([
      { label: "#", render: (j) => link(`/job/${j.id}`, `#${j.id}`) },
      { label: "Status", render: (j) => statusBadge(j.status) },
      { label: "Match", render: (j) => h("span", {}, h("span.port.p1", {}, "P1"), ` ${j.label1} (${j.char1_name}) `, h("span.dim", {}, "vs "),
        h("span.port.p2", {}, "P2"), ` ${j.label2} (${j.char2_name})`) },
      { label: "Stage", render: (j) => j.stage_name },
      { label: "Mode", render: (j) => `${j.mode}${j.lane === "headless" ? " (headless)" : ""}` },
      { label: "Games", cls: "num", render: (j) => `${j.results.length}/${j.games}` },
      { label: "Result", render: (j) => j.results.length === 1 ? resultText(j.results[0])
        : j.results.length ? `P1 ${j.results.filter((r) => r.winner === 1).length} – ${j.results.filter((r) => r.winner === 2).length} P2` : "–" },
      { label: "LLM tokens", render: (j) => j.tokens ? h("span", { title: fmt.tokens(j.tokens) },
        `${fmt.k(j.tokens.prompt + j.tokens.completion)}${j.tokens.est_usd !== null ? ` · ~${fmt.usd(j.tokens.est_usd)}` : ""}`) : "–" },
      { label: "When", render: (j) => j.status === "queued" ? `queued ${fmt.ago(j.created)}`
        : j.finished ? `${fmt.ago(j.finished)} · ${fmt.secs(j.finished - j.started)}` : j.started ? `running ${fmt.secs(Date.now() / 1000 - j.started)}` : "–" },
      { label: "", render: (j) => (j.status === "queued" || j.status === "running")
        ? h("button.small.danger", { onclick: (e) => { e.stopPropagation(); cancel(j); }, disabled: !!j.cancel }, j.cancel ? "cancelling…" : "Cancel")
        : j.error ? h("span.dim", { title: j.error }, "error ⓘ") : "" },
    ], jobs, { empty: "No jobs yet. Queue one above." }));
  }

  mount(root, h("div.pagehead", {}, h("h1", {}, "Launch a match"),
    h("div.lede", {}, "Live jobs take display :99 in order; the arena fills the slot when the queue is empty. Fast jobs run headless, up to 4 at once.")),
  h("div.launch-grid", {}, p1, h("div.vs-mark", {}, "VS"), p2), matchBox,
  h("div.section-title", {}, h("h2", {}, "Queue & history")), h("div.card", {}, jobsBox));
  renderAll();
  every(3000, refreshJobs, signal);
}
