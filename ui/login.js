/* Sign-in: mobile → OTP → session cookie. The dashboard is unreachable without it. */
const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const post = async (path, body) => {
  const r = await fetch(path, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
  return { ok: r.ok, data: await r.json() };
};

const theme = localStorage.getItem("vi-theme") ||
  (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
document.documentElement.dataset.theme = theme;

const state = { mobile: null };
const digits = (v) => String(v || "").replace(/\D/g, "");

function showErr(el, msg) {
  const box = $(el);
  box.textContent = msg || "";
  box.hidden = !msg;
}

function step(which) {
  $("#mobile-form").hidden = which !== "mobile";
  $("#otp-form").hidden = which !== "otp";
  setTimeout(() => $(which === "mobile" ? "#mobile" : "#otp").focus(), 30);
}

// ------------------------------------------------------------------ step 1
$("#mobile").addEventListener("input", (e) => { e.target.value = digits(e.target.value).slice(0, 10); });

$("#mobile-form").onsubmit = async (e) => {
  e.preventDefault();
  showErr("#mobile-err", "");
  const mobile = digits($("#mobile").value);
  if (mobile.length < 10) return showErr("#mobile-err", "Enter a 10-digit mobile number.");
  $("#mobile-btn").disabled = true;
  try {
    await sendOtp(mobile);
  } finally { $("#mobile-btn").disabled = false; }
};

async function sendOtp(mobile) {
  const { ok, data } = await post("/api/auth/request_otp", { mobile });
  if (!ok || !data.ok) return showErr("#mobile-err", data.error || "Could not send the code.");
  state.mobile = data.mobile;
  $("#otp-sent").innerHTML =
    `Sent to <b>+91 ${esc(data.mobile.slice(0, 5))} ${esc(data.mobile.slice(5))}</b> · ${esc(data.vendor_name)}`;
  $("#otp").value = "";
  showErr("#otp-err", "");
  step("otp");
}

// ------------------------------------------------------------------ step 2
$("#otp").addEventListener("input", (e) => { e.target.value = digits(e.target.value).slice(0, 6); });
$("#change-mobile").onclick = () => { state.mobile = null; showErr("#otp-err", ""); step("mobile"); };
$("#resend").onclick = () => state.mobile && sendOtp(state.mobile);

$("#otp-form").onsubmit = async (e) => {
  e.preventDefault();
  showErr("#otp-err", "");
  $("#otp-btn").disabled = true;
  try {
    const { ok, data } = await post("/api/auth/verify_otp", { mobile: state.mobile, otp: $("#otp").value });
    if (!ok || !data.ok) return showErr("#otp-err", data.error || "Could not verify that code.");
    window.location.href = "/";
  } finally { $("#otp-btn").disabled = false; }
};

step("mobile");
