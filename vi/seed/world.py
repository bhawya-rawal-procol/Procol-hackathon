"""Static world: buyers, vendors, categories, products, buyer↔vendor mappings, feedback policies."""
from __future__ import annotations

import random
import sqlite3
from dataclasses import dataclass, field

from .archetypes import ARCHETYPES, CATEGORIES, GENERIC_NAMES, generic_archetype

BUYERS = [
    # (name, default vendor_feedback_policy)
    ("Apex Steelworks Ltd", "relative_plus_technical"),
    ("Bharat Packaging Co", "relative_plus_technical"),
    ("Coastal Chemicals Pvt Ltd", "none"),
]

PRODUCTS_BY_CATEGORY = {
    "Steel": [("MS Angle 50x50x6", "MT", 62000), ("TMT Bar Fe500 12mm", "MT", 58500),
              ("HR Coil 3mm", "MT", 61000), ("MS Plate 10mm", "MT", 63500)],
    "Packaging": [("5-ply Corrugated Box 600x400", "pcs", 38), ("Stretch Film 23mic", "kg", 165),
                  ("HDPE Drum 200L", "pcs", 1450), ("BOPP Tape 48mm", "roll", 42)],
    "Chemicals": [("Caustic Soda Lye 48%", "MT", 41000), ("Sulphuric Acid 98%", "MT", 9800),
                  ("Hydrogen Peroxide 50%", "MT", 52000), ("Sodium Hypochlorite", "MT", 12500)],
    "Electricals": [("XLPE Cable 3.5C 95sqmm", "m", 1180), ("MCCB 250A 4P", "pcs", 14200),
                    ("LED Highbay 150W", "pcs", 6800), ("Contactor 95A", "pcs", 5400)],
    "MRO Spares": [("SKF Bearing 6205", "pcs", 640), ("V-Belt B68", "pcs", 310),
                   ("Gate Valve 4in CI", "pcs", 5200), ("Pneumatic Cylinder 63x200", "pcs", 8900)],
    "Logistics Services": [("FTL 32ft MXL Mumbai-Pune", "trip", 18500), ("Warehouse Handling", "MT", 420),
                           ("Container Haulage 40ft JNPT", "trip", 24000), ("Last-mile Van Hire", "trip", 3200)],
}


@dataclass
class World:
    buyer_ids: list[int] = field(default_factory=list)
    vendor_ids: list[int] = field(default_factory=list)
    vendor_arch: dict[int, dict] = field(default_factory=dict)          # vendor_id -> archetype params
    vendor_label: dict[int, str] = field(default_factory=dict)          # vendor_id -> archetype label
    category_ids: dict[str, int] = field(default_factory=dict)
    products_by_category: dict[int, list[dict]] = field(default_factory=dict)
    buyer_policy: dict[int, str] = field(default_factory=dict)
    vendor_code: dict[tuple[int, int], str] = field(default_factory=dict)  # (buyer, vendor) -> code

    def vendors_for(self, buyer_id: int, category: str) -> list[int]:
        """Vendors this buyer can invite for a category (mapped + supply the category)."""
        return [v for v in self.vendor_ids
                if category in self.vendor_arch[v]["categories"] and (buyer_id, v) in self.vendor_code]


def _gst(rng: random.Random, n: int) -> str:
    return f"{rng.randint(1, 36):02d}AA{n:04d}A{rng.randint(1000, 9999)}Z{rng.randint(1, 9)}"


def build_world(conn: sqlite3.Connection, rng: random.Random) -> World:
    w = World()

    for i, (name, policy) in enumerate(BUYERS, start=1):
        conn.execute("INSERT INTO companies(id,name,category,gst_no) VALUES (?,?,?,?)",
                     (i, name, "buyer", _gst(rng, i)))
        w.buyer_ids.append(i)
        w.buyer_policy[i] = policy

    for name, (cat_i, _) in zip(CATEGORIES, enumerate(CATEGORIES, start=1)):
        conn.execute("INSERT INTO product_categories(id,name) VALUES (?,?)", (cat_i, name))
        w.category_ids[name] = cat_i

    pid = 0
    for cat_name, items in PRODUCTS_BY_CATEGORY.items():
        cid = w.category_ids[cat_name]
        w.products_by_category[cid] = []
        for pname, unit, base_price in items:
            pid += 1
            conn.execute("INSERT INTO products(id,name,product_category_id,unit) VALUES (?,?,?,?)",
                         (pid, pname, cid, unit))
            w.products_by_category[cid].append(dict(id=pid, name=pname, unit=unit, base_price=base_price))

    vid = 100
    for label, arch in ARCHETYPES.items():
        vid += 1
        conn.execute("INSERT INTO companies(id,name,category,gst_no,archetype) VALUES (?,?,?,?,?)",
                     (vid, arch["name"], "vendor", _gst(rng, vid), label))
        w.vendor_ids.append(vid)
        w.vendor_arch[vid] = arch
        w.vendor_label[vid] = label
    for name in GENERIC_NAMES:
        vid += 1
        arch = generic_archetype(rng, name)
        conn.execute("INSERT INTO companies(id,name,category,gst_no,archetype) VALUES (?,?,?,?,?)",
                     (vid, name, "vendor", _gst(rng, vid), "generic"))
        w.vendor_ids.append(vid)
        w.vendor_arch[vid] = arch
        w.vendor_label[vid] = "generic"

    # buyer ↔ vendor mappings. Every vendor is mapped to 2–3 buyers, except V-NEVERINVITED.
    mid = 0
    for v in w.vendor_ids:
        arch = w.vendor_arch[v]
        if "only_buyers" in arch:
            buyers = [w.buyer_ids[i] for i in arch["only_buyers"]]
        else:
            buyers = rng.sample(w.buyer_ids, rng.choice([2, 3, 3]))
        for b in buyers:
            mid += 1
            code = f"V{v:05d}"
            status = "approved" if rng.random() < 0.85 else rng.choice(["onboarding", "invited"])
            if w.vendor_label[v] != "generic":
                status = "approved"
            conn.execute(
                "INSERT INTO buyer_seller_company_mappings(id,client_company_id,dealing_with_company_id,"
                "vendor_code,status) VALUES (?,?,?,?,?)", (mid, b, v, code, status))
            w.vendor_code[(b, v)] = code

    conn.commit()
    return w
