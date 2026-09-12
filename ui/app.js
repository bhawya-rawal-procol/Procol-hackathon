/* Vendor Intelligence demo UI — no framework, no build step. */
const $ = (s) => document.querySelector(s);
const api = async (path, opts) => { const r = await fetch(path, opts); if (!r.ok) throw new Error(await r.text()); return r.json(); };
const pct = (v) => v == null ? "—" : Math.round(v * 100) + "%";
const num = (v, d = 1) => v == null ? "—" : Number(v).toFixed(d);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

const state = { vendor: null, meta: null };

// ------------------------------------------------------------------ boot
(async function boot() {
  state.meta = await api("/api/meta");
  $("#vendor-select").innerHTML = state.meta.vendors.map((v) =>
    `<option value="${v.id}">${esc(v.name)}${v.archetype !== "generic" ? "  ·  " + v.archetype : ""}</option>`).join("");
  state.vendor = +$("#vendor-select").value;
  $("#vendor-select").onchange = (e) => { state.vendor = +e.target.value; loadVendor(); };
  loadVendor();
})();

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
