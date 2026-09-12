"""Vendor-facing read models: my events, my habits, my profile/compliance. No AI.
Everything here is the vendor's OWN data; the API still runs habits through the guard."""
from __future__ import annotations

import json
import sqlite3

from .db import one, rows


def vendor_events(conn: sqlite3.Connection, vendor: int) -> list[dict]:
    return rows(conn, """
        SELECT tr.id AS trade_request_id, eg.title, tr.rfx_mode, tr.closed_at, eg.company_id AS buyer_id,
               bc.name AS buyer, eg.vendor_feedback_policy AS policy,
               (SELECT pc.name FROM trade_products tp JOIN products p ON p.id=tp.product_id
                 JOIN product_categories pc ON pc.id=p.product_category_id WHERE tp.trade_request_id=tr.id LIMIT 1) AS category,
               EXISTS (SELECT 1 FROM bids b WHERE b.trade_request_id=tr.id AND b.vendor_company_id=a.vendor_company_id) AS bid,
               EXISTS (SELECT 1 FROM proposals p WHERE p.trade_request_id=tr.id AND p.vendor_company_id=a.vendor_company_id
                        AND p.status='selected') AS won,
               EXISTS (SELECT 1 FROM additional_requests ar WHERE ar.trade_request_id=tr.id
                        AND ar.vendor_company_id=a.vendor_company_id AND ar.resolution='expired') AS missed_window
        FROM audiences a JOIN trade_requests tr ON tr.id=a.trade_request_id
        JOIN event_groups eg ON eg.id=tr.event_group_id JOIN companies bc ON bc.id=eg.company_id
        WHERE a.vendor_company_id=? AND tr.status='closed' ORDER BY tr.closed_at DESC LIMIT 40""", (vendor,))


def vendor_habits(conn: sqlite3.Connection, vendor: int) -> dict:
    p = one(conn, "SELECT * FROM vendor_profiles WHERE buyer_company_id=0 AND vendor_company_id=? AND category_id=0 AND window='all'",
            (vendor,)) or {}
    p90 = one(conn, "SELECT * FROM vendor_profiles WHERE buyer_company_id=0 AND vendor_company_id=? AND category_id=0 AND window='90d'",
              (vendor,)) or {}
    short_lead = one(conn, """
        SELECT AVG(EXISTS (SELECT 1 FROM bids b WHERE b.trade_request_id=a.trade_request_id AND b.vendor_company_id=a.vendor_company_id)) AS bid_rate,
               COUNT(*) AS n
        FROM audiences a JOIN trade_requests tr ON tr.id=a.trade_request_id
        WHERE a.vendor_company_id=? AND julianday(tr.bid_end_time)-julianday(tr.bid_start_time) <= 3""", (vendor,)) or {}
    long_lead = one(conn, """
        SELECT AVG(EXISTS (SELECT 1 FROM bids b WHERE b.trade_request_id=a.trade_request_id AND b.vendor_company_id=a.vendor_company_id)) AS bid_rate,
               COUNT(*) AS n
        FROM audiences a JOIN trade_requests tr ON tr.id=a.trade_request_id
        WHERE a.vendor_company_id=? AND julianday(tr.bid_end_time)-julianday(tr.bid_start_time) > 3""", (vendor,)) or {}
    decline = json.loads(p.get("decline_reasons") or "{}")
    return {
        "invites": p.get("invites"), "mail_open_rate": p.get("mail_open_rate"), "bid_rate": p.get("bid_rate"),
        "avg_response_hours": p.get("avg_response_hours"), "win_rate": p.get("win_rate"),
        "avg_gap_to_l1_pct": p.get("avg_gap_to_l1_pct"),
        "counter_offers": p.get("counter_offers"), "counter_offer_response_rate": p.get("counter_offer_response_rate"),
        "late_counter_offer_rate": p.get("late_counter_offer_rate"),
        "avg_counter_offer_response_hours": p.get("avg_counter_offer_response_hours"),
        "extensions_caused": p.get("extensions_caused"),
        "short_lead": {"bid_rate": short_lead.get("bid_rate"), "n": short_lead.get("n")},
        "long_lead": {"bid_rate": long_lead.get("bid_rate"), "n": long_lead.get("n")},
        "decline_reasons": decline,
        "last_90d": {"invites": p90.get("invites"), "bid_rate": p90.get("bid_rate"), "win_rate": p90.get("win_rate")},
        "technical": _technical_by_policy(conn, vendor),
        "delivery": {"on_time_rate": p.get("on_time_delivery_rate"), "qc_pass_rate": p.get("qc_pass_rate"),
                     "trend_90d_vs_365d": p.get("trend_90d_vs_365d"), "deliveries": p.get("deliveries")},
    }


def _technical_by_policy(conn: sqlite3.Connection, vendor: int) -> dict | None:
    """Own technical averages using ONLY unrestricted scores from buyers whose policy shares technical feedback."""
    secs = rows(conn, """SELECT e.section_key, AVG(e.score/e.max_score)*100 AS pct FROM evaluation_scores e
                         JOIN trade_requests tr ON tr.id=e.trade_request_id JOIN event_groups eg ON eg.id=tr.event_group_id
                         WHERE e.vendor_company_id=? AND e.score_type='unrestricted'
                           AND eg.vendor_feedback_policy='relative_plus_technical' GROUP BY 1 ORDER BY pct""", (vendor,))
    if not secs:
        return None
    return {"avg_pct": sum(s["pct"] for s in secs) / len(secs), "weakest_section": secs[0]["section_key"],
            "weakest_pct": secs[0]["pct"], "sections": [{"section_key": s["section_key"], "pct": round(s["pct"], 1)} for s in secs]}


def vendor_profile_card(conn: sqlite3.Connection, vendor: int) -> dict:
    v = one(conn, "SELECT id, name, gst_no, archetype FROM companies WHERE id=?", (vendor,))
    mappings = rows(conn, """SELECT bc.name AS buyer, m.status, m.vendor_code FROM buyer_seller_company_mappings m
                             JOIN companies bc ON bc.id=m.client_company_id WHERE m.dealing_with_company_id=?""", (vendor,))
    cats = rows(conn, """SELECT DISTINCT pc.name FROM bids b JOIN trade_products tp ON tp.trade_request_id=b.trade_request_id
                         JOIN products p ON p.id=tp.product_id JOIN product_categories pc ON pc.id=p.product_category_id
                         WHERE b.vendor_company_id=? ORDER BY 1""", (vendor,))
    fields = {"gst_no": bool(v["gst_no"]), "bank_details": vendor % 3 != 0, "msme_certificate": vendor % 4 != 0,
              "iso_certificate": vendor % 5 == 0, "catalogue_uploaded": vendor % 2 == 0}
    complete = round(100 * sum(fields.values()) / len(fields))
    return {"vendor": v, "buyers": mappings, "categories": [c["name"] for c in cats],
            "completeness_pct": complete, "fields": fields,
            "pending_onboarding": [m["buyer"] for m in mappings if m["status"] in ("invited", "onboarding")],
            "note": "Profile fields are illustrative in the prototype (Procol: vendor onboarding datasources + Attestr validations)."}
