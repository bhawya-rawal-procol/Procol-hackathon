"""Planted vendor behaviours. The demo has something to say because these exist.

Each archetype is a dict of behaviour parameters the event generator reads:
  open_rate         P(vendor opens the invite mail)
  bid_rate          P(vendor bids | opened)  (unopened invites almost never bid)
  price_mult        (lo, hi) multiplier on the buyer's target_price, per category override allowed
  co_late_rate      P(counter-offer reply arrives after ends_at)  -> resolution 'expired'
  co_accept_rate    P(accepts counter-offer | replied on time)
  tech              default technical section score fraction; per-section overrides allowed
  on_time           P(delivery on time); may be a callable(days_ago) for trends
  qc                P(QC passed)
  decline_reason    reason written to user_intents when the vendor declines
  categories        categories the vendor supplies (None = random 1-3)
"""
from __future__ import annotations

import random

TECH_SECTIONS = ["technical_compliance", "quality_certifications", "delivery_capability", "past_performance"]

CATEGORIES = ["Steel", "Packaging", "Chemicals", "Electricals", "MRO Spares", "Logistics Services"]

DECLINE_REASONS = [
    "capacity_full", "insufficient_lead_time", "outside_service_area",
    "specification_mismatch", "payment_terms_unacceptable",
]


def _slipping_on_time(days_ago: float) -> float:
    # strong a year ago, sliding over the last six months
    if days_ago > 270:
        return 0.95
    if days_ago > 150:
        return 0.80
    return 0.45


ARCHETYPES: dict[str, dict] = {
    "V-LATE": dict(
        open_rate=0.92, bid_rate=0.85, price_mult=(0.95, 1.00),
        co_late_rate=0.80, co_accept_rate=0.7, tech=0.75, on_time=0.90, qc=0.95, response_hours=22,
        decline_reason="capacity_full", categories=["Steel", "Electricals"],
        name="Rathi Metallurgicals Pvt Ltd",
    ),
    "V-HIGH": dict(
        open_rate=0.90, bid_rate=0.85,
        price_mult=(0.96, 1.03),
        price_mult_by_category={"Steel": (1.07, 1.10), "Packaging": (0.94, 0.99)},
        co_late_rate=0.10, co_accept_rate=0.3, tech=0.78, on_time=0.88, qc=0.93, response_hours=14,
        decline_reason="specification_mismatch", categories=["Steel", "Packaging"],
        name="Omkar Industrial Supplies",
    ),
    "V-TECHWEAK": dict(
        open_rate=0.95, bid_rate=0.9, price_mult=(0.93, 0.98),
        co_late_rate=0.10, co_accept_rate=0.6,
        tech=0.80, tech_by_section={"quality_certifications": 0.32},
        on_time=0.90, qc=0.85, decline_reason="capacity_full", response_hours=10,
        categories=["Chemicals", "MRO Spares"], name="Kaveri Chem & Spares",
    ),
    "V-GHOST": dict(
        open_rate=0.30, bid_rate=0.35, price_mult=(0.97, 1.04),
        co_late_rate=0.3, co_accept_rate=0.5, tech=0.7, on_time=0.85, qc=0.9, response_hours=52,
        decline_reason="insufficient_lead_time", decline_prob=0.9,
        categories=["Electricals", "MRO Spares"], name="Vidyut Traders",
    ),
    "V-STAR": dict(
        open_rate=0.98, bid_rate=0.92, price_mult=(0.95, 1.01),
        co_late_rate=0.05, co_accept_rate=0.75, tech=0.86, on_time=0.95, qc=0.97, response_hours=6,
        decline_reason="capacity_full", categories=["Steel", "Packaging", "MRO Spares"],
        name="Shakti Enterprises",
    ),
    "V-SLIPPING": dict(
        open_rate=0.92, bid_rate=0.85, price_mult=(0.93, 0.99),
        co_late_rate=0.15, co_accept_rate=0.6, tech=0.8, on_time=_slipping_on_time, qc=0.9, response_hours=12,
        decline_reason="capacity_full", categories=["Logistics Services", "Packaging"],
        name="Meridian Freight & Pack",
    ),
    "V-NEVERINVITED": dict(
        open_rate=0.95, bid_rate=0.9, price_mult=(0.94, 0.99),
        co_late_rate=0.1, co_accept_rate=0.7, tech=0.82, on_time=0.93, qc=0.95, response_hours=9,
        decline_reason="capacity_full", categories=["Chemicals"],
        name="Sagar Speciality Chemicals", only_buyers=[0, 1],   # buyers A and B; never buyer C
    ),
}

GENERIC_NAMES = [
    "Arihant Metals", "Bhagwati Steel Corp", "Chakra Packaging", "Dhruv Polymers", "Eastern Electricals",
    "Falcon Logistics", "Ganga Chemicals", "Hindon Fasteners", "Indus Cartons", "Jyoti Switchgear",
    "Kalinga Alloys", "Lotus Labels", "Mahavir Bearings", "Narmada Transport", "Orion Cables",
    "Prakash Pipes", "Quantum Reagents", "Rudra Engineering", "Sundaram Corrugators", "Trishul Tools",
    "Ujjwal Chemicals", "Vanguard Movers", "Western Wires", "Xylem Industrial", "Yamuna Packaging",
    "Zenith Fabricators", "Aakash Logistics", "Bharani Electricals", "Chetak Steels", "Dakshin Chem",
    "Everest Spares", "Fortune Freight", "Girnar Metals",
]


def generic_archetype(rng: random.Random, name: str) -> dict:
    """A plausible, mildly-varied vendor. Variation is what gives the ranker signal."""
    quality = rng.random()  # 0 = weak vendor, 1 = strong vendor
    return dict(
        open_rate=0.55 + 0.4 * quality,
        bid_rate=0.45 + 0.45 * quality,
        response_hours=8 + 50 * (1 - quality),
        price_mult=(0.95 + 0.04 * (1 - quality), 1.01 + 0.06 * (1 - quality)),
        co_late_rate=0.35 * (1 - quality) + 0.05,
        co_accept_rate=0.35 + 0.4 * quality,
        tech=0.6 + 0.3 * quality,
        on_time=0.7 + 0.27 * quality,
        qc=0.8 + 0.18 * quality,
        decline_reason=rng.choice(DECLINE_REASONS),
        categories=rng.sample(CATEGORIES, rng.randint(1, 3)),
        name=name,
    )


def price_multiplier(arch: dict, category: str, rng: random.Random) -> float:
    lo, hi = arch.get("price_mult_by_category", {}).get(category, arch["price_mult"])
    return rng.uniform(lo, hi)


def tech_fraction(arch: dict, section: str, rng: random.Random) -> float:
    base = arch.get("tech_by_section", {}).get(section, arch["tech"])
    return max(0.05, min(1.0, base + rng.gauss(0, 0.06)))


def on_time_prob(arch: dict, days_ago: float) -> float:
    v = arch["on_time"]
    return v(days_ago) if callable(v) else v
