/* Vendor Intelligence demo UI — no framework, no build step. */
const $ = (s) => document.querySelector(s);
const api = async (path, opts) => { const r = await fetch(path, opts); if (!r.ok) throw new Error(await r.text()); return r.json(); };
const pct = (v) => v == null ? "—" : Math.round(v * 100) + "%";
const num = (v, d = 1) => v == null ? "—" : Number(v).toFixed(d);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

const state = { persona: "buyer", buyer: null, vendor: null, tr: null, reco: null, meta: null };

// ------------------------------------------------------------------ boot
(async function boot() {
  state.meta = await api("/api/meta");
  $("#buyer-select").innerHTML = state.meta.buyers.map((b) => `<option value="${b.id}">${esc(b.name)}</option>`).join("");
  $("#vendor-select").innerHTML = state.meta.vendors.map((v) =>
    `<option value="${v.id}">${esc(v.name)}${v.archetype !== "generic" ? "  ·  " + v.archetype : ""}</option>`).join("");
  state.buyer = +$("#buyer-select").value;
  state.vendor = +$("#vendor-select").value;
  $("#model-note").textContent = state.meta.models_ready
    ? `Ranker: ${state.meta.model_metrics.p_top3.chosen}, out-of-time test AUC ${state.meta.model_metrics.p_top3.test_auc[state.meta.model_metrics.p_top3.chosen]} (P(bid & top-3)); forecast uses P(bid) AUC ${state.meta.model_metrics.p_bid.test_auc[state.meta.model_metrics.p_bid.chosen]}. Synthetic data — these numbers describe the prototype, not Procol.`
    : "Models not trained — run `make train`.";
  document.querySelectorAll(".persona button").forEach((b) => b.onclick = () => setPersona(b.dataset.persona));
  $("#buyer-select").onchange = (e) => { state.buyer = +e.target.value; loadBuyer(); };
  $("#vendor-select").onchange = (e) => { state.vendor = +e.target.value; loadVendor(); };
  document.querySelectorAll('#policy-radios input').forEach((r) => r.onchange = () => setPolicy(r.value));
  $("#btn-forecast").onclick = runForecast;
  loadBuyer();
})();

function setPersona(p) {
  state.persona = p;
  document.querySelectorAll(".persona button").forEach((b) => b.classList.toggle("on", b.dataset.persona === p));
  $("#buyer-view").hidden = p !== "buyer"; $("#vendor-view").hidden = p !== "vendor";
  $("#who-buyer").hidden = p !== "buyer"; $("#who-vendor").hidden = p !== "vendor";
  if (p === "vendor") loadVendor();
}

// ------------------------------------------------------------------ buyer
async function loadBuyer() {
  const policy = state.meta.policies[state.buyer] || "relative_only";
  document.querySelectorAll('#policy-radios input').forEach((r) => r.checked = r.value === policy);
  const evs = await api(`/api/buyer/${state.buyer}/events`);
  $("#buyer-events").innerHTML = evs.map((e) => `
    <li data-tr="${e.trade_request_id}" data-status="${e.status}">
      <span class="t">${esc(e.title)}</span><span class="pill ${e.status}">${e.status}</span>
      <span class="s">${esc(e.category)} · ${e.rfx_mode.toUpperCase()} · ${e.status === "draft" ? "not yet published" : `${e.invited} invited, ${e.bidders} bid`}</span>
    </li>`).join("");
  document.querySelectorAll("#buyer-events li").forEach((li) => li.onclick = () => pickEvent(+li.dataset.tr, li));
  $("#reco").hidden = true; $("#buyer-empty").hidden = false; $("#scorecard").hidden = true;
  const first = document.querySelector('#buyer-events li[data-status="draft"]');
  if (first) pickEvent(+first.dataset.tr, first);
}

async function setPolicy(policy) {
  await api(`/api/buyer/${state.buyer}/policy`, { method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify({ policy }) });
  state.meta.policies[state.buyer] = policy;
}

async function pickEvent(tr, li) {
  document.querySelectorAll("#buyer-events li").forEach((x) => x.classList.toggle("sel", x === li));
  state.tr = tr;
  $("#buyer-empty").hidden = true; $("#reco").hidden = false;
  $("#reco-title").textContent = li.querySelector(".t").textContent;
  $("#reco-meta").textContent = "scoring vendors…";
  $("#reco-table tbody").innerHTML = ""; $("#discovery").innerHTML = ""; $("#forecast-msg").innerHTML = "Tick vendors to invite, then forecast. Rule: at least 3 expected bids."; $("#forecast-suggest").innerHTML = "";
  const r = await api(`/api/buyer/${state.buyer}/events/${tr}/recommendations`);
  state.reco = r;
  $("#reco-meta").textContent = `${r.category} · ${r.ranked.length} eligible vendors · lot value ₹${Math.round(r.lot_value).toLocaleString("en-IN")} · ${r.lead_days} days to bid`;
  $("#reco-table tbody").innerHTML = r.ranked.map((v) => `
    <tr>
      <td><input type="checkbox" class="inv" value="${v.vendor_id}" ${v.rank <= 5 ? "checked" : ""}></td>
      <td class="num">${v.rank}</td>
      <td><span class="name" data-v="${v.vendor_id}">${esc(v.name)}</span>${v.archetype !== "generic" ? `<span class="arch">${v.archetype}</span>` : ""}${v.cold_start ? `<span class="arch">no history — cold start</span>` : ""}</td>
      <td class="num"><span class="bar"><i style="width:${Math.round(v.score * 100)}%"></i></span>${num(v.score, 2)}</td>
      <td class="num">${num(v.p_bid, 2)}</td>
      <td class="why">${v.reasons.map((x) => `<span class="${x.direction === "-" ? "neg" : ""}">${esc(x.text)}</span>`).join(" · ")}</td>
    </tr>`).join("");
  document.querySelectorAll("#reco-table .name").forEach((n) => n.onclick = () => showScorecard(+n.dataset.v));
  $("#discovery").innerHTML = r.discovery.length ? r.discovery.map((d) => `
    <li><strong>${esc(d.name)}</strong> ${d.archetype !== "generic" ? `<span class="pill">${d.archetype}</span>` : ""}<br><span class="muted">${esc(d.note)}</span></li>`).join("")
    : `<li class="muted">No unmapped vendors active in ${esc(r.category)} with 2+ other buyers.</li>`;
}

async function runForecast() {
  const ids = [...document.querySelectorAll(".inv:checked")].map((c) => +c.value);
  $("#forecast-msg").textContent = "forecasting…";
  const f = await api(`/api/buyer/${state.buyer}/events/${state.tr}/forecast`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ vendor_ids: ids }) });
  $("#forecast-msg").innerHTML = `<strong style="color:${f.sufficient ? "var(--ok)" : "var(--crit)"}">${esc(f.message)}</strong>`;
  $("#forecast-suggest").innerHTML = f.suggestions.length ? `<div class="sugg">${f.suggestions.map((s) =>
    `<button data-v="${s.vendor_id}">+ ${esc(s.name)} <span class="muted">P(bid) ${num(s.p_bid, 2)}</span></button>`).join("")}</div>` : "";
  document.querySelectorAll("#forecast-suggest button").forEach((b) => b.onclick = () => {
    const cb = document.querySelector(`.inv[value="${b.dataset.v}"]`); if (cb) cb.checked = true; runForecast();
  });
}

async function showScorecard(vid) {
  const s = await api(`/api/buyer/${state.buyer}/vendors/${vid}/scorecard`);
  const row = (label, key, fmt = pct) => {
    const g = (o) => (o ? fmt(o[key]) : "—");
    return `<div class="h">${label}</div><div class="num">${g(s.with_you["90d"])}</div><div class="num">${g(s.with_you["365d"])}</div><div class="num">${g(s.with_you["all"])}</div>`;
  };
  const tr = s.overall.all && s.overall.all.trend_90d_vs_365d;
  $("#scorecard").hidden = false;
  $("#scorecard").innerHTML = `
    <div class="card">
      <h3>Vendor scorecard</h3>
      <h2>${esc(s.vendor.name)} ${s.vendor.archetype !== "generic" ? `<span class="pill">${s.vendor.archetype}</span>` : ""}</h2>
      <p class="muted" style="margin:0 0 8px">With you · by window</p>
      <div class="kv">
        <div class="h"></div><div class="h">90d</div><div class="h">365d</div><div class="h">all</div>
        ${row("Invites", "invites", (v) => v ?? "—")}${row("Bid rate", "bid_rate")}${row("Win rate", "win_rate")}
        ${row("Gap to L1", "avg_gap_to_l1_pct", (v) => v == null ? "—" : num(v) + "%")}
        ${row("Late counter-offer replies", "late_counter_offer_rate")}${row("On-time delivery", "on_time_delivery_rate")}${row("QC pass", "qc_pass_rate")}
        ${row("Technical avg", "avg_technical_pct", (v) => v == null ? "—" : Math.round(v) + "%")}
      </div>
      <p style="margin-top:10px">Delivery trend (all buyers, 90d vs 365d): <span class="trend ${tr < -5 ? "down" : tr > 5 ? "up" : ""}">${tr == null ? "—" : (tr > 0 ? "+" : "") + tr + " pp"}</span></p>
      <h3 style="margin-top:12px">By category (all buyers)</h3>
      <div class="kv" style="grid-template-columns:1fr auto auto auto">
        <div class="h">Category</div><div class="h">Bids</div><div class="h">Win</div><div class="h">Gap</div>
        ${s.by_category.map((c) => `<div>${esc(c.category)}</div><div class="num">${c.events_bid ?? 0}</div><div class="num">${pct(c.win_rate)}</div><div class="num">${c.avg_gap_to_l1_pct == null ? "—" : num(c.avg_gap_to_l1_pct) + "%"}</div>`).join("")}
      </div>
    </div>`;
}

// ------------------------------------------------------------------ vendor
async function loadVendor() {
  const v = state.vendor;
  const [habits, events, band, profile] = await Promise.all([
    api(`/api/vendor/${v}/habits`), api(`/api/vendor/${v}/events`), api(`/api/vendor/${v}/priceband`), api(`/api/vendor/${v}/profile`)]);
  renderHabits(habits); renderEvents(events); renderBand(band); renderProfile(profile);
  $("#postmortem").innerHTML = "Click a lost event to see why."; $("#postmortem").className = "card muted";
  startChat();
}

// ------------------------------------------------------------------ vendor chat
const chatState = { session: null, busy: false };
$("#chat-form").onsubmit = (e) => { e.preventDefault(); sendChat($("#chat-input").value); };
$("#chat-reset").onclick = () => startChat();

const ENGINE_LABEL = { anthropic: "Claude", groq: "Groq", openai: "OpenAI", grok: "Grok" };
function showEngine(st) {
  const live = st.engine !== "offline";
  const label = ENGINE_LABEL[st.engine] || st.engine;
  $("#engine-badge").textContent = live ? `${label} · ${st.model}` : "fallback engine";
  $("#engine-badge").className = `pill ${live ? "claude" : "offline"}`;
  $("#engine-text").textContent = live ? "free conversation over your guarded record"
    : "deterministic answers only — connect Claude for free conversation";
  $("#engine-toggle").textContent = st.engine === "anthropic" ? "disconnect" : "connect Claude";
}
$("#engine-toggle").onclick = async () => {
  const st = await api("/api/settings/claude");
  if (st.engine === "anthropic") {
    const r = await api("/api/settings/claude", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ api_key: "" }) });
    showEngine(r); $("#key-form").hidden = true; return;
  }
  $("#key-form").hidden = !$("#key-form").hidden;
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
  $("#chat-log").innerHTML = "";
  const g = await api(`/api/vendor/${state.vendor}/chat/greeting`);
  showEngine(g);
  addMsg("bot", g.text);
  $("#chat-suggest").innerHTML = g.suggestions.map((s) => `<button type="button">${esc(s)}</button>`).join("");
  document.querySelectorAll("#chat-suggest button").forEach((b) => b.onclick = () => sendChat(b.textContent));
}

function addMsg(role, text, tools) {
  const div = document.createElement("div");
  div.className = `msg ${role}`;
  div.innerHTML = esc(text).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>") +
    (tools && tools.length ? `<span class="tools">used: ${tools.map((t) => esc(t.tool)).join(", ")}</span>` : "");
  $("#chat-log").appendChild(div);
  $("#chat-log").scrollTop = $("#chat-log").scrollHeight;
  return div;
}

async function sendChat(text) {
  text = (text || "").trim();
  if (!text || chatState.busy) return;
  chatState.busy = true;
  $("#chat-input").value = "";
  addMsg("user", text);
  const thinking = addMsg("bot think", "checking your record…");
  try {
    const r = await api(`/api/vendor/${state.vendor}/chat`, { method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ session_id: chatState.session, message: text }) });
    chatState.session = r.session_id;
    thinking.remove();
    addMsg("bot", r.reply, r.tools);
    if (r.engine === "offline" && $("#engine-badge").classList.contains("claude")) showEngine({ engine: "offline" });
  } catch (e) {
    thinking.remove(); addMsg("bot", "Something went wrong answering that. Try again.");
  } finally { chatState.busy = false; }
}

function renderHabits(h) {
  const late = h.late_counter_offer_rate, sl = h.short_lead || {}, ll = h.long_lead || {};
  const declines = Object.entries(h.decline_reasons || {}).map(([k, n]) => `${k.replaceAll("_", " ")} (${n})`).join(", ") || "none recorded";
  $("#habits").innerHTML = `
    <h3>My habits <span class="muted">· policy in effect: ${h.policy}</span></h3>
    <div class="stat">
      <div><div class="l">Invites</div><div class="v">${h.invites ?? "—"}</div></div>
      <div><div class="l">Bid rate</div><div class="v">${pct(h.bid_rate)}</div></div>
      <div><div class="l">Mail open rate</div><div class="v ${h.mail_open_rate < 0.5 ? "bad" : ""}">${pct(h.mail_open_rate)}</div></div>
      <div><div class="l">First bid after</div><div class="v">${h.avg_response_hours == null ? "—" : Math.round(h.avg_response_hours) + "h"}</div></div>
      <div><div class="l">Win rate</div><div class="v">${pct(h.win_rate)}</div></div>
      <div><div class="l">Avg gap to L1</div><div class="v">${h.avg_gap_to_l1_pct == null ? "—" : num(h.avg_gap_to_l1_pct) + "%"}</div></div>
      <div><div class="l">Counter-offer windows missed</div><div class="v ${late > 0.4 ? "bad" : late < 0.15 ? "good" : ""}">${pct(late)}</div></div>
      <div><div class="l">Extensions you caused</div><div class="v">${h.extensions_caused ?? 0}</div></div>
    </div>
    <p class="fine" style="margin-top:10px">Short-lead events (≤3 days): you bid on ${pct(sl.bid_rate)} of ${sl.n ?? 0}. Longer lead: ${pct(ll.bid_rate)} of ${ll.n ?? 0}.<br>
    Reasons you gave for declining: ${esc(declines)}.</p>
    ${h.technical ? `<p class="fine">Technical avg ${h.technical.avg_pct == null ? "—" : Math.round(h.technical.avg_pct) + "%"}; weakest section <b>${esc((h.technical.weakest_section || "—").replaceAll("_", " "))}</b> at ${h.technical.weakest_pct == null ? "—" : Math.round(h.technical.weakest_pct) + "%"}.</p>`
      : `<p class="fine">No technical scores from buyers who share technical feedback yet.</p>`}
    <p class="fine">Delivery on-time ${pct(h.delivery?.on_time_rate)} over ${h.delivery?.deliveries ?? 0} orders · trend 90d vs 365d: <span class="trend ${h.delivery?.trend_90d_vs_365d < -5 ? "down" : ""}">${h.delivery?.trend_90d_vs_365d == null ? "—" : h.delivery.trend_90d_vs_365d + " pp"}</span></p>`;
}

function renderEvents(evs) {
  $("#vendor-events").innerHTML = evs.map((e) => `
    <li data-tr="${e.trade_request_id}">
      <span class="t">${esc(e.title)}</span>
      <span>${e.won ? '<span class="pill won">won</span>' : e.bid ? '<span class="pill lost">lost</span>' : '<span class="pill">no bid</span>'}
      ${e.missed_window ? '<span class="pill late">missed window</span>' : ""}${e.policy === "none" ? '<span class="pill none">no feedback</span>' : ""}</span>
      <span class="s">${esc(e.buyer)} · ${esc(e.category)} · ${e.rfx_mode.toUpperCase()} · closed ${e.closed_at.slice(0, 10)}</span>
    </li>`).join("");
  document.querySelectorAll("#vendor-events li").forEach((li) => li.onclick = () => {
    document.querySelectorAll("#vendor-events li").forEach((x) => x.classList.toggle("sel", x === li)); showPostMortem(+li.dataset.tr);
  });
}

async function showPostMortem(tr) {
  $("#postmortem").className = "card"; $("#postmortem").innerHTML = "<span class='muted'>running checks…</span>";
  const p = await api(`/api/vendor/${state.vendor}/events/${tr}/postmortem?force=1`);
  if (!p.available) {
    $("#postmortem").innerHTML = `<h3>Why I lost</h3><h2>${esc(p.title)}</h2><div class="blocked">This buyer's feedback policy is <b>none</b>. No event feedback is shared with vendors. (Guard: ${p.guard_audit.map((a) => a.action).join(", ")})</div>`;
    return;
  }
  const order = ["timing", "price", "technical", "terms"];
  $("#postmortem").innerHTML = `
    <h3>${p.won ? "Why I won" : "Why I lost"} <span class="muted">· ${p.policy.replaceAll("_", " ")} · narrator: ${p.narrator}</span></h3>
    <h2>${esc(p.title)}</h2>
    <p class="story">${esc(p.narration)}</p>
    <div class="next"><b>Next time:</b> ${esc(p.next_action)}</div>
    ${order.filter((k) => p.checks[k]).map((k) => `<div class="check ${p.checks[k].severity}"><b>${k} · ${p.checks[k].severity}</b>${esc(p.checks[k].signal)}</div>`).join("")}
    ${p.policy === "relative_only" ? `<p class="fine">Technical section withheld by buyer policy.</p>` : ""}
    <p class="fine">Confidentiality guard removed ${p.guard_audit.length} item(s)${p.guard_audit.length ? ": " + p.guard_audit.map((a) => esc(a.reason)).join("; ") : ""}. Nothing about other vendors is shown here.</p>`;
}

function renderBand(b) {
  const cats = b.categories || [];
  $("#priceband").innerHTML = `<h3>My winning price band <span class="muted">· from my own bids only</span></h3>` +
    (cats.length ? cats.map((c) => {
      const w = 300, h = 90, bw = 48, max = 1;
      const bars = c.buckets.map((k, i) => {
        const v = k.win_rate ?? 0, bh = Math.round(v / max * 55), x = 8 + i * (bw + 10);
        return `<rect x="${x}" y="${65 - bh}" width="${bw}" height="${bh}" fill="${k.bids ? "#0d5c63" : "#e3e9ea"}" rx="2"></rect>
                <text x="${x + bw / 2}" y="${60 - bh}" font-size="10" text-anchor="middle" fill="#15191b">${k.bids ? Math.round(v * 100) + "%" : ""}</text>
                <text x="${x + bw / 2}" y="78" font-size="9" text-anchor="middle" fill="#7a868b">${k.bucket}</text>
                <text x="${x + bw / 2}" y="88" font-size="9" text-anchor="middle" fill="#7a868b">n=${k.bids}</text>`;
      }).join("");
      return `<div class="pb"><div class="cat">${esc(c.category)} <span class="muted">· ${c.total_bids} bids</span></div>
        <svg viewBox="0 0 ${w} ${h}" role="img" aria-label="win rate by gap to L1">${bars}</svg><div class="ins">${esc(c.insight)}</div></div>`;
    }).join("") : `<p class="muted">No bid history yet.</p>`);
}

function renderProfile(p) {
  const f = p.fields;
  $("#profile").innerHTML = `<h3>Profile & compliance</h3>
    <div class="stat"><div><div class="l">Completeness</div><div class="v ${p.completeness_pct < 70 ? "bad" : "good"}">${p.completeness_pct}%</div></div>
    <div><div class="l">Buyers</div><div class="v">${p.buyers.length}</div></div></div>
    <p class="fine" style="margin-top:8px">Missing: ${Object.entries(f).filter(([, v]) => !v).map(([k]) => k.replaceAll("_", " ")).join(", ") || "nothing"}.<br>
    Pending onboarding: ${p.pending_onboarding.length ? p.pending_onboarding.map(esc).join(", ") : "none"}.<br>Categories: ${p.categories.map(esc).join(", ")}.</p>`;
}
