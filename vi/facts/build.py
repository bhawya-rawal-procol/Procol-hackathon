"""Vendor-360 fact builder. Idempotent. No AI.

  profile(conn, buyer, vendor, category, since, until)  -> one metrics dict (the SQL in sql/vendor_profile.sql)
  build_all(conn, as_of)                                -> rebuilds vendor_profiles for every pair/category/window
"""
from __future__ import annotations

import argparse
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from ..db import DEFAULT_DB, connect, iso, now_iso, rows

SQL = (Path(__file__).parent / "sql" / "vendor_profile.sql").read_text()
WINDOWS = {"90d": 90, "365d": 365, "all": None}

METRIC_COLUMNS = [
    "invites", "events_bid", "counter_offers", "deliveries", "mail_open_rate", "bid_rate", "avg_response_hours", "win_rate", "avg_rank",
    "avg_gap_to_l1_pct", "counter_offer_response_rate", "counter_offer_accept_rate",
    "avg_counter_offer_response_hours", "late_counter_offer_rate", "extensions_caused",
    "on_time_delivery_rate", "qc_pass_rate", "avg_technical_pct", "weakest_technical_section",
    "weakest_technical_pct", "decline_reasons", "last_active_at",
]


def profile(conn: sqlite3.Connection, buyer: int, vendor: int, category: int,
            since: str | None, until: str | None) -> dict:
    """buyer=0 means across all buyers; category=0 means across all categories."""
    r = conn.execute(SQL, {"buyer": buyer, "vendor": vendor, "category": category,
                           "since": since, "until": until}).fetchone()
    return dict(r)


def _pairs(conn: sqlite3.Connection) -> list[tuple[int, int]]:
    """Every buyer×vendor pair that is either mapped or has ever been invited."""
    return [(r["b"], r["v"]) for r in rows(conn, """
        SELECT client_company_id AS b, dealing_with_company_id AS v FROM buyer_seller_company_mappings
        UNION
        SELECT eg.company_id, a.vendor_company_id
        FROM audiences a JOIN trade_requests tr ON tr.id = a.trade_request_id
        JOIN event_groups eg ON eg.id = tr.event_group_id
    """)]


def _categories_touched(conn: sqlite3.Connection, buyer: int, vendor: int) -> list[int]:
    return [r["cid"] for r in rows(conn, f"""
        SELECT DISTINCT p.product_category_id AS cid
        FROM audiences a JOIN trade_requests tr ON tr.id = a.trade_request_id
        JOIN event_groups eg ON eg.id = tr.event_group_id
        JOIN trade_products tp ON tp.trade_request_id = tr.id JOIN products p ON p.id = tp.product_id
        WHERE {"1=1" if buyer == 0 else "eg.company_id = ?"} AND a.vendor_company_id = ?
    """, (vendor,) if buyer == 0 else (buyer, vendor))]


def build_all(conn: sqlite3.Connection, as_of: datetime | None = None) -> int:
    as_of_iso = iso(as_of) if as_of else None
    conn.execute("DELETE FROM vendor_profiles")
    n = 0
    vendors = [r["id"] for r in rows(conn, "SELECT id FROM companies WHERE category='vendor'")]
    for buyer, vendor in _pairs(conn) + [(0, v) for v in vendors]:      # buyer 0 = across all buyers
        for category in [0, *_categories_touched(conn, buyer, vendor)]:  # category 0 = all
            per_window: dict[str, dict] = {}
            for window, days in WINDOWS.items():
                since = None
                if days:
                    base = as_of or datetime.fromisoformat(now_iso())
                    since = iso(base - timedelta(days=days))
                per_window[window] = profile(conn, buyer, vendor, category, since, as_of_iso)
            for window, m in per_window.items():
                trend = None
                a, b = per_window["90d"]["on_time_delivery_rate"], per_window["365d"]["on_time_delivery_rate"]
                if a is not None and b is not None:
                    trend = round((a - b) * 100, 1)
                conn.execute(f"""
                    INSERT OR REPLACE INTO vendor_profiles
                    (buyer_company_id, vendor_company_id, category_id, window, {", ".join(METRIC_COLUMNS)},
                     trend_90d_vs_365d, built_at)
                    VALUES (?, ?, ?, ?, {", ".join("?" * len(METRIC_COLUMNS))}, ?, ?)
                """, (buyer, vendor, category, window, *[m[c] for c in METRIC_COLUMNS], trend, now_iso()))
                n += 1
    conn.commit()
    return n


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--as-of", default="2026-09-11T09:00:00+00:00")
    args = ap.parse_args()
    c = connect(args.db)
    count = build_all(c, datetime.fromisoformat(args.as_of))
    print(f"vendor_profiles rebuilt: {count} rows")
    for r in rows(c, """
        SELECT co.archetype, vp.window, vp.invites, ROUND(vp.bid_rate,2) bid_rate,
               ROUND(vp.avg_gap_to_l1_pct,1) gap, ROUND(vp.win_rate,2) win,
               ROUND(vp.late_counter_offer_rate,2) late_co, ROUND(vp.on_time_delivery_rate,2) on_time,
               vp.trend_90d_vs_365d trend, vp.weakest_technical_section weakest
        FROM vendor_profiles vp JOIN companies co ON co.id = vp.vendor_company_id
        WHERE co.archetype <> 'generic' AND vp.category_id = 0 AND vp.buyer_company_id = 0
        ORDER BY co.archetype, vp.window"""):
        print("  ", dict(r))
