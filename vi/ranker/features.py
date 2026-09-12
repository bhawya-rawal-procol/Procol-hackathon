"""Feature assembly for the ranker. Reuses the fact SQL with :until = event bid_start_time so
training rows only see history that existed before the event opened (no leakage)."""
from __future__ import annotations

import math
import sqlite3

from ..db import one
from ..facts.build import profile

PAIR_FEATURES = ["invites", "bid_rate", "mail_open_rate", "avg_response_hours", "win_rate", "avg_gap_to_l1_pct",
                 "late_counter_offer_rate", "on_time_delivery_rate", "qc_pass_rate", "avg_technical_pct"]
CAT_FEATURES = ["invites", "bid_rate", "win_rate", "avg_gap_to_l1_pct", "events_bid", "avg_response_hours"]
EVENT_FEATURES = ["lot_value_log", "lead_days", "n_invited", "is_rfp", "is_auction"]

DEFAULTS = {"invites": 0, "bid_rate": 0.5, "mail_open_rate": 0.7, "avg_response_hours": 30, "win_rate": 0.2,
            "avg_gap_to_l1_pct": 4.0, "late_counter_offer_rate": 0.2, "on_time_delivery_rate": 0.85,
            "qc_pass_rate": 0.9, "avg_technical_pct": 72, "events_bid": 0}

FEATURE_NAMES = ([f"pair_{f}" for f in PAIR_FEATURES] + ["pair_has_history"]
                 + [f"cat_{f}" for f in CAT_FEATURES] + ["cat_has_history"] + EVENT_FEATURES)


def event_features(conn: sqlite3.Connection, tr_id: int, n_invited: int | None = None) -> dict:
    e = one(conn, """
        SELECT tr.id, tr.rfx_mode, tr.bid_start_time, tr.bid_end_time, eg.company_id AS buyer_id,
               (julianday(tr.bid_end_time) - julianday(tr.bid_start_time)) AS lead_days,
               (SELECT SUM(tp.target_price * tp.quantity) FROM trade_products tp WHERE tp.trade_request_id = tr.id) AS lot_value,
               (SELECT MIN(p.product_category_id) FROM trade_products tp JOIN products p ON p.id = tp.product_id
                 WHERE tp.trade_request_id = tr.id) AS category_id,
               (SELECT COUNT(*) FROM audiences a WHERE a.trade_request_id = tr.id) AS invited
        FROM trade_requests tr JOIN event_groups eg ON eg.id = tr.event_group_id WHERE tr.id = ?""", (tr_id,))
    e["n_invited"] = n_invited if n_invited is not None else e["invited"]
    return e


def vendor_vector(conn: sqlite3.Connection, buyer: int, vendor: int, ev: dict, as_of: str | None) -> tuple[list[float], dict]:
    """Returns (numeric feature vector, raw dict used for reason codes)."""
    pair = profile(conn, buyer, vendor, 0, None, as_of)
    cat = profile(conn, 0, vendor, ev["category_id"], None, as_of)
    raw = {"pair": pair, "cat": cat, "event": ev}
    x: list[float] = []
    for f in PAIR_FEATURES:
        x.append(_num(pair.get(f), f))
    x.append(1.0 if (pair.get("invites") or 0) > 0 else 0.0)
    for f in CAT_FEATURES:
        x.append(_num(cat.get(f), f))
    x.append(1.0 if (cat.get("invites") or 0) > 0 else 0.0)
    x += [math.log1p(ev["lot_value"] or 0), float(ev["lead_days"] or 0), float(ev["n_invited"] or 0),
          1.0 if ev["rfx_mode"] == "rfp" else 0.0, 1.0 if ev["rfx_mode"] == "auction" else 0.0]
    return x, raw


def _num(v, f: str) -> float:
    return float(v) if v is not None else float(DEFAULTS.get(f, 0.0))
