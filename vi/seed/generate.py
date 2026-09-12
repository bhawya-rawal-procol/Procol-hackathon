"""Seed the synthetic Procol-shaped world.  `python -m vi.seed.generate --db data/x.db --seed 42`"""
from __future__ import annotations

import argparse
import random
from datetime import datetime, timedelta, timezone

from ..db import DEFAULT_DB, iso, reset_db, scalar
from .events import EventGenerator
from .world import build_world

NOW = datetime(2026, 9, 11, 9, 0, tzinfo=timezone.utc)
HISTORY_DAYS = 540
N_EVENTS = 150


def _rating_logs(conn, now: datetime) -> None:
    """Monthly company_rating_logs per vendor, computed from the transactional tables."""
    for m in range(18, -1, -1):
        d = now - timedelta(days=30 * m)
        conn.execute("""
        INSERT INTO company_rating_logs(company_id, profiling_date, bids, selected_bids, revised_bids,
               deliveries, delayed_deliveries, passed_quality_checks, failed_quality_checks, total_requests)
        SELECT c.id, :d,
          (SELECT COUNT(*) FROM bids b WHERE b.vendor_company_id=c.id AND b.created_at<=:d),
          (SELECT COUNT(*) FROM bids b WHERE b.vendor_company_id=c.id AND b.status='selected' AND b.created_at<=:d),
          (SELECT COUNT(*) FROM bids b WHERE b.vendor_company_id=c.id AND b.status='revised' AND b.created_at<=:d),
          (SELECT COUNT(*) FROM orders o WHERE o.vendor_company_id=c.id AND o.delivered_at<=:d),
          (SELECT COUNT(*) FROM orders o WHERE o.vendor_company_id=c.id AND o.delivered_at<=:d
                                              AND o.delivered_at>o.delivery_date),
          (SELECT COUNT(*) FROM orders o WHERE o.vendor_company_id=c.id AND o.delivered_at<=:d AND o.qc_passed=1),
          (SELECT COUNT(*) FROM orders o WHERE o.vendor_company_id=c.id AND o.delivered_at<=:d AND o.qc_passed=0),
          (SELECT COUNT(*) FROM audiences a WHERE a.vendor_company_id=c.id AND a.invited_at<=:d)
        FROM companies c WHERE c.category='vendor'
        """, {"d": iso(d)})


def seed(db_path: str, seed: int = 42) -> None:
    rng = random.Random(seed)
    conn = reset_db(db_path)
    world = build_world(conn, rng)
    gen = EventGenerator(conn, rng, world, NOW)

    # skew toward recent months so 90d/365d windows both have signal
    starts = sorted(NOW - timedelta(days=25 + (HISTORY_DAYS - 25) * rng.random() ** 1.4) for _ in range(N_EVENTS))
    for s in starts:
        gen.closed_event(s)

    # draft events for the buyer demo — buyer A gets a Steel RFQ (V-STAR/V-LATE/V-HIGH story),
    # buyer C gets a Chemicals RFQ (V-NEVERINVITED discovery story), buyer B a short-lead Electricals RFQ.
    a, b, c = world.buyer_ids
    gen.draft_event(a, "Steel", "Steel RFQ — Q4 structural requirement", lead_days=7)
    gen.draft_event(c, "Chemicals", "Chemicals RFQ — caustic & peroxide, H2", lead_days=5)
    gen.draft_event(b, "Electricals", "Electricals RFQ — urgent cable lot", lead_days=2)
    conn.commit()

    _rating_logs(conn, NOW)
    conn.commit()

    print(f"seeded {db_path}")
    for t in ["companies", "event_groups", "trade_requests", "audiences", "bids", "bid_trade_products",
              "additional_requests", "trade_schedules", "evaluation_scores", "proposals", "orders",
              "user_intents", "purchase_price_records", "company_rating_logs"]:
        print(f"  {t:<28} {scalar(conn, f'SELECT COUNT(*) FROM {t}'):>6}")
    conn.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()
    seed(args.db, args.seed)
