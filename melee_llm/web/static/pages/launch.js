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
  const submit = h("button.primary", { onclick: send }, "Queue match");
  const p1 = h("div.card.pcard.p1");
  const p2 = h("div.card.pcard.p2");
  const matchBox = h("div.card");
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
        argEl = h("span", {}, h("input", { value: s.arg ?? "", placeholder: k.arg.placeholder || "", list: listId, style: { width: "100%" },
          oninput: (e) => { s.arg = e.target.value; changed(); } }),
          k.arg.options ? h("datalist", { id: listId }, k.arg.options.map((o) => h("option", { value: o }))) : null);
      }
    }
    const allowed = allowedChars(p);
    if (!allowed.includes(s.char)) s.char = allowed[0] || "FOX";
    const charSel = h("select", { onchange: (e) => { s.char = e.target.value; changed(); } },
      allowed.map((c) => h("option", { value: c, selected: c === s.char }, charName[c] || c)));
    const argLabel = { cpu: "Level", llm_paused: "Model", llm_live: "Model", coach: "Coach model", hal: "Identity",
      phillip: "Model", mimic: "Checkpoint", faynt: "Variant", reyn: "Command" }[s.kind] || "Argument";
    mount(el, h("h2", {}, h(`span.port.p${p}`, {}, `P${p}`), "Player"),
      h("div.fields", {},
        h("label.field.wide", {}, "Player type", kindSel),
        argEl ? h("label.field", { class: k.arg.type === "text" ? "wide" : "" }, argLabel, argEl) : null,
        h("label.field", {}, "Character", charSel),
        k.options !== undefined ? h("label.field.wide", {}, "Options (key=value, comma separated)",
          h("input", { value: s.options ?? "", placeholder: k.options, oninput: (e) => { s.options = e.target.value; changed(); } })) : null),
      h("div.spec-preview", { id: `spec-${p}` }, spec(p)));
  }

  function matchCard() {
    const live = state.mode !== "fast";
    mount(matchBox, h("h2", {}, "Match"),
      h("div.modes", {}, cat.modes.map((m) => h(`div.mode${state.mode === m.id ? ".on" : ""}`, {
        onclick: () => { state.mode = m.id; renderAll(); } }, h("b", {}, m.id), h("span", {}, m.desc)))),
      h("div.match-fields", { style: { marginTop: "12px" } },
        h("label.field", {}, "Stage", h("select", { onchange: (e) => { state.stage = e.target.value; changed(); } },
          cat.stages.map((s) => h("option", { value: s.id, selected: s.id === state.stage }, s.name)))),
        h("label.field", {}, "Games", h("input", { type: "number", min: 1, max: 50, value: state.games,
          oninput: (e) => { state.games = +e.target.value || 1; changed(); } })),
        live ? h("label.check", {}, h("input", { type: "checkbox", checked: state.preempt,
          onchange: (e) => { state.preempt = e.target.checked; changed(); } }), "Start now (abort the running arena game)") : h("span"),
        h("div", { style: { textAlign: "right" } }, submit)),
      msgs);
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
    ], jobs, { empty: "No jobs yet." }));
  }

  mount(root, h("div.pagehead", {}, h("h1", {}, "Launch a match"),
    h("span.dim", {}, "Live jobs take display :99 in order; the arena fills the slot when the queue is empty. Fast jobs run headless, up to 4 at once.")),
  h("div.launch-grid", {}, p1, p2), h("div", { style: { marginTop: "16px" } }, matchBox),
  h("div.card", { style: { marginTop: "16px" } }, h("h2", {}, "Jobs"), jobsBox));
  renderAll();
  every(3000, refreshJobs, signal);
}
