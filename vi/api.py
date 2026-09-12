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
from .forecast import forecast
from .guard import ConfidentialityGuard
from .postmortem.service import build_post_mortem
from .priceband import buyer_purchase_band, winning_price_band
from .ranker.serve import models_ready, rank_for_event
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
    m = json.loads(Path("data/models/metrics.json").read_text()) if models_ready() else None
    return jsonify({
        "buyers": rows(c, "SELECT id, name FROM companies WHERE category='buyer' ORDER BY id"),
        "vendors": rows(c, "SELECT id, name, archetype FROM companies WHERE category='vendor' ORDER BY (archetype='generic'), name"),
        "policies": {r["company_id"]: r["policy"] for r in rows(c, "SELECT company_id, MAX(vendor_feedback_policy) AS policy FROM event_groups GROUP BY 1")},
        "models_ready": models_ready(), "model_metrics": m["models"] if m else None,
    })


# ----------------------------------------------------------------------------- buyer
@app.get("/api/buyer/<int:buyer>/events")
def buyer_events(buyer: int):
    c = db()
    return jsonify(rows(c, """
        SELECT tr.id AS trade_request_id, eg.title, tr.rfx_mode, tr.status, tr.bid_start_time, tr.bid_end_time,
               eg.vendor_feedback_policy AS policy,
               (SELECT pc.name FROM trade_products tp JOIN products p ON p.id=tp.product_id
                 JOIN product_categories pc ON pc.id=p.product_category_id WHERE tp.trade_request_id=tr.id LIMIT 1) AS category,
               (SELECT COUNT(*) FROM audiences a WHERE a.trade_request_id=tr.id) AS invited,
               (SELECT COUNT(DISTINCT vendor_company_id) FROM bids b WHERE b.trade_request_id=tr.id) AS bidders
        FROM trade_requests tr JOIN event_groups eg ON eg.id=tr.event_group_id
        WHERE eg.company_id=? ORDER BY tr.status='draft' DESC, tr.bid_start_time DESC LIMIT 40""", (buyer,)))


@app.get("/api/buyer/<int:buyer>/events/<int:tr>/recommendations")
def recommendations(buyer: int, tr: int):
    if not models_ready():
        abort(503, "models not trained — run `make train`")
    c = db()
    out = rank_for_event(c, tr, buyer)
    audit.log(c, "buyer", buyer, "rank_vendors", {"trade_request_id": tr}, None, [r["vendor_id"] for r in out["ranked"]])
    return jsonify(out)


@app.post("/api/buyer/<int:buyer>/events/<int:tr>/forecast")
def forecast_route(buyer: int, tr: int):
    body = request.get_json(force=True) or {}
    c = db()
    out = forecast(c, tr, buyer, [int(v) for v in body.get("vendor_ids", [])], int(body.get("threshold", 3)))
    audit.log(c, "buyer", buyer, "participation_forecast", body, None, out["expected_bids"])
    return jsonify(out)


@app.get("/api/buyer/<int:buyer>/vendors/<int:vendor>/scorecard")
def scorecard(buyer: int, vendor: int):
    c = db()
    v = one(c, "SELECT id, name, archetype FROM companies WHERE id=?", (vendor,)) or abort(404)
    prof = {w: one(c, "SELECT * FROM vendor_profiles WHERE buyer_company_id=? AND vendor_company_id=? AND category_id=0 AND window=?",
                   (buyer, vendor, w)) for w in ("90d", "365d", "all")}
    overall = {w: one(c, "SELECT * FROM vendor_profiles WHERE buyer_company_id=0 AND vendor_company_id=? AND category_id=0 AND window=?",
                      (vendor, w)) for w in ("90d", "365d", "all")}
    cats = rows(c, """SELECT pc.name AS category, vp.* FROM vendor_profiles vp JOIN product_categories pc ON pc.id=vp.category_id
                      WHERE vp.buyer_company_id=0 AND vp.vendor_company_id=? AND vp.window='all' AND vp.category_id<>0""", (vendor,))
    return jsonify({"vendor": v, "with_you": prof, "overall": overall, "by_category": cats})


@app.put("/api/buyer/<int:buyer>/policy")
def set_policy(buyer: int):
    policy = (request.get_json(force=True) or {}).get("policy")
    if policy not in ("none", "relative_only", "relative_plus_technical"):
        abort(400, "bad policy")
    c = db()
    c.execute("UPDATE event_groups SET vendor_feedback_policy=? WHERE company_id=?", (policy, buyer))
    c.commit()
    audit.log(c, "buyer", buyer, "set_vendor_feedback_policy", {"policy": policy}, None, policy)
    return jsonify({"buyer": buyer, "policy": policy})


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
