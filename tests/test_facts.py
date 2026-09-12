"""vendor_profiles must reproduce the planted archetype stories. No AI involved here."""
import unittest

from tests.conftest_db import conn, vendor_id


def profile(c, archetype, window="all", buyer=0, category=0):
    v = vendor_id(c, archetype)
    r = c.execute("""SELECT * FROM vendor_profiles WHERE buyer_company_id=? AND vendor_company_id=?
                     AND category_id=? AND window=?""", (buyer, v, category, window)).fetchone()
    assert r is not None, f"no profile row for {archetype}"
    return dict(r)


class ArchetypesShowUpInFacts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = conn()

    def test_v_late_replies_late_to_counter_offers(self):
        p = profile(self.c, "V-LATE")
        self.assertGreaterEqual(p["counter_offers"], 5)
        self.assertGreater(p["late_counter_offer_rate"], 0.6)
        star = profile(self.c, "V-STAR")
        self.assertLess(star["late_counter_offer_rate"], 0.2)

    def test_v_high_is_expensive_in_steel_but_not_packaging(self):
        steel = self.c.execute("SELECT id FROM product_categories WHERE name='Steel'").fetchone()[0]
        pack = self.c.execute("SELECT id FROM product_categories WHERE name='Packaging'").fetchone()[0]
        s = profile(self.c, "V-HIGH", category=steel)
        p = profile(self.c, "V-HIGH", category=pack)
        self.assertGreater(s["avg_gap_to_l1_pct"], 6.0)
        self.assertLessEqual(s["win_rate"], 0.1)      # "almost never" — an uncontested event can still fall to him
        self.assertLess(p["avg_gap_to_l1_pct"], 3.0)

    def test_v_techweak_weakest_section_is_quality_certifications(self):
        p = profile(self.c, "V-TECHWEAK")
        self.assertEqual(p["weakest_technical_section"], "quality_certifications")
        self.assertLess(p["weakest_technical_pct"], 45)

    def test_v_ghost_rarely_opens_or_bids_and_says_why(self):
        p = profile(self.c, "V-GHOST")
        self.assertLess(p["mail_open_rate"], 0.45)
        self.assertLess(p["bid_rate"], 0.35)
        self.assertIn("insufficient_lead_time", p["decline_reasons"] or "")

    def test_v_star_participates_and_delivers(self):
        p = profile(self.c, "V-STAR")
        self.assertGreater(p["bid_rate"], 0.75)
        self.assertGreaterEqual(p["on_time_delivery_rate"], 0.9)
        self.assertGreater(p["win_rate"], 0.2)

    def test_v_slipping_delivery_trend_is_negative(self):
        p = profile(self.c, "V-SLIPPING")
        self.assertIsNotNone(p["trend_90d_vs_365d"])
        self.assertLess(p["trend_90d_vs_365d"], -10)

    def test_v_neverinvited_has_no_rows_for_buyer_c(self):
        v = vendor_id(self.c, "V-NEVERINVITED")
        n = self.c.execute("SELECT COUNT(*) FROM vendor_profiles WHERE buyer_company_id=3 AND vendor_company_id=?",
                           (v,)).fetchone()[0]
        self.assertEqual(n, 0)
        n_ab = self.c.execute("SELECT COUNT(*) FROM vendor_profiles WHERE buyer_company_id IN (1,2) AND vendor_company_id=?",
                              (v,)).fetchone()[0]
        self.assertGreater(n_ab, 0)


class FactBuildIsIdempotent(unittest.TestCase):
    def test_rebuild_gives_same_row_count(self):
        from tests.conftest_db import AS_OF
        from vi.facts.build import build_all
        c = conn()
        before = c.execute("SELECT COUNT(*) FROM vendor_profiles").fetchone()[0]
        n = build_all(c, AS_OF)
        after = c.execute("SELECT COUNT(*) FROM vendor_profiles").fetchone()[0]
        self.assertEqual(before, after)
        self.assertEqual(n, after)


if __name__ == "__main__":
    unittest.main()
