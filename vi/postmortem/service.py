"""Post-mortem orchestration: checks → restricted-score strip → ConfidentialityGuard → narrator → store + audit."""
from __future__ import annotations

import json
import sqlite3

from .. import audit
from ..db import now_iso, one, rows
from ..guard import ConfidentialityGuard, strip_restricted_technical
from .checks import event_context, run_all
from .narrator import narrate


def _guard_for(conn: sqlite3.Connection, vendor: int, buyer: int) -> ConfidentialityGuard:
    own = one(conn, "SELECT name FROM companies WHERE id=?", (vendor,))["name"]
    buyer_name = one(conn, "SELECT name FROM companies WHERE id=?", (buyer,))["name"]
    others = [r["name"] for r in rows(conn, "SELECT name FROM companies WHERE category='vendor' AND id<>?", (vendor,))]
    return ConfidentialityGuard(vendor, own, buyer_name, others)


def build_post_mortem(conn: sqlite3.Connection, vendor: int, tr: int, force: bool = False) -> dict:
    ctx = event_context(conn, vendor, tr)
    policy = ctx["policy"]

    cached = one(conn, "SELECT * FROM post_mortems WHERE vendor_company_id=? AND trade_request_id=?", (vendor, tr))
    if cached and cached["policy"] == policy and not force:
        return _present(cached, ctx)

    checks = run_all(conn, vendor, ctx)
    restricted_audit: list[dict] = []
    if checks["technical"]["evidence"].get("sections"):
        kept, restricted_audit = strip_restricted_technical(checks["technical"]["evidence"]["sections"])
        if not kept:
            checks["technical"] = {"signal": "The buyer keeps technical scores confidential for this event.",
                                   "severity": "na", "evidence": {"sections": []}}
        else:
            checks["technical"]["evidence"]["sections"] = kept

    guard = _guard_for(conn, vendor, ctx["buyer_id"])
    res = guard.apply(checks, policy)
    guard_audit = restricted_audit + res.audit

    if policy == "none":
        story = {"narration": None, "next_action": None, "narrator": "template"}
    else:
        story = narrate(res.payload, ctx)          # the narrator only ever sees the guarded payload

    conn.execute("""INSERT OR REPLACE INTO post_mortems
        (vendor_company_id, trade_request_id, policy, checks_json, narration, next_action, narrator, guard_audit_json, created_at)
        VALUES (?,?,?,?,?,?,?,?,?)""",
                 (vendor, tr, policy, json.dumps(res.payload), story["narration"], story["next_action"],
                  story["narrator"], json.dumps(guard_audit), now_iso()))
    conn.commit()
    audit.log(conn, "vendor", vendor, "post_mortem", {"trade_request_id": tr, "policy": policy}, guard_audit, res.payload)
    row = one(conn, "SELECT * FROM post_mortems WHERE vendor_company_id=? AND trade_request_id=?", (vendor, tr))
    return _present(row, ctx)


def _present(row: dict, ctx: dict) -> dict:
    return {
        "trade_request_id": row["trade_request_id"], "title": ctx["title"], "category": ctx["category"],
        "rfx_mode": ctx["rfx_mode"], "closed_at": ctx["closed_at"], "won": ctx["won"], "policy": row["policy"],
        "available": row["policy"] != "none",
        "checks": json.loads(row["checks_json"]), "narration": row["narration"], "next_action": row["next_action"],
        "narrator": row["narrator"], "guard_audit": json.loads(row["guard_audit_json"]),
    }
