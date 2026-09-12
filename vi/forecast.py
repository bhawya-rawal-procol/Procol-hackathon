"""Pre-publish participation forecast. Expected bids = Σ P(bid) over the chosen vendors.
If below the bid-sufficiency threshold, suggest more vendors from the ranker until it is met.
The threshold mirrors Procol's per-tenant `bid_sufficiency_rules` (default: at least 3 bids)."""
from __future__ import annotations

import sqlite3

from .ranker.serve import rank_for_event

DEFAULT_THRESHOLD = 3


def forecast(conn: sqlite3.Connection, tr_id: int, buyer: int, chosen: list[int],
             threshold: int = DEFAULT_THRESHOLD) -> dict:
    ranking = rank_for_event(conn, tr_id, buyer, n_invited=len(chosen))
    by_id = {r["vendor_id"]: r for r in ranking["ranked"]}
    picked = [by_id[v] for v in chosen if v in by_id]
    expected = sum(r["p_bid"] for r in picked)

    suggestions, running = [], expected
    if expected < threshold:
        for r in ranking["ranked"]:
            if r["vendor_id"] in chosen:
                continue
            suggestions.append({"vendor_id": r["vendor_id"], "name": r["name"], "p_bid": r["p_bid"], "reasons": r["reasons"]})
            running += r["p_bid"]
            if running >= threshold:
                break

    return {
        "trade_request_id": tr_id, "threshold": threshold, "chosen": len(picked),
        "expected_bids": round(expected, 1), "sufficient": expected >= threshold,
        "expected_after_suggestions": round(running, 1),
        "message": (f"{expected:.1f} bids expected from {len(picked)} vendors — meets the {threshold}-bid rule."
                    if expected >= threshold else
                    f"{expected:.1f} bids expected from {len(picked)} vendors — below the {threshold}-bid rule. "
                    f"Add {len(suggestions)} more to reach ~{running:.1f}."),
        "suggestions": suggestions,
        "per_vendor": [{"vendor_id": r["vendor_id"], "name": r["name"], "p_bid": r["p_bid"]} for r in picked],
    }
