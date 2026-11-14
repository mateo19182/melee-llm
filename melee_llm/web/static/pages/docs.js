// Docs: docs/*.md rendered by the server (melee_llm/web/docs.py), with a doc list, search, a table of contents,
// scrollspy and copy-link heading anchors.
import { api, fmt, h, mount } from "../lib.js";

export default async function docs(root, { name = "research", query }, signal) {
  const [list, doc] = await Promise.all([api("/api/docs"), api(`/api/docs/${name}`)]);
  if (signal.aborted) return;
  document.title = `${doc.title} · Melee × LLM`;
  signal.addEventListener("abort", () => { document.title = "Melee × LLM"; });

  const article = h("article.prose");
  article.innerHTML = doc.html;
  enhance(article);
  anchors(article);
  const q = query.get("q");
  if (q) highlight(article, q);

  const toc = h("nav.doc-toc", {}, h("div.doc-side-label", {}, "On this page"),
    doc.toc.map((t) => h(`a.l${t.level}`, { href: `#${t.id}`, "data-id": t.id }, t.text)));
  const words = article.textContent.split(/\s+/).length;
  const sources = new Set([...article.querySelectorAll("a[target=_blank]")].map((a) => a.href)).size;

  mount(root, h("div.doc-layout", {},
    h("aside.doc-side", {},
      searchBox(toc, signal, q),
      h("div.doc-side-label", {}, "Docs"),
      h("nav.doc-list", {}, list.map((d) => h("a", { href: `/docs/${d.name}`, "data-link": "", class: d.name === name ? "on" : null }, d.title))),
      toc),
    h("div.doc-main", {},
      h("header.doc-hero", {},
        h("div.doc-kicker", {}, `docs/${name}.md`),
        h("h1", {}, doc.title),
        h("div.doc-meta", {},
          h("span", {}, `Updated ${fmt.time(doc.updated)}`),
          h("span", {}, `${Math.max(1, Math.round(words / 230))} min read`),
          sources ? h("span", {}, `${sources} sources`) : null)),
      article)));

  scrollspy(article, toc, signal);
  const target = location.hash ? document.getElementById(decodeURIComponent(location.hash.slice(1))) : article.querySelector("mark");
  target?.scrollIntoView({ block: target.tagName === "MARK" ? "center" : "start" });
}

// Search across every doc; results replace the table of contents while a query is typed. "/" focuses, Esc clears.
function searchBox(toc, signal, initial) {
  const input = h("input.doc-search", { type: "search", placeholder: "Search docs", value: initial || "", "aria-label": "Search docs" });
  const results = h("div.doc-results");
  let timer, seq = 0, hits = [];
  // The router re-renders on popstate; importing app.js here would load a second copy (it is served versioned).
  const go = (hit) => {
    history.pushState(null, "", `/docs/${hit.doc}?q=${encodeURIComponent(input.value.trim())}${hit.id ? `#${hit.id}` : ""}`);
    dispatchEvent(new PopStateEvent("popstate"));
  };
  const run = async () => {
    const q = input.value.trim(), mine = ++seq;
    toc.hidden = !!q;
    if (!q) return mount(results);
    hits = await api(`/api/docs/search?q=${encodeURIComponent(q)}`);
    if (mine !== seq || signal.aborted) return;
    mount(results, h("div.doc-side-label", {}, hits.length ? `${hits.length} result${hits.length > 1 ? "s" : ""}` : "No results"),
      hits.map((x) => h("a.doc-hit", { href: `/docs/${x.doc}${x.id ? `#${x.id}` : ""}`, onclick: (e) => { e.preventDefault(); go(x); } },
        h("div.doc-hit-head", {}, x.heading, h("span", {}, x.doc_title)),
        h("div.doc-hit-snip", {}, mark(x.snippet, q)))));
  };
  input.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(run, 150); });
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && hits[0]) go(hits[0]);
    if (e.key === "Escape") { input.value = ""; run(); input.blur(); }
  });
  const onKey = (e) => {
    if (e.key === "/" && !/^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement?.tagName)) { e.preventDefault(); input.focus(); input.select(); }
  };
  document.addEventListener("keydown", onKey);
  signal.addEventListener("abort", () => { document.removeEventListener("keydown", onKey); clearTimeout(timer); });
  if (initial) run();
  return h("div.doc-search-wrap", {}, input, h("kbd", {}, "/"), results);
}

const escapeRe = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

// Text with every query word wrapped in <mark>.
function mark(text, q) {
  const words = q.split(/\s+/).filter(Boolean).map(escapeRe);
  if (!words.length) return text;
  return text.split(new RegExp(`(${words.join("|")})`, "gi")).map((part, i) => (i % 2 ? h("mark", {}, part) : part));
}

function highlight(article, q) {
  const walker = document.createTreeWalker(article, NodeFilter.SHOW_TEXT);
  const re = new RegExp(q.split(/\s+/).filter(Boolean).map(escapeRe).join("|"), "i");
  const nodes = [];
  while (walker.nextNode()) if (re.test(walker.currentNode.data)) nodes.push(walker.currentNode);
  for (const n of nodes) n.replaceWith(...[mark(n.data, q)].flat());
}

// A "#" after each h2/h3: click copies the section's URL and puts it in the address bar.
function anchors(article) {
  for (const hd of article.querySelectorAll("h2[id], h3[id]")) {
    const a = h("a.doc-anchor", { href: `#${hd.id}`, title: "Copy link to this section", "aria-label": "Copy link to this section" }, "#");
    a.addEventListener("click", async (e) => {
      e.preventDefault();
      const url = `${location.origin}${location.pathname}#${hd.id}`;
      history.replaceState(null, "", url);
      hd.scrollIntoView({ behavior: "smooth" });
      try { await navigator.clipboard.writeText(url); a.dataset.copied = ""; setTimeout(() => delete a.dataset.copied, 1400); } catch { /* insecure context */ }
    });
    hd.append(a);
  }
}

function enhance(article) {
  article.querySelector("h1")?.remove(); // shown in the hero
  // The first paragraph is the lede.
  const first = article.firstElementChild;
  if (first?.tagName === "P") first.classList.add("lede");

  for (const s of article.querySelectorAll("strong")) {
    const m = s.textContent.match(/^\[(unverified[^\]]*)\]$/i);
    if (m) s.replaceWith(h("span.badge.warn", { title: "No primary source found" }, m[1]));
  }
  const walker = document.createTreeWalker(article, NodeFilter.SHOW_TEXT);
  const hits = [];
  while (walker.nextNode()) if (/\[unverified/i.test(walker.currentNode.data)) hits.push(walker.currentNode);
  for (const node of hits) {
    node.replaceWith(...node.data.split(/\[(unverified[^\]]*)\]/i)
      .map((part, i) => (i % 2 ? h("span.badge.warn", { title: "No primary source found" }, part) : part)).filter(Boolean));
  }
  for (const t of article.querySelectorAll("table")) {
    const head = [...t.querySelectorAll("thead th")].map((th) => th.textContent.trim().toLowerCase());
    const rows = [...t.querySelectorAll("tbody tr")].map((tr) => [...tr.children]);
    if (head[0] === "year") t.replaceWith(timeline(article, rows));
    else if (head[0] === "person") t.replaceWith(people(rows));
    else t.replaceWith(h(`div.table-wrap.doc-table${head[0] === "date" ? ".dated" : ""}`, {}, t.cloneNode(true)));
  }
}

// "Year | Bot | Author | Technique" → a vertical timeline whose entries jump to the bot's section.
function timeline(article, rows) {
  const h3s = [...article.querySelectorAll("h3[id]")];
  const target = (botName) => {
    const word = botName.split(/[\s(/]/)[0].replace(/["“”]/g, "");
    if (word.length < 3) return null;
    const re = new RegExp(`(^|\\W)${word.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}(\\W|$)`, "i");
    return h3s.find((x) => re.test(x.textContent));
  };
  return h("ol.timeline", {}, rows.map(([year, bot, author, tech]) => {
    const sec = target(bot.textContent);
    return h("li", {},
      h("div.tl-year", {}, year.textContent),
      h("div.tl-body", {},
        h("div.tl-name", {}, sec ? h("a", { href: `#${sec.id}` }, bot.textContent) : bot.textContent),
        h("div.tl-who", {}, author.textContent),
        h("div.tl-tech", {}, tech.textContent)));
  }));
}

// "Person | Handle | Known for" → cards.
function people(rows) {
  return h("div.people", {}, rows.map(([person, handle, what]) => h("div.person", {},
    h("div.person-name", {}, person.textContent),
    handle.textContent.trim() ? h("div.person-handle", {}, handle.textContent) : null,
    h("div.person-what", {}, ...what.childNodes))));
}

function scrollspy(article, toc, signal) {
  const links = new Map([...toc.querySelectorAll("a")].map((a) => [a.dataset.id, a]));
  const visible = new Set();
  const obs = new IntersectionObserver((entries) => {
    for (const e of entries) e.isIntersecting ? visible.add(e.target.id) : visible.delete(e.target.id);
    const heads = [...article.querySelectorAll("h2[id], h3[id]")];
    let cur = heads.find((x) => visible.has(x.id));
    if (!cur) cur = heads.filter((x) => x.getBoundingClientRect().top < 80).pop();
    for (const [id, a] of links) a.classList.toggle("on", id === cur?.id);
  }, { rootMargin: "-64px 0px -60% 0px" });
  for (const x of article.querySelectorAll("h2[id], h3[id]")) obs.observe(x);
  signal.addEventListener("abort", () => obs.disconnect());
}
