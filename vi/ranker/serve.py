"""Serving: rank eligible vendors for an event, with score + reasons, plus the discovery slot.

Discovery handles the never-invited problem explicitly: a ranker trained on invited vendors can never
surface a vendor the buyer has never invited, so we add vendors who are active in this category with
>= 2 OTHER buyers, labelled 'discovery' and shown without a model score.
"""
from __future__ import annotations

import json
import pickle
import sqlite3
from functools import lru_cache
from pathlib import Path

import numpy as np

from ..db import rows
from .features import event_features, vendor_vector
from .reasons import top_reasons

MODEL_DIR = Path("data/models")
DISCOVERY_MIN_OTHER_BUYERS = 2


@lru_cache(maxsize=1)
def _models():
    with open(MODEL_DIR / "p_bid.pkl", "rb") as f:
        p_bid = pickle.load(f)
    with open(MODEL_DIR / "p_top3.pkl", "rb") as f:
        p_top3 = pickle.load(f)
    meta = json.loads((MODEL_DIR / "metrics.json").read_text())
    return p_bid, p_top3, meta["feature_means"], meta


def models_ready() -> bool:
    return (MODEL_DIR / "p_bid.pkl").exists() and (MODEL_DIR / "p_top3.pkl").exists()


def eligible_vendors(conn: sqlite3.Connection, buyer: int, category_id: int) -> list[dict]:
    """Mapped (approved/onboarding) vendors of this buyer who have ever been invited or bid in the category, anywhere."""
    return rows(conn, """
        SELECT c.id, c.name, c.archetype, m.status AS mapping_status
        FROM buyer_seller_company_mappings m JOIN companies c ON c.id = m.dealing_with_company_id
        WHERE m.client_company_id = ? AND m.status IN ('approved', 'onboarding')
          AND EXISTS (SELECT 1 FROM audiences a JOIN trade_requests tr ON tr.id = a.trade_request_id
                      JOIN trade_products tp ON tp.trade_request_id = tr.id JOIN products p ON p.id = tp.product_id
                      WHERE a.vendor_company_id = c.id AND p.product_category_id = ?)
        ORDER BY c.name""", (buyer, category_id))


def discovery_vendors(conn: sqlite3.Connection, buyer: int, category_id: int) -> list[dict]:
    """Vendors NOT mapped to this buyer, active in the category with >= 2 other buyers. No names of those buyers."""
    return rows(conn, """
        SELECT c.id, c.name, c.archetype, COUNT(DISTINCT eg.company_id) AS other_buyers,
               COUNT(DISTINCT b.trade_request_id) AS events_bid
        FROM companies c
        JOIN bids b ON b.vendor_company_id = c.id
        JOIN trade_requests tr ON tr.id = b.trade_request_id
        JOIN event_groups eg ON eg.id = tr.event_group_id
        JOIN trade_products tp ON tp.trade_request_id = tr.id JOIN products p ON p.id = tp.product_id
        WHERE c.category = 'vendor' AND p.product_category_id = ? AND eg.company_id <> ?
          AND NOT EXISTS (SELECT 1 FROM buyer_seller_company_mappings m
                          WHERE m.client_company_id = ? AND m.dealing_with_company_id = c.id)
        GROUP BY c.id HAVING other_buyers >= ?
        ORDER BY events_bid DESC LIMIT 5""", (category_id, buyer, buyer, DISCOVERY_MIN_OTHER_BUYERS))


def score_vendor(conn: sqlite3.Connection, buyer: int, vendor: int, ev: dict, category: str) -> dict:
    p_bid, p_top3, means, _ = _models()
    x, raw = vendor_vector(conn, buyer, vendor, ev, as_of=None)
    xa = np.array([x])
    pb = float(p_bid.predict_proba(xa)[0, 1])
    pt = float(p_top3.predict_proba(xa)[0, 1])
    return {"p_bid": round(pb, 3), "p_top3": round(pt, 3), "score": round(pt, 3),
            "reasons": top_reasons(p_top3, x, means, raw, category),
            "cold_start": not (raw["pair"].get("invites") or raw["cat"].get("invites"))}


def rank_for_event(conn: sqlite3.Connection, tr_id: int, buyer: int, n_invited: int | None = None) -> dict:
    ev = event_features(conn, tr_id, n_invited)
    category = conn.execute("SELECT name FROM product_categories WHERE id=?", (ev["category_id"],)).fetchone()[0]
    ranked = []
    for v in eligible_vendors(conn, buyer, ev["category_id"]):
        s = score_vendor(conn, buyer, v["id"], ev, category)
        ranked.append({"vendor_id": v["id"], "name": v["name"], "archetype": v["archetype"],
                       "mapping_status": v["mapping_status"], **s})
    ranked.sort(key=lambda r: -r["score"])
    for i, r in enumerate(ranked, start=1):
        r["rank"] = i
    disc = [{"vendor_id": d["id"], "name": d["name"], "archetype": d["archetype"], "discovery": True,
             "note": f"Active in {category} with {d['other_buyers']} other buyers ({d['events_bid']} events). Never invited by you."}
            for d in discovery_vendors(conn, buyer, ev["category_id"])]
    return {"trade_request_id": tr_id, "category": category, "category_id": ev["category_id"],
            "lead_days": round(ev["lead_days"], 1), "lot_value": round(ev["lot_value"] or 0, 2),
            "ranked": ranked, "discovery": disc, "model": _models()[3]["models"]["p_top3"]}
