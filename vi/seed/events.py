"""Generates sourcing events end-to-end: invites → bids → counter-offers → best offer →
evaluation → award → order → intents → purchase price records. Behaviour comes from archetypes."""
from __future__ import annotations

import random
import sqlite3
from datetime import datetime, timedelta

from ..db import iso
from .archetypes import TECH_SECTIONS, on_time_prob, price_multiplier, tech_fraction
from .world import World

H = timedelta(hours=1)
D = timedelta(days=1)


class Ids:
    def __init__(self) -> None:
        self.c: dict[str, int] = {}

    def next(self, key: str) -> int:
        self.c[key] = self.c.get(key, 0) + 1
        return self.c[key]


class EventGenerator:
    def __init__(self, conn: sqlite3.Connection, rng: random.Random, world: World, now: datetime):
        self.conn, self.rng, self.w, self.now = conn, rng, world, now
        self.ids = Ids()

    # ------------------------------------------------------------------ helpers
    def _ins(self, table: str, **cols) -> int:
        keys = ",".join(cols)
        qs = ",".join("?" * len(cols))
        cur = self.conn.execute(f"INSERT INTO {table}({keys}) VALUES ({qs})", tuple(cols.values()))
        return cur.lastrowid

    def _bid(self, tr_id: int, vendor: int, at: datetime, tag: str, prices: dict[int, float],
             tps: list[dict], arch: dict) -> int:
        bid_id = self._ins("bids", trade_request_id=tr_id, vendor_company_id=vendor, status="active",
                           created_at=iso(at), bid_tag=tag)
        for tp in tps:
            self._ins("bid_trade_products", bid_id=bid_id, trade_product_id=tp["id"],
                      price=round(prices[tp["id"]], 2), quantity=tp["quantity"],
                      payment_terms_days=self.rng.choice([30, 45, 45, 60, 90]) if arch["tech"] < 0.85
                      else self.rng.choice([30, 45, 45]),
                      delivery_days=tp["asked_delivery_days"] + self.rng.choice([-5, 0, 0, 5, 10, 20]))
        return bid_id

    # ------------------------------------------------------------------ one event
    def closed_event(self, start: datetime) -> None:
        rng, w = self.rng, self.w
        buyer = rng.choice(w.buyer_ids)
        cat_name = rng.choice(list(w.category_ids))
        cat_id = w.category_ids[cat_name]
        mode = rng.choices(["rfq", "rfp", "auction"], weights=[60, 25, 15])[0]
        lead_days = rng.choice([2, 3, 5, 7, 7, 10])
        bid_start = start + rng.randint(1, 3) * D
        bid_end = bid_start + lead_days * D

        eg_id = self._ins("event_groups", company_id=buyer,
                          title=f"{cat_name} {mode.upper()} — {start:%b %Y}", status="closed",
                          created_at=iso(start), closed_at=iso(bid_end + 3 * D),
                          vendor_feedback_policy=w.buyer_policy[buyer])
        tr_id = self._ins("trade_requests", event_group_id=eg_id, rfx_mode=mode, status="closed",
                          bid_start_time=iso(bid_start), bid_end_time=iso(bid_end),
                          closed_at=iso(bid_end + 3 * D))
        self._ins("trade_schedules", trade_request_id=tr_id, schedule_type="auction" if mode == "auction" else "rfq",
                  created_at=iso(start), new_end_time=iso(bid_end))

        tps = []
        for prod in rng.sample(w.products_by_category[cat_id], rng.randint(1, 3)):
            tp = dict(id=None, product_id=prod["id"], quantity=float(rng.choice([10, 25, 50, 100, 250, 500])),
                      target_price=round(prod["base_price"] * rng.uniform(0.95, 1.05), 2),
                      asked_payment_terms_days=rng.choice([45, 60]), asked_delivery_days=rng.choice([15, 30, 45]))
            tp["id"] = self._ins("trade_products", trade_request_id=tr_id, product_id=tp["product_id"],
                                 quantity=tp["quantity"], target_price=tp["target_price"],
                                 asked_payment_terms_days=tp["asked_payment_terms_days"],
                                 asked_delivery_days=tp["asked_delivery_days"])
            tps.append(tp)

        pool = w.vendors_for(buyer, cat_name)
        invitees = rng.sample(pool, min(len(pool), rng.randint(5, 9)))
        bidders: dict[int, dict] = {}          # vendor -> {first_at, prices, last_bid_id}
        non_bidders: list[int] = []

        for v in invitees:
            arch = w.vendor_arch[v]
            opened = rng.random() < arch["open_rate"]
            opened_at = bid_start + rng.uniform(0.5, 30) * H if opened else None
            self._ins("audiences", trade_request_id=tr_id, vendor_company_id=v, invited_at=iso(bid_start),
                      mail_opened_at=iso(opened_at) if opened_at else None)
            p_bid = arch["bid_rate"] if opened else 0.05
            if lead_days <= 3 and w.vendor_label[v] == "V-GHOST":
                p_bid *= 0.3
            if rng.random() >= p_bid:
                non_bidders.append(v)
                continue
            resp_h = max(1.0, rng.gauss(arch.get("response_hours", 24), 6))
            first_at = min(bid_start + resp_h * H, bid_end - 1 * H)
            prices = {tp["id"]: tp["target_price"] * price_multiplier(arch, cat_name, rng) * rng.gauss(1, 0.01)
                      for tp in tps}
            bid_id = self._bid(tr_id, v, first_at, "initial", prices, tps, arch)
            bidders[v] = dict(first_at=first_at, prices=prices, last_bid_id=bid_id)

        # extensions when participation is thin: some non-bidders come in late
        if len(bidders) < 3 and non_bidders:
            new_end = bid_end
            for _ in range(rng.randint(1, 2)):
                new_end = new_end + 1 * D
                self._ins("trade_schedules", trade_request_id=tr_id, schedule_type="extra_closing_time",
                          created_at=iso(new_end - 1 * D), new_end_time=iso(new_end))
                for v in list(non_bidders):
                    if rng.random() < 0.45:
                        arch = w.vendor_arch[v]
                        at = new_end - rng.uniform(1, 20) * H
                        prices = {tp["id"]: tp["target_price"] * price_multiplier(arch, cat_name, rng)
                                  for tp in tps}
                        bid_id = self._bid(tr_id, v, at, "initial", prices, tps, arch)
                        bidders[v] = dict(first_at=at, prices=prices, last_bid_id=bid_id)
                        non_bidders.remove(v)

        # decline reasons from vendors who did not bid
        for v in non_bidders:
            arch = w.vendor_arch[v]
            if rng.random() < arch.get("decline_prob", 0.35):
                self._ins("user_intents", vendor_company_id=v, trade_request_id=tr_id, intent_type="trade_reject",
                          reason=arch["decline_reason"], remarks=None)

        if not bidders:
            return

        totals = lambda: {v: sum(b["prices"][tp["id"]] * tp["quantity"] for tp in tps) for v, b in bidders.items()}

        # negotiation round (not for auctions)
        if mode != "auction" and rng.random() < 0.7 and len(bidders) >= 2:
            t = totals()
            l1 = min(t.values())
            for v in sorted(bidders, key=t.get)[:4]:
                arch = w.vendor_arch[v]
                co_at = bid_end + 4 * H
                ends = co_at + 24 * H
                target = l1 * 0.97  # ask everyone to beat L1 by 3%
                ar = dict(trade_request_id=tr_id, vendor_company_id=v, change_type="counter_offer_for_bid",
                          target_price=round(target, 2), created_at=iso(co_at), ends_at=iso(ends))
                if rng.random() < arch["co_late_rate"]:
                    self._ins("additional_requests", **ar, resolution="expired",
                              resolved_at=iso(ends + rng.uniform(6, 60) * H))
                elif rng.random() < arch["co_accept_rate"]:
                    resolved = co_at + rng.uniform(1, 22) * H
                    self._ins("additional_requests", **ar, resolution="accepted", resolved_at=iso(resolved))
                    factor = (target / t[v]) * rng.uniform(1.0, 1.015)
                    bidders[v]["prices"] = {k: p * factor for k, p in bidders[v]["prices"].items()}
                    self.conn.execute("UPDATE bids SET status='revised' WHERE id=?", (bidders[v]["last_bid_id"],))
                    bidders[v]["last_bid_id"] = self._bid(tr_id, v, resolved, "negotiation",
                                                          bidders[v]["prices"], tps, arch)
                else:
                    self._ins("additional_requests", **ar, resolution="rejected",
                              resolved_at=iso(co_at + rng.uniform(1, 22) * H))

        # best-offer round
        if mode == "rfq" and rng.random() < 0.3 and len(bidders) >= 2:
            bo_at = bid_end + 2 * D
            for v in bidders:
                arch = w.vendor_arch[v]
                ends = bo_at + 48 * H
                late = rng.random() < arch["co_late_rate"] * 0.7
                self._ins("additional_requests", trade_request_id=tr_id, vendor_company_id=v, change_type="best_offer",
                          target_price=None, created_at=iso(bo_at), ends_at=iso(ends),
                          resolution="expired" if late else "accepted",
                          resolved_at=iso(ends + 10 * H) if late else iso(bo_at + rng.uniform(2, 40) * H))
                if not late:
                    factor = rng.uniform(0.975, 0.995)
                    bidders[v]["prices"] = {k: p * factor for k, p in bidders[v]["prices"].items()}
                    self.conn.execute("UPDATE bids SET status='revised' WHERE id=?", (bidders[v]["last_bid_id"],))
                    bidders[v]["last_bid_id"] = self._bid(tr_id, v, bo_at + 30 * H, "best_offer",
                                                          bidders[v]["prices"], tps, arch)

        # technical evaluation for RFPs
        t = totals()
        l1 = min(t.values())
        tech: dict[int, float] = {}
        if mode == "rfp":
            score_type = "unrestricted" if rng.random() < 0.7 else "restricted"
            for v in bidders:
                arch = w.vendor_arch[v]
                fr = []
                for sec in TECH_SECTIONS:
                    f = tech_fraction(arch, sec, rng)
                    fr.append(f)
                    self._ins("evaluation_scores", trade_request_id=tr_id, vendor_company_id=v, section_key=sec,
                              score=round(f * 25, 1), max_score=25, score_type=score_type)
                tech[v] = sum(fr) / len(fr)
            combined = {v: 0.6 * (l1 / t[v]) + 0.4 * tech[v] for v in bidders}
            winner = max(combined, key=combined.get)
        else:
            winner = min(t, key=t.get)

        closed_at = bid_end + 3 * D
        self.conn.execute("UPDATE bids SET status='selected' WHERE id=?", (bidders[winner]["last_bid_id"],))
        shortlisted = sorted(bidders, key=t.get)[:3]
        if winner not in shortlisted:
            shortlisted.append(winner)
        for v in shortlisted:
            self._ins("proposals", trade_request_id=tr_id, vendor_company_id=v,
                      status="selected" if v == winner else "rejected", created_at=iso(closed_at))
        prop_id = self.conn.execute("SELECT id FROM proposals WHERE trade_request_id=? AND status='selected'",
                                    (tr_id,)).fetchone()[0]

        # order + delivery + QC for the winner
        arch = w.vendor_arch[winner]
        days_ago = (self.now - closed_at).days
        for tp in tps:
            due = closed_at + tp["asked_delivery_days"] * D
            on_time = rng.random() < on_time_prob(arch, days_ago)
            delivered = due - rng.uniform(0, 3) * D if on_time else due + rng.uniform(2, 15) * D
            delivered = min(delivered, self.now)
            self._ins("orders", proposal_id=prop_id, vendor_company_id=winner, created_at=iso(closed_at),
                      delivery_date=iso(due), delivered_at=iso(delivered) if delivered <= self.now else None,
                      qc_passed=1 if rng.random() < arch["qc"] else 0)
            self._ins("purchase_price_records", company_id=buyer, item_code=f"ITM{tp['product_id']:04d}",
                      vendor_code=w.vendor_code[(buyer, winner)],
                      price=round(bidders[winner]["prices"][tp["id"]], 2), purchase_date=iso(closed_at),
                      plant_code=rng.choice(["P100", "P200", "P300"]))

    # ------------------------------------------------------------------ drafts for the buyer demo
    def draft_event(self, buyer: int, cat_name: str, title: str, lead_days: int) -> None:
        cat_id = self.w.category_ids[cat_name]
        start = self.now - 1 * D
        eg_id = self._ins("event_groups", company_id=buyer, title=title, status="draft", created_at=iso(start),
                          closed_at=None, vendor_feedback_policy=self.w.buyer_policy[buyer])
        tr_id = self._ins("trade_requests", event_group_id=eg_id, rfx_mode="rfq", status="draft",
                          bid_start_time=iso(self.now + 1 * D), bid_end_time=iso(self.now + (1 + lead_days) * D),
                          closed_at=None)
        for prod in self.rng.sample(self.w.products_by_category[cat_id], 2):
            self._ins("trade_products", trade_request_id=tr_id, product_id=prod["id"],
                      quantity=float(self.rng.choice([50, 100, 250])), target_price=prod["base_price"],
                      asked_payment_terms_days=45, asked_delivery_days=30)
