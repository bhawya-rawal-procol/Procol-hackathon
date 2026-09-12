"""Demo server. Flask, plain JSON, one HTML page. `python -m vi.api --db data/vendor_intelligence.db`

Buyer endpoints never pass through the guard (the buyer owns the event data).
Vendor endpoints ALWAYS pass through the guard — see vendor_* routes.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from flask import Flask, abort, jsonify, request, send_from_directory

from . import audit
from .db import DEFAULT_DB, connect, one, rows
from .guard import ConfidentialityGuard
from .postmortem.service import build_post_mortem
from .priceband import buyer_purchase_band, winning_price_band
from .vendor_views import vendor_events, vendor_habits, vendor_profile_card
from .chat.service import chat as chat_turn, greeting as chat_greeting, history as chat_history, connect_claude, engine_status

UI_DIR = Path(__file__).resolve().parent.parent / "ui"
app = Flask(__name__, static_folder=None)
DB_PATH = os.environ.get("VI_DB", DEFAULT_DB)


def db():
    return connect(DB_PATH)


# ----------------------------------------------------------------------------- shared
@app.get("/")
def index():
    return send_from_directory(UI_DIR, "index.html")


@app.get("/ui/<path:name>")
def ui_asset(name: str):
    return send_from_directory(UI_DIR, name)


@app.get("/api/meta")
def meta():
    c = db()
    return jsonify({
        "vendors": rows(c, "SELECT id, name, archetype FROM companies WHERE category='vendor' ORDER BY (archetype='generic'), name"),
    })


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
    c = db()
    return jsonify(rows(c, "SELECT * FROM audit_log ORDER BY id DESC LIMIT 30"))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--port", type=int, default=int(os.environ.get("VI_PORT", 8000)))
    args = ap.parse_args()
    DB_PATH = args.db
    os.environ["VI_DB"] = args.db
    print(f"Vendor Intelligence demo → http://127.0.0.1:{args.port}   (db: {args.db})")
    app.run(host="127.0.0.1", port=args.port, debug=False)
