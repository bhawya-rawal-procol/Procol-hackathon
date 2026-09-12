"""The four deterministic 'why I lost' checks. No AI. Each returns
    {"signal": str, "severity": "high"|"medium"|"low"|"ok"|"na", "evidence": {...}}
Evidence contains ONLY the vendor's own data or relative figures. The guard runs afterwards anyway.
"""
from __future__ import annotations

import sqlite3

from ..db import one, rows

SEVERITY_ORDER = {"high": 3, "medium": 2, "low": 1, "ok": 0, "na": -1}

POSITION_SQL = """
WITH latest AS (
  SELECT b.vendor_company_id AS v, b.id AS bid_id, b.created_at
  FROM bids b
  WHERE b.trade_request_id = :tr
    AND b.created_at = (SELECT MAX(b2.created_at) FROM bids b2
                        WHERE b2.trade_request_id = b.trade_request_id AND b2.vendor_company_id = b.vendor_company_id)
),
tot AS (SELECT l.v, SUM(btp.price * btp.quantity) AS total
        FROM latest l JOIN bid_trade_products btp ON btp.bid_id = l.bid_id GROUP BY 1),
ranked AS (SELECT v, total, RANK() OVER (ORDER BY total) AS rnk, MIN(total) OVER () AS l1, COUNT(*) OVER () AS n
           FROM tot)
SELECT total AS own_total, rnk AS rank_position, n AS n_bidders,
       (total - l1) / l1 * 100.0 AS gap_to_l1_pct
FROM ranked WHERE v = :vendor
"""


def _hours(a: str | None, b: str | None, conn: sqlite3.Connection) -> float | None:
    if not a or not b:
        return None
    return conn.execute("SELECT (julianday(?) - julianday(?)) * 24", (b, a)).fetchone()[0]


def event_context(conn: sqlite3.Connection, vendor: int, tr: int) -> dict:
    ctx = one(conn, """
        SELECT tr.id AS tr_id, tr.rfx_mode, tr.bid_start_time, tr.bid_end_time, tr.closed_at,
               eg.company_id AS buyer_id, eg.title, eg.vendor_feedback_policy AS policy,
               (SELECT MIN(p.product_category_id) FROM trade_products tp JOIN products p ON p.id = tp.product_id
                 WHERE tp.trade_request_id = tr.id) AS category_id,
               (SELECT pc.name FROM trade_products tp JOIN products p ON p.id = tp.product_id
                 JOIN product_categories pc ON pc.id = p.product_category_id
                 WHERE tp.trade_request_id = tr.id LIMIT 1) AS category,
               EXISTS (SELECT 1 FROM proposals pr WHERE pr.trade_request_id = tr.id
                        AND pr.vendor_company_id = :vendor AND pr.status = 'selected') AS won,
               (SELECT invited_at FROM audiences a WHERE a.trade_request_id = tr.id AND a.vendor_company_id = :vendor) AS invited_at,
               (SELECT mail_opened_at FROM audiences a WHERE a.trade_request_id = tr.id AND a.vendor_company_id = :vendor) AS mail_opened_at
        FROM trade_requests tr JOIN event_groups eg ON eg.id = tr.event_group_id
        WHERE tr.id = :tr
    """, {"tr": tr, "vendor": vendor})
    if ctx is None:
        raise LookupError(f"trade_request {tr} not found")
    ctx["won"] = bool(ctx["won"])
    return ctx


def price_check(conn: sqlite3.Connection, vendor: int, ctx: dict) -> dict:
    pos = one(conn, POSITION_SQL, {"tr": ctx["tr_id"], "vendor": vendor})
    if pos is None:
        return {"signal": "You did not submit a bid on this event.", "severity": "na", "evidence": {}}
    hist = one(conn, """SELECT avg_gap_to_l1_pct, events_bid FROM vendor_profiles
                        WHERE buyer_company_id = 0 AND vendor_company_id = ? AND category_id = ? AND window = 'all'""",
               (vendor, ctx["category_id"])) or {}
    gap = round(pos["gap_to_l1_pct"], 1)
    ev = {"own_total": round(pos["own_total"], 2), "gap_to_l1_pct": gap, "rank_position": pos["rank_position"],
          "n_bidders": pos["n_bidders"], "hist_gap_to_l1_pct": round(hist["avg_gap_to_l1_pct"], 1) if hist.get("avg_gap_to_l1_pct") is not None else None,
          "hist_events_in_category": hist.get("events_bid")}
    if ctx["won"] or gap <= 0:
        return {"signal": "You were the lowest price (L1).", "severity": "ok", "evidence": ev}
    sev = "high" if gap > 8 else "medium" if gap > 3 else "low"
    sig = f"You were {gap}% above L1 — rank {pos['rank_position']} of {pos['n_bidders']}."
    if ev["hist_gap_to_l1_pct"] is not None and ev["hist_events_in_category"] and ev["hist_events_in_category"] >= 3:
        sig += f" Across your last {ev['hist_events_in_category']} {ctx['category']} events you averaged {ev['hist_gap_to_l1_pct']}% above L1."
    return {"signal": sig, "severity": sev, "evidence": ev}


def timing_check(conn: sqlite3.Connection, vendor: int, ctx: dict) -> dict:
    first = one(conn, "SELECT MIN(created_at) AS at FROM bids WHERE trade_request_id=? AND vendor_company_id=?",
                (ctx["tr_id"], vendor))
    first_at = first["at"] if first else None
    window_h = _hours(ctx["bid_start_time"], ctx["bid_end_time"], conn)
    resp_h = _hours(ctx["invited_at"], first_at, conn)
    ev = {"response_hours": round(resp_h, 1) if resp_h is not None else None,
          "bidding_window_hours": round(window_h, 1) if window_h else None,
          "bid_after_original_deadline": bool(first_at and first_at > ctx["bid_end_time"]),
          "mail_opened": ctx["mail_opened_at"] is not None, "counter_offers": [], "best_offers": []}
    sev, signals = "ok", []
    if first_at is None:
        ev["counter_offers"] = []
        return {"signal": "No bid submitted." + ("" if ev["mail_opened"] else " The invitation mail was never opened."),
                "severity": "high", "evidence": ev}
    if ev["bid_after_original_deadline"]:
        sev, s = "medium", "Your first bid landed after the original deadline — the buyer had to extend."
        signals.append(s)
    for ar in rows(conn, """SELECT change_type, created_at, ends_at, resolution, resolved_at FROM additional_requests
                            WHERE trade_request_id=? AND vendor_company_id=? ORDER BY created_at""", (ctx["tr_id"], vendor)):
        h = _hours(ar["created_at"], ar["resolved_at"], conn)
        item = {"resolution": ar["resolution"], "response_hours": round(h, 1) if h is not None else None,
                "window_hours": round(_hours(ar["created_at"], ar["ends_at"], conn), 1)}
        key = "counter_offers" if ar["change_type"] == "counter_offer_for_bid" else "best_offers"
        ev[key].append(item)
        label = "counter-offer" if key == "counter_offers" else "best-offer request"
        if ar["resolution"] == "expired":
            sev = "high"
            late_by = round(h - item["window_hours"], 0) if h else None
            signals.append(f"The buyer sent a {label} with a {item['window_hours']:.0f}h window; your reply arrived "
                           + (f"{late_by:.0f}h after it closed." if late_by else "after it closed."))
        elif ar["resolution"] == "rejected" and key == "counter_offers":
            signals.append(f"You declined the buyer's {label}.")
            sev = "medium" if sev == "ok" else sev
    if not signals:
        signals.append(f"You responded in {ev['response_hours']}h and met every negotiation window.")
    return {"signal": " ".join(signals), "severity": sev, "evidence": ev}


def technical_check(conn: sqlite3.Connection, vendor: int, ctx: dict) -> dict:
    secs = rows(conn, """SELECT e.section_key, e.score / e.max_score * 100.0 AS pct, e.score_type,
                                (SELECT AVG(e2.score / e2.max_score) * 100.0 FROM evaluation_scores e2
                                  WHERE e2.vendor_company_id = e.vendor_company_id AND e2.section_key = e.section_key
                                    AND e2.trade_request_id <> e.trade_request_id) AS own_hist_pct
                         FROM evaluation_scores e WHERE e.trade_request_id=? AND e.vendor_company_id=?""",
                (ctx["tr_id"], vendor))
    if not secs:
        return {"signal": "No technical evaluation on this event.", "severity": "na", "evidence": {"sections": []}}
    sections = [{"section_key": s["section_key"], "pct": round(s["pct"], 1), "score_type": s["score_type"],
                 "own_hist_pct": round(s["own_hist_pct"], 1) if s["own_hist_pct"] is not None else None} for s in secs]
    weakest = min(sections, key=lambda s: s["pct"])
    avg = round(sum(s["pct"] for s in sections) / len(sections), 1)
    sev = "high" if weakest["pct"] < 50 else "medium" if weakest["pct"] < 65 else "ok"
    sig = f"Your technical average was {avg}%. Weakest section: {weakest['section_key'].replace('_', ' ')} at {weakest['pct']}%."
    if weakest["own_hist_pct"] is not None and weakest["pct"] < weakest["own_hist_pct"] - 5:
        sig += f" That is below your own usual {weakest['own_hist_pct']}% there."
    return {"signal": sig, "severity": sev, "evidence": {"avg_pct": avg, "weakest_section": weakest["section_key"],
                                                          "weakest_pct": weakest["pct"], "sections": sections}}


def terms_check(conn: sqlite3.Connection, vendor: int, ctx: dict) -> dict:
    r = one(conn, """SELECT AVG(btp.payment_terms_days) AS pay, AVG(btp.delivery_days) AS deliv,
                            AVG(tp.asked_payment_terms_days) AS asked_pay, AVG(tp.asked_delivery_days) AS asked_deliv
                     FROM bids b JOIN bid_trade_products btp ON btp.bid_id = b.id
                     JOIN trade_products tp ON tp.id = btp.trade_product_id
                     WHERE b.trade_request_id=? AND b.vendor_company_id=?
                       AND b.created_at = (SELECT MAX(created_at) FROM bids WHERE trade_request_id=b.trade_request_id
                                           AND vendor_company_id=b.vendor_company_id)""", (ctx["tr_id"], vendor))
    if not r or r["pay"] is None:
        return {"signal": "No bid terms to assess.", "severity": "na", "evidence": {}}
    ev = {"payment_terms_days": round(r["pay"]), "asked_payment_terms_days": round(r["asked_pay"]),
          "delivery_days": round(r["deliv"]), "asked_delivery_days": round(r["asked_deliv"])}
    issues = []
    if ev["payment_terms_days"] > ev["asked_payment_terms_days"]:
        issues.append(f"you asked {ev['payment_terms_days']}-day payment terms against the buyer's {ev['asked_payment_terms_days']}")
    if ev["delivery_days"] > ev["asked_delivery_days"]:
        issues.append(f"you quoted {ev['delivery_days']}-day delivery against the buyer's {ev['asked_delivery_days']}")
    if not issues:
        return {"signal": "Your payment and delivery terms matched the buyer's ask.", "severity": "ok", "evidence": ev}
    return {"signal": "Terms were off: " + "; ".join(issues) + ".", "severity": "medium", "evidence": ev}


def run_all(conn: sqlite3.Connection, vendor: int, ctx: dict) -> dict[str, dict]:
    return {"price": price_check(conn, vendor, ctx), "timing": timing_check(conn, vendor, ctx),
            "technical": technical_check(conn, vendor, ctx), "terms": terms_check(conn, vendor, ctx)}
