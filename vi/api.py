"""Demo server. Flask, plain JSON, one HTML page. `python -m vi.api --db data/vendor_intelligence.db`

A vendor signs in with mobile + OTP (`vi/auth.py`) and the session carries exactly one
vendor_company_id. Two layers stand between a vendor and anyone else's data:

  1. the session check below — every /api/vendor/<id>/… route whose id is not the session's is 403,
     so changing the number in the URL gets you nothing and is written to audit_log;
  2. the ConfidentialityGuard, unchanged, on every vendor-facing payload.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import secrets
from pathlib import Path

from flask import Flask, abort, jsonify, redirect, request, send_from_directory, session

from . import audit, auth
from .db import DEFAULT_DB, connect, one, rows
from .guard import ConfidentialityGuard
from .postmortem.service import build_post_mortem
from .priceband import buyer_purchase_band, winning_price_band
from .vendor_views import vendor_events, vendor_habits, vendor_profile_card
from .chat.service import chat as chat_turn, greeting as chat_greeting, history as chat_history, connect_claude, engine_status

UI_DIR = Path(__file__).resolve().parent.parent / "ui"
app = Flask(__name__, static_folder=None)
# A fresh key per process signs the session cookie; set VI_SECRET to keep sessions across restarts.
app.secret_key = os.environ.get("VI_SECRET") or secrets.token_hex(32)
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax")
DB_PATH = os.environ.get("VI_DB", DEFAULT_DB)

VENDOR_ROUTE = re.compile(r"^/api/vendor/(\d+)(/|$)")


def db():
    return connect(DB_PATH)


# ----------------------------------------------------------------------------- session
def current_vendor() -> int | None:
    v = session.get("vendor_id")
    return int(v) if v is not None else None


@app.before_request
def enforce_vendor_session():
    """One gate in front of everything: no session → no data; wrong vendor in the URL → 403."""
    path = request.path
    if path == "/login" or path.startswith("/ui/") or path.startswith("/api/auth/"):
        return None

    vendor = current_vendor()
    if vendor is None:
        return redirect("/login") if path == "/" else (jsonify({"error": "not_authenticated"}), 401)

    m = VENDOR_ROUTE.match(path)
    if m and int(m.group(1)) != vendor:
        audit.log(db(), "vendor", vendor, "cross_vendor_denied",
                  {"path": path, "requested_vendor": int(m.group(1))}, [], None)
        return jsonify({"error": "forbidden", "detail": "You are signed in as a different vendor."}), 403
    return None


# ----------------------------------------------------------------------------- auth
@app.get("/login")
def login_page():
    return send_from_directory(UI_DIR, "login.html")


@app.post("/api/auth/request_otp")
def auth_request_otp():
    body = request.get_json(force=True) or {}
    out = auth.request_otp(body.get("mobile"))
    return jsonify(out), (200 if out["ok"] else 404)


@app.post("/api/auth/verify_otp")
def auth_verify_otp():
    body = request.get_json(force=True) or {}
    c = db()
    out = auth.verify_otp(c, body.get("mobile"), body.get("otp"))
    if not out["ok"]:
        return jsonify(out), 401
    session.clear()                                   # never carry one vendor's session into another
    session["vendor_id"] = out["vendor_id"]
    session["mobile"] = out["mobile"]
    session["vendor_name"] = out["vendor_name"]
    session.permanent = False
    audit.log(c, "vendor", out["vendor_id"], "login", {"mobile": out["mobile"]}, [], None)
    return jsonify(out)


@app.post("/api/auth/logout")
def auth_logout():
    session.clear()
    return jsonify({"ok": True})


@app.get("/api/session")
def session_info():
    c = db()
    v = current_vendor()
    row = one(c, "SELECT id, name, archetype FROM companies WHERE id=?", (v,)) or abort(404)
    return jsonify({"vendor": row, "mobile": session.get("mobile")})


# ----------------------------------------------------------------------------- shared
@app.get("/")
def index():
    return send_from_directory(UI_DIR, "index.html")


@app.get("/ui/<path:name>")
def ui_asset(name: str):
    return send_from_directory(UI_DIR, name)


@app.get("/api/meta")
def meta():
    """Only the signed-in vendor. The old vendor picker is gone — there is no list to hand out."""
    c = db()
    v = current_vendor()
    return jsonify({"vendors": rows(c, "SELECT id, name, archetype FROM companies WHERE id=?", (v,))})


# ----------------------------------------------------------------------------- vendor (guarded)
def _guard(c, vendor: int, buyer: int | None) -> ConfidentialityGuard:
    own = one(c, "SELECT name FROM companies WHERE id=?", (vendor,)) or abort(404)
    buyer_name = one(c, "SELECT name FROM companies WHERE id=?", (buyer,))["name"] if buyer else ""
    others = [r["name"] for r in rows(c, "SELECT name FROM companies WHERE category='vendor' AND id<>?", (vendor,))]
    return ConfidentialityGuard(vendor, own["name"], buyer_name, others)


@app.get("/api/vendor/<int:vendor>/events")
def vendor_events_route(vendor: int):
    c = db()
    return jsonify(vendor_events(c, vendor))


@app.get("/api/vendor/<int:vendor>/events/<int:tr>/postmortem")
def postmortem(vendor: int, tr: int):
    c = db()
    return jsonify(build_post_mortem(c, vendor, tr, force=request.args.get("force") == "1"))


@app.get("/api/vendor/<int:vendor>/priceband")
def priceband(vendor: int):
    c = db()
    out = winning_price_band(c, vendor)
    res = _guard(c, vendor, None).apply(out, "relative_only")
    audit.log(c, "vendor", vendor, "price_band", None, res.audit, res.payload)
    return jsonify(res.payload)


@app.get("/api/vendor/<int:vendor>/buyer/<int:buyer>/purchase_band/<int:category>")
def purchase_band(vendor: int, buyer: int, category: int):
    c = db()
    policy = one(c, "SELECT MAX(vendor_feedback_policy) AS p FROM event_groups WHERE company_id=?", (buyer,))["p"]
    res = _guard(c, vendor, buyer).apply(buyer_purchase_band(c, buyer, category), policy)
    audit.log(c, "vendor", vendor, "buyer_purchase_band", {"buyer": buyer, "category": category}, res.audit, res.payload)
    return jsonify({"policy": policy, "data": res.payload, "guard_audit": res.audit})


def _vendor_wide_policy(c, vendor: int) -> str:
    """Habits span many buyers. Own behaviour (open rate, response time) is always the vendor's to see;
    own technical averages come from buyers' evaluations, so they are shown only if EVERY buyer allows it."""
    ps = [r["p"] for r in rows(c, """SELECT DISTINCT eg.vendor_feedback_policy AS p FROM audiences a
                                     JOIN trade_requests tr ON tr.id=a.trade_request_id JOIN event_groups eg ON eg.id=tr.event_group_id
                                     WHERE a.vendor_company_id=?""", (vendor,))]
    return "relative_plus_technical" if ps and all(p == "relative_plus_technical" for p in ps) else "relative_only"


@app.get("/api/vendor/<int:vendor>/habits")
def habits(vendor: int):
    c = db()
    policy = _vendor_wide_policy(c, vendor)
    # technical block is already filtered per-buyer at row level (see vendor_views._technical_by_policy)
    res = _guard(c, vendor, None).apply(vendor_habits(c, vendor), "relative_plus_technical")
    audit.log(c, "vendor", vendor, "habits", {"policy": policy}, res.audit, res.payload)
    return jsonify({"policy": policy, **res.payload})


@app.get("/api/vendor/<int:vendor>/profile")
def profile_card(vendor: int):
    c = db()
    return jsonify(vendor_profile_card(c, vendor))


# ----------------------------------------------------------------------------- vendor chat (guarded)
@app.get("/api/vendor/<int:vendor>/chat/greeting")
def chat_greet(vendor: int):
    c = db()
    return jsonify(chat_greeting(c, vendor))


@app.post("/api/vendor/<int:vendor>/chat")
def chat_post(vendor: int):
    body = request.get_json(force=True) or {}
    c = db()
    out = chat_turn(c, vendor, body.get("session_id"), body.get("message", ""), force_offline=bool(body.get("offline")))
    return jsonify(out)


@app.get("/api/vendor/<int:vendor>/chat/<session_id>")
def chat_hist(vendor: int, session_id: str):
    c = db()
    return jsonify(chat_history(c, session_id, vendor))


@app.get("/api/settings/claude")
def claude_status():
    return jsonify(engine_status())


@app.post("/api/settings/claude")
def claude_connect():
    """Local prototype only: hold the key in server memory so the demo can switch to Claude without a restart."""
    body = request.get_json(force=True) or {}
    return jsonify(connect_claude(body.get("api_key"), body.get("model")))


@app.get("/api/audit")
def audit_tail():
    """Your own trail only — the log holds every vendor's, so it is filtered to the session."""
    c = db()
    return jsonify(rows(c, "SELECT * FROM audit_log WHERE persona='vendor' AND actor_id=? ORDER BY id DESC LIMIT 30",
                        (current_vendor(),)))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--port", type=int, default=int(os.environ.get("VI_PORT", 8000)))
    args = ap.parse_args()
    DB_PATH = args.db
    os.environ["VI_DB"] = args.db
    print(f"Vendor Intelligence demo → http://127.0.0.1:{args.port}   (db: {args.db})")
    app.run(host="127.0.0.1", port=args.port, debug=False)
