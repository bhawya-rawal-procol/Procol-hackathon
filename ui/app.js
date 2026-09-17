/* Vendor Intelligence — vendor analytics console. No framework, no build step. */
const $ = (s) => document.querySelector(s);
const $$ = (s) => Array.from(document.querySelectorAll(s));
const api = async (path, opts) => { const r = await fetch(path, opts); if (!r.ok) throw new Error(await r.text()); return r.json(); };
const pct = (v) => v == null ? "—" : Math.round(v * 100) + "%";
const num = (v, d = 1) => v == null ? "—" : Number(v).toFixed(d);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const css = (name, fallback) => getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;

const state = { vendor: null, meta: null, events: [], habits: null, profile: null, filter: "bid" };

/* card scaffold: head (title + meta) · body · optional footnote */
function card(el, title, meta, bodyHtml, footHtml) {
  $(el).innerHTML =
    `<div class="card-head"><h3>${esc(title)}</h3>${meta ? `<span class="meta">${esc(meta)}</span>` : ""}</div>
     <div class="card-body">${bodyHtml}</div>` +
    (footHtml ? `<p class="card-foot">${footHtml}</p>` : "");
}

// ------------------------------------------------------------------ chrome
const body = document.body;
const openAI = () => { body.classList.add("ai-open"); setTimeout(() => $("#chat-input").focus(), 240); };
const closeAI = () => body.classList.remove("ai-open");
$("#ai-open").onclick = openAI;
$("#ai-close").onclick = closeAI;
$("#pm-close").onclick = () => body.classList.remove("pm-open");
$("#scrim").onclick = () => { closeAI(); body.classList.remove("pm-open"); };
document.addEventListener("keydown", (e) => {
  if (e.key !== "Escape") return;
  if (body.classList.contains("pm-open")) body.classList.remove("pm-open"); else closeAI();
});

const theme = localStorage.getItem("vi-theme") ||
  (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
document.documentElement.dataset.theme = theme;
$("#theme-toggle").onclick = () => {
  const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  document.documentElement.dataset.theme = next;
  localStorage.setItem("vi-theme", next);
  renderActivity();                               // the only palette-baked SVG
};

// ------------------------------------------------------------------ boot
(async function boot() {
  state.meta = await api("/api/meta");
  $("#vendor-select").innerHTML = state.meta.vendors.map((v) =>
    `<option value="${v.id}">${esc(v.name)}${v.archetype !== "generic" ? "  ·  " + v.archetype : ""}</option>`).join("");
  state.vendor = +$("#vendor-select").value;
  $("#vendor-select").onchange = (e) => { state.vendor = +e.target.value; loadVendor(); };
  loadVendor();
})();

async function loadVendor() {
  const v = state.vendor;
  const [habits, events, profile] = await Promise.all([
    api(`/api/vendor/${v}/habits`), api(`/api/vendor/${v}/events`), api(`/api/vendor/${v}/profile`)]);
  Object.assign(state, { habits, events, profile });
  renderKpis(); renderActivity(); renderFunnel(); renderQuality();
  renderEvents();
  $("#scope-note").textContent =
    `${events.length} closed events · buyer feedback policy in effect: ${(habits.policy || "—").replaceAll("_", " ")}`;
  startChat();
}

// ------------------------------------------------------------------ analytics
const bidsOf = (evs) => evs.filter((e) => e.bid);
const winsOf = (evs) => evs.filter((e) => e.won);

const LEGEND = `<div class="legend">
  <span><b class="dot-ok"></b>won</span><span><b class="dot-accent"></b>bid, not won</span><span><b class="dot-rule"></b>invited, no bid</span></div>`;

/* one bar row: segments are shares of `max` */
function hbar(label, valueText, segments, zero) {
  return `<div class="hbar${zero ? " is-zero" : ""}">
    <span class="k">${esc(label)}</span><span class="n">${valueText}</span>
    <span class="track">${segments.map((s) => `<i class="${s.cls}" style="width:${s.w}%"></i>`).join("")}</span>
  </div>`;
}

function renderKpis() {
  const h = state.habits, evs = state.events;
  const bids = bidsOf(evs).length, wins = winsOf(evs).length;
  const missed = evs.filter((e) => e.missed_window).length;
  const tiles = [
    { l: "Invites received", v: h.invites ?? evs.length, d: `${evs.length} closed on record` },
    { l: "Bids placed", v: bids, d: `${pct(h.bid_rate)} of invites` },
    { l: "Events won", v: wins, d: `${pct(h.win_rate)} win rate` },
    { l: "Avg gap to L1", v: h.avg_gap_to_l1_pct == null ? "—" : num(h.avg_gap_to_l1_pct) + "%", d: "across your bids" },
    { l: "First bid after", v: h.avg_response_hours == null ? "—" : Math.round(h.avg_response_hours) + "h", d: `mail opened ${pct(h.mail_open_rate)}` },
    { l: "Windows missed", v: missed, d: `${pct(h.late_counter_offer_rate)} of counter-offers`, cls: missed ? "bad" : "" },
  ];
  $("#kpis").innerHTML = tiles.map((t) =>
    `<div class="kpi"><div class="l">${esc(t.l)}</div><div class="v ${t.cls || ""}">${esc(t.v)}</div><div class="d">${esc(t.d)}</div></div>`).join("");
}

function renderActivity() {
  const evs = state.events;
  if (!evs.length) return card("#card-activity", "Activity by month", "", `<p class="fine">No events on record.</p>`, "");
  const months = monthsOf(evs), last = months[months.length - 1];
  card("#card-activity", "Activity by month", `last ${months.length} months`,
    monthChart(months) + LEGEND,
    `Latest month (${esc(last.k)}): ${last.invites} invites, ${last.bids} bids, <b>${last.wins} won</b>.`);
}

function monthsOf(evs) {
  const m = new Map();
  evs.forEach((e) => {
    const k = (e.closed_at || "").slice(0, 7);
    const g = m.get(k) || { k, invites: 0, bids: 0, wins: 0 };
    g.invites++; if (e.bid) g.bids++; if (e.won) g.wins++;
    m.set(k, g);
  });
  return Array.from(m.values()).sort((a, b) => a.k.localeCompare(b.k)).slice(-8);
}

function monthChart(months) {
  const accent = css("--accent", "#2563eb"), ok = css("--ok-bar", "#1d9a6c"),
        dim = css("--bar-dim", "#d6dae2"), rule = css("--rule-soft", "#eef0f4"), label = css("--ink3", "#79839a");
  const W = 340, H = 168, L = 22, R = 6, T = 8, base = H - 22;
  const raw = Math.max(1, ...months.map((g) => g.invites));
  const step = raw <= 4 ? 1 : raw <= 10 ? 2 : Math.ceil(raw / 4);
  const max = Math.ceil(raw / step) * step;
  const y = (n) => base - (n / max) * (base - T);
  const ticks = []; for (let n = 0; n <= max; n += step) ticks.push(n);
  const grid = ticks.map((n) => `
    <line x1="${L}" y1="${y(n).toFixed(1)}" x2="${W - R}" y2="${y(n).toFixed(1)}" stroke="${rule}" stroke-width="1"></line>
    <text x="${L - 6}" y="${(y(n) + 3.2).toFixed(1)}" font-size="9" text-anchor="end" fill="${label}">${n}</text>`).join("");
  const slot = (W - L - R) / months.length, bw = Math.min(9, (slot - 8) / 3);
  const bars = months.map((g, i) => {
    const gx = L + i * slot + (slot - bw * 3 - 4) / 2;
    return [[g.invites, dim], [g.bids, accent], [g.wins, ok]].map(([n, fill], j) => {
      const h = Math.max(n ? 1.5 : 0, base - y(n));
      return `<rect x="${(gx + j * (bw + 2)).toFixed(1)}" y="${(base - h).toFixed(1)}" width="${bw.toFixed(1)}" height="${h.toFixed(1)}" rx="1.5" fill="${fill}"></rect>`;
    }).join("") +
      `<text x="${(gx + (bw * 3 + 4) / 2).toFixed(1)}" y="${H - 7}" font-size="9" text-anchor="middle" fill="${label}">${esc(g.k.slice(2).replace("-", "/"))}</text>`;
  }).join("");
  return `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="invites, bids and wins by month">
    ${grid}${bars}<line x1="${L}" y1="${base}" x2="${W - R}" y2="${base}" stroke="${dim}" stroke-width="1"></line></svg>`;
}

function renderFunnel() {
  const h = state.habits, evs = state.events;
  const invites = h.invites ?? evs.length;
  const opened = h.mail_open_rate == null ? null : Math.round(invites * h.mail_open_rate);
  const bids = bidsOf(evs).length, wins = winsOf(evs).length;
  const steps = [
    ["Invited", invites, ""],
    ["Opened the mail", opened, pct(h.mail_open_rate)],
    ["Bid submitted", bids, pct(h.bid_rate)],
    ["Won", wins, pct(h.win_rate)],
  ].filter(([, n]) => n != null);
  const max = Math.max(1, ...steps.map(([, n]) => n));
  const rows = steps.map(([k, n, d], i) => hbar(k, `${n}${d ? " · " + d : ""}`,
    [{ cls: i === steps.length - 1 ? "won" : "bid", w: n / max * 100 }])).join("");
  const drop = invites && bids ? Math.round((1 - bids / invites) * 100) : 0;
  card("#card-funnel", "Invite → win funnel", `${invites} invites`,
    `<div class="hbars">${rows}</div>`,
    drop ? `You drop <b>${drop}%</b> of invites before bidding.` : `You bid on every invite on record.`);
}

function renderQuality() {
  const h = state.habits, p = state.profile, t = h.technical, d = h.delivery || {};
  card("#card-quality", "Delivery, technical & profile", `${d.deliveries ?? 0} deliveries`,
    `<div class="stat">
       <div><span class="l">On-time delivery</span><span class="v ${d.on_time_rate != null && d.on_time_rate < .9 ? "bad" : ""}">${pct(d.on_time_rate)}</span></div>
       <div><span class="l">QC pass rate</span><span class="v">${pct(d.qc_pass_rate)}</span></div>
       <div><span class="l">Technical average</span><span class="v">${t?.avg_pct == null ? "—" : Math.round(t.avg_pct) + "%"}</span></div>
       <div><span class="l">Profile complete</span><span class="v ${p.completeness_pct < 70 ? "bad" : ""}">${p.completeness_pct}%</span></div>
     </div>`, "");
}

// ------------------------------------------------------------------ bid history
const FILTERS = {
  bid: (e) => e.bid,
  won: (e) => e.won,
  lost: (e) => e.bid && !e.won,
  skipped: (e) => !e.bid,
  all: () => true,
};
$$("#event-filters button").forEach((b) => b.onclick = () => {
  state.filter = b.dataset.f;
  $$("#event-filters button").forEach((x) => x.classList.toggle("on", x === b));
  renderEvents();
});

function renderEvents() {
  const evs = state.events.filter(FILTERS[state.filter]);
  $("#events-body").innerHTML = evs.length ? evs.map((e) => `
    <tr data-tr="${e.trade_request_id}">
      <td class="name">${esc(e.title)}</td>
      <td>${esc(e.buyer)}</td>
      <td>${esc(e.category)}</td>
      <td>${esc((e.rfx_mode || "").toUpperCase())}</td>
      <td class="num">${esc((e.closed_at || "").slice(0, 10))}</td>
      <td>${e.won ? '<span class="pill won">Won</span>' : e.bid ? '<span class="pill lost">Lost</span>' : '<span class="pill">No bid</span>'}
          ${e.missed_window ? '<span class="pill late">Missed window</span>' : ""}
          ${e.policy === "none" ? '<span class="pill none">No feedback</span>' : ""}</td>
      <td class="act">Post-mortem</td>
    </tr>`).join("")
    : `<tr><td class="empty" colspan="7">No events under this filter.</td></tr>`;
  $$("#events-body tr[data-tr]").forEach((tr) => tr.onclick = () => showPostMortem(+tr.dataset.tr));
  $("#events-note").textContent =
    `${evs.length} of ${state.events.length} closed events · ${bidsOf(state.events).length} bids placed`;
}

async function showPostMortem(tr) {
  body.classList.add("pm-open");
  $("#postmortem").innerHTML = `<p class="fine">Running checks…</p>`;
  const p = await api(`/api/vendor/${state.vendor}/events/${tr}/postmortem?force=1`);
  if (!p.available) {
    $("#postmortem").innerHTML = `<p class="eyebrow">Post-mortem</p><h2>${esc(p.title)}</h2>
      <div class="blocked">This buyer's feedback policy is <b>none</b> — no event feedback is shared with vendors.
      (Guard: ${esc(p.guard_audit.map((a) => a.action).join(", "))})</div>`;
    return;
  }
  const order = ["timing", "price", "technical", "terms"];
  $("#postmortem").innerHTML = `
    <p class="eyebrow">${p.won ? "Why I won" : "Why I lost"} · ${esc(p.policy.replaceAll("_", " "))} · narrator: ${esc(p.narrator)}</p>
    <h2>${esc(p.title)}</h2>
    <p class="story">${esc(p.narration)}</p>
    <div class="next"><b>Next time:</b> ${esc(p.next_action)}</div>
    ${order.filter((k) => p.checks[k]).map((k) => `<div class="check ${p.checks[k].severity}"><b>${k} · ${p.checks[k].severity}</b>${esc(p.checks[k].signal)}</div>`).join("")}
    ${p.policy === "relative_only" ? `<p class="fine">Technical section withheld by buyer policy.</p>` : ""}
    <p class="fine">Confidentiality guard removed ${p.guard_audit.length} item(s)${p.guard_audit.length ? ": " + esc(p.guard_audit.map((a) => a.reason).join("; ")) : ""}. Nothing about other vendors is shown here.</p>`;
}

// ------------------------------------------------------------------ analytics intelligence (chat)
const chatState = { session: null, busy: false };
const log = () => $("#chat-log");
const input = $("#chat-input");

$("#chat-form").onsubmit = (e) => { e.preventDefault(); sendChat(input.value); };
$("#chat-reset").onclick = () => { startChat(); input.focus(); };
input.addEventListener("input", autosize);
input.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendChat(input.value); } });
function autosize() {
  input.style.height = "";
  if (input.value.trim()) input.style.height = Math.min(input.scrollHeight, 170) + "px";
  $("#send-btn").disabled = !input.value.trim() || chatState.busy;
}
autosize();
window.addEventListener("load", autosize);
if (document.fonts && document.fonts.ready) document.fonts.ready.then(autosize);

const ENGINE_LABEL = { anthropic: "Claude", groq: "Groq", openai: "OpenAI", grok: "Grok" };
function showEngine(st) {
  const live = st.engine !== "offline";
  const label = ENGINE_LABEL[st.engine] || st.engine;
  $("#engine-badge").textContent = live ? `${label} · ${st.model}` : "fallback engine";
  $("#engine-badge").className = `pill ${live ? "claude" : "offline"}`;
  $("#engine-toggle").textContent = st.engine === "anthropic" ? "disconnect" : "connect Claude";
}
$("#engine-toggle").onclick = async () => {
  const st = await api("/api/settings/claude");
  if (st.engine === "anthropic") {
    const r = await api("/api/settings/claude", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ api_key: "" }) });
    showEngine(r); $("#key-form").hidden = true; return;
  }
  $("#key-form").hidden = !$("#key-form").hidden;
  if (!$("#key-form").hidden) $("#key-input").focus();
};
$("#key-form").onsubmit = async (e) => {
  e.preventDefault();
  $("#key-msg").textContent = "connecting…";
  const r = await api("/api/settings/claude", { method: "POST", headers: { "content-type": "application/json" },
    body: JSON.stringify({ api_key: $("#key-input").value.trim(), model: $("#model-input").value.trim() || undefined }) });
  $("#key-msg").textContent = r.message;
  if (r.ok && r.engine === "anthropic") { $("#key-form").hidden = true; $("#key-input").value = ""; showEngine(r); startChat(); }
};

async function startChat() {
  chatState.session = null;
  log().innerHTML = "";
  const g = await api(`/api/vendor/${state.vendor}/chat/greeting`);
  showEngine(g);
  log().insertAdjacentHTML("beforeend",
    `<div class="hello"><h1>Ask for any cut of your data</h1><p>${esc(g.text)}</p></div>`);
  renderSuggestions(g.suggestions || []);
  autosize();
}

function renderSuggestions(list) {
  $("#chat-suggest").innerHTML = list.map((s) => `<button type="button">${esc(s)}</button>`).join("");
  $$("#chat-suggest button").forEach((b) => b.onclick = () => sendChat(b.textContent));
}

/* light markdown: **bold**, *italic*, `code`, bullets, pipe tables */
function mdish(text) {
  const inline = (s) => esc(s)
    .replace(/\*\*(.+?)\*\*/g, "<b>$1</b>")
    .replace(/(^|[^*])\*([^*\n]+)\*/g, "$1<em>$2</em>")
    .replace(/`([^`]+)`/g, "<code>$1</code>");
  const out = []; let bullets = [], table = [];
  const cells = (row) => row.replace(/^\||\|$/g, "").split("|").map((c) => c.trim());
  const flushTable = () => {
    if (!table.length) return;
    const [head, ...rest] = table;
    out.push(`<table><thead><tr>${cells(head).map((c) => `<th>${inline(c)}</th>`).join("")}</tr></thead>` +
      `<tbody>${rest.map((r) => `<tr>${cells(r).map((c) => `<td>${inline(c)}</td>`).join("")}</tr>`).join("")}</tbody></table>`);
    table = [];
  };
  const flush = () => {
    if (bullets.length) { out.push(`<ul>${bullets.join("")}</ul>`); bullets = []; }
    flushTable();
  };
  String(text ?? "").split("\n").forEach((line) => {
    const t = line.trim();
    if (t.startsWith("|") && t.endsWith("|")) {
      if (!/^\|[\s:|-]+\|$/.test(t)) table.push(t);
      return;
    }
    const m = t.match(/^[-•*]\s+(.*)$/);
    if (m) { flushTable(); bullets.push(`<li>${inline(m[1])}</li>`); return; }
    flush();
    if (t) out.push(`<p>${inline(t)}</p>`);
  });
  flush();
  return out.join("") || "<p></p>";
}

function addMsg(role, text, tools) {
  $(".hello")?.remove();
  const div = document.createElement("div");
  if (role === "user") {
    div.className = "msg user";
    div.innerHTML = `<div class="bubble">${esc(text)}</div>`;
  } else {
    div.className = "msg bot";
    const inner = role === "think"
      ? `<div class="dots"><i></i><i></i><i></i></div>`
      : mdish(text) + `<div class="meta">${tools && tools.length
          ? `<span class="tools">used ${tools.map((t) => esc(t.tool)).join(", ")}</span>` : ""}
          <button class="copy-btn" type="button">Copy</button></div>`;
    div.innerHTML = `<div class="role">Analytics Intelligence</div><div class="body">${inner}</div>`;
    const copy = div.querySelector(".copy-btn");
    if (copy) copy.onclick = () => {
      navigator.clipboard.writeText(text);
      copy.textContent = "Copied"; copy.parentElement.classList.add("always");
      setTimeout(() => { copy.textContent = "Copy"; copy.parentElement.classList.remove("always"); }, 1400);
    };
  }
  log().appendChild(div);
  $("#thread").scrollTop = $("#thread").scrollHeight;
  return div;
}

async function sendChat(text) {
  text = (text || "").trim();
  if (!text || chatState.busy) return;
  chatState.busy = true;
  input.value = ""; autosize();
  $("#chat-suggest").innerHTML = "";
  addMsg("user", text);
  const thinking = addMsg("think");
  try {
    const r = await api(`/api/vendor/${state.vendor}/chat`, { method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ session_id: chatState.session, message: text }) });
    chatState.session = r.session_id;
    thinking.remove();
    addMsg("bot", r.reply, r.tools);
    if (r.engine === "offline" && $("#engine-badge").classList.contains("claude")) showEngine({ engine: "offline" });
  } catch (e) {
    thinking.remove(); addMsg("bot", "Something went wrong answering that. Try again.");
  } finally { chatState.busy = false; autosize(); input.focus(); }
}
