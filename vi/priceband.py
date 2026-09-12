"""'My winning price band' — computed from the vendor's OWN bid history only. No AI.

For each category: bucket the vendor's final bids by % gap to L1, and report win rate per bucket.
The vendor learns "when I am within 3% of the lowest bid I win 60%; above 8% I win 5%" without
ever seeing a competitor's number. Optionally (buyer policy permitting) adds the buyer's own
historical purchase band from purchase_price_records, k-anonymised over distinct vendors.
"""
from __future__ import annotations

import sqlite3

from .db import rows

BUCKETS = [("≤0% (L1)", None, 0.0), ("0–3%", 0.0, 3.0), ("3–6%", 3.0, 6.0), ("6–10%", 6.0, 10.0), (">10%", 10.0, None)]

OWN_BIDS_SQL = """
WITH ev AS (
  SELECT tr.id AS tr_id, eg.company_id AS buyer_id,
         (SELECT MIN(p.product_category_id) FROM trade_products tp JOIN products p ON p.id = tp.product_id
           WHERE tp.trade_request_id = tr.id) AS cat_id
  FROM trade_requests tr JOIN event_groups eg ON eg.id = tr.event_group_id
  WHERE tr.status = 'closed' AND (:buyer = 0 OR eg.company_id = :buyer)
),
latest AS (
  SELECT b.trade_request_id AS tr_id, b.vendor_company_id AS v, b.id AS bid_id
  FROM bids b JOIN ev ON ev.tr_id = b.trade_request_id
  WHERE b.created_at = (SELECT MAX(b2.created_at) FROM bids b2
                        WHERE b2.trade_request_id = b.trade_request_id AND b2.vendor_company_id = b.vendor_company_id)
),
tot AS (SELECT l.tr_id, l.v, SUM(btp.price * btp.quantity) AS total
        FROM latest l JOIN bid_trade_products btp ON btp.bid_id = l.bid_id GROUP BY 1, 2),
ranked AS (SELECT tr_id, v, total, MIN(total) OVER (PARTITION BY tr_id) AS l1 FROM tot)
SELECT ev.cat_id, pc.name AS category, (r.total - r.l1) / r.l1 * 100.0 AS gap_pct,
       EXISTS (SELECT 1 FROM proposals p WHERE p.trade_request_id = r.tr_id AND p.vendor_company_id = :vendor
                AND p.status = 'selected') AS won
FROM ranked r JOIN ev ON ev.tr_id = r.tr_id JOIN product_categories pc ON pc.id = ev.cat_id
WHERE r.v = :vendor
"""


def _bucket(gap: float) -> str:
    for label, lo, hi in BUCKETS:
        if (lo is None or gap > lo) and (hi is None or gap <= hi):
            return label
    return BUCKETS[-1][0]


def winning_price_band(conn: sqlite3.Connection, vendor: int, buyer: int = 0) -> dict:
    per_cat: dict[str, dict[str, dict]] = {}
    for r in rows(conn, OWN_BIDS_SQL, {"vendor": vendor, "buyer": buyer}):
        b = _bucket(r["gap_pct"])
        cell = per_cat.setdefault(r["category"], {lbl: {"bids": 0, "wins": 0} for lbl, _, _ in BUCKETS})[b]
        cell["bids"] += 1
        cell["wins"] += int(bool(r["won"]))
    out = []
    for cat, cells in sorted(per_cat.items()):
        buckets = [{"bucket": lbl, "bids": c["bids"], "wins": c["wins"],
                    "win_rate": round(c["wins"] / c["bids"], 2) if c["bids"] else None}
                   for lbl, c in cells.items()]
        total = sum(c["bids"] for c in cells.values())
        out.append({"category": cat, "total_bids": total, "buckets": buckets, "insight": _insight(cat, buckets)})
    return {"vendor_id": vendor, "scope": "all buyers" if buyer == 0 else f"buyer {buyer}", "categories": out}


def _insight(cat: str, buckets: list[dict]) -> str:
    close = [b for b in buckets if b["bucket"] in ("≤0% (L1)", "0–3%") and b["bids"]]
    far = [b for b in buckets if b["bucket"] in ("6–10%", ">10%") and b["bids"]]
    if not close and not far:
        return f"Not enough {cat} history yet."
    parts = []
    if close:
        bids = sum(b["bids"] for b in close); wins = sum(b["wins"] for b in close)
        parts.append(f"within 3% of L1 you won {round(100 * wins / bids)}% ({wins}/{bids})")
    if far:
        bids = sum(b["bids"] for b in far); wins = sum(b["wins"] for b in far)
        parts.append(f"more than 6% above L1 you won {round(100 * wins / bids)}% ({wins}/{bids})")
    return f"In {cat}: " + "; ".join(parts) + "."


def buyer_purchase_band(conn: sqlite3.Connection, buyer: int, category_id: int) -> dict:
    """Buyer's historical unit-price band per item, from ERP purchase_price_records.
    k = distinct vendors behind the number; the guard strips any *_median without k >= 3."""
    items = []
    for r in rows(conn, """
        SELECT ppr.item_code, p.name, COUNT(*) AS n, COUNT(DISTINCT ppr.vendor_code) AS k,
               MIN(ppr.price) AS lo, MAX(ppr.price) AS hi
        FROM purchase_price_records ppr
        JOIN products p ON printf('ITM%04d', p.id) = ppr.item_code
        WHERE ppr.company_id = ? AND p.product_category_id = ?
        GROUP BY 1, 2""", (buyer, category_id)):
        prices = [x["price"] for x in rows(conn, "SELECT price FROM purchase_price_records WHERE company_id=? AND item_code=? ORDER BY price",
                                          (buyer, r["item_code"]))]
        med = prices[len(prices) // 2]
        items.append({"item_code": r["item_code"], "item": r["name"], "purchases": r["n"],
                      "price_median": round(med, 2), "price_k": r["k"]})
    return {"buyer_id": buyer, "category_id": category_id, "items": items}
