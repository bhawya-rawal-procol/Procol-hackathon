"""Reason codes: model-agnostic attribution (move one feature to its mean, watch the score move),
then templated into plain buyer-facing sentences using the vendor's REAL raw numbers."""
from __future__ import annotations

import numpy as np

from .features import FEATURE_NAMES


def contributions(model, x: list[float], means: list[float]) -> list[tuple[str, float]]:
    base = float(model.predict_proba(np.array([x]))[0, 1])
    out = []
    for i, name in enumerate(FEATURE_NAMES):
        if name in ("pair_has_history", "cat_has_history", "lot_value_log", "n_invited", "is_rfp", "is_auction"):
            continue
        x2 = list(x); x2[i] = means[i]
        out.append((name, base - float(model.predict_proba(np.array([x2]))[0, 1])))
    return sorted(out, key=lambda t: -abs(t[1]))


def _pct(v):  return f"{round(v * 100)}%"
def _h(v):    return f"{round(v)}h"


def sentence(name: str, delta: float, raw: dict, category: str) -> "str | None":
    pair, cat = raw["pair"], raw["cat"]
    if name == "cat_bid_rate" and cat.get("invites"):
        return f"bid on {round(cat['bid_rate'] * cat['invites'])} of last {cat['invites']} {category} invites"
    if name == "pair_bid_rate" and pair.get("invites"):
        return f"bid on {round(pair['bid_rate'] * pair['invites'])} of your last {pair['invites']} invites"
    if name == "cat_avg_gap_to_l1_pct" and cat.get("avg_gap_to_l1_pct") is not None:
        g = cat["avg_gap_to_l1_pct"]
        return f"avg {abs(g):.1f}% {'above' if g > 0 else 'below'} L1 in {category}"
    if name == "pair_avg_gap_to_l1_pct" and pair.get("avg_gap_to_l1_pct") is not None:
        g = pair["avg_gap_to_l1_pct"]
        return f"avg {abs(g):.1f}% {'above' if g > 0 else 'below'} L1 with you"
    if name == "cat_win_rate" and cat.get("events_bid"):
        return f"won {_pct(cat['win_rate'])} of {cat['events_bid']} {category} events"
    if name == "pair_win_rate" and pair.get("events_bid"):
        return f"won {_pct(pair['win_rate'])} of {pair['events_bid']} events with you"
    if name == "pair_late_counter_offer_rate" and pair.get("counter_offers"):
        r = pair["late_counter_offer_rate"]
        return ("replies to counter-offers on time" if r < 0.2 else f"missed {_pct(r)} of counter-offer windows")
    if name in ("pair_avg_response_hours", "cat_avg_response_hours"):
        v = pair.get("avg_response_hours") or cat.get("avg_response_hours")
        return f"first bid in ~{_h(v)}" if v else None
    if name == "pair_on_time_delivery_rate" and pair.get("deliveries"):
        return f"on-time delivery {_pct(pair['on_time_delivery_rate'])} over {pair['deliveries']} orders"
    if name == "pair_mail_open_rate" and pair.get("invites"):
        return f"opens {_pct(pair['mail_open_rate'])} of your invites"
    if name == "pair_qc_pass_rate" and pair.get("deliveries"):
        return f"QC pass {_pct(pair['qc_pass_rate'])}"
    if name == "pair_avg_technical_pct" and pair.get("avg_technical_pct"):
        return f"technical avg {round(pair['avg_technical_pct'])}%"
    return None


def top_reasons(model, x: list[float], means: list[float], raw: dict, category: str, n: int = 3) -> list[dict]:
    out, seen = [], set()
    for name, delta in contributions(model, x, means):
        s = sentence(name, delta, raw, category)
        if s and s not in seen:
            out.append({"text": s, "direction": "+" if delta > 0 else "-"})
            seen.add(s)
        if len(out) == n:
            break
    return out
