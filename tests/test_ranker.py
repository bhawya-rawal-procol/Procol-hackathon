"""Ranker + forecast behaviour on the planted stories. Requires trained models (make train)."""
import unittest
from pathlib import Path

from tests.conftest_db import conn, vendor_id
from vi.forecast import forecast
from vi.ranker.serve import discovery_vendors, models_ready, rank_for_event


def draft_event(c, buyer):
    return c.execute("""SELECT tr.id FROM trade_requests tr JOIN event_groups eg ON eg.id=tr.event_group_id
                        WHERE eg.company_id=? AND tr.status='draft' LIMIT 1""", (buyer,)).fetchone()[0]


@unittest.skipUnless(models_ready(), "models not trained — run `make train` first")
class Ranker(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = conn()
        cls.r = rank_for_event(cls.c, draft_event(cls.c, 1), 1)      # buyer A, Steel draft

    def test_v_star_outranks_v_high_in_steel(self):
        pos = {x["archetype"]: x["rank"] for x in self.r["ranked"] if x["archetype"] != "generic"}
        self.assertIn("V-STAR", pos); self.assertIn("V-HIGH", pos)
        self.assertLess(pos["V-STAR"], pos["V-HIGH"])
        self.assertLessEqual(pos["V-STAR"], 3)

    def test_every_ranked_vendor_has_score_and_reasons(self):
        for x in self.r["ranked"]:
            self.assertTrue(0 <= x["score"] <= 1)
            self.assertTrue(0 <= x["p_bid"] <= 1)
            self.assertIsInstance(x["reasons"], list)
        self.assertEqual([x["rank"] for x in self.r["ranked"]], list(range(1, len(self.r["ranked"]) + 1)))

    def test_v_neverinvited_surfaces_in_discovery_for_buyer_c(self):
        chem = self.c.execute("SELECT id FROM product_categories WHERE name='Chemicals'").fetchone()[0]
        disc = discovery_vendors(self.c, 3, chem)
        self.assertIn(vendor_id(self.c, "V-NEVERINVITED"), [d["id"] for d in disc])
        for d in disc:
            self.assertGreaterEqual(d["other_buyers"], 2)

    def test_forecast_flags_thin_participation_and_suggests(self):
        tr = self.r["trade_request_id"]
        weakest = [x["vendor_id"] for x in self.r["ranked"][-2:]]
        f = forecast(self.c, tr, 1, weakest)
        self.assertFalse(f["sufficient"])
        self.assertGreater(len(f["suggestions"]), 0)
        self.assertGreaterEqual(f["expected_after_suggestions"], f["threshold"] - 0.01)
        strong = [x["vendor_id"] for x in self.r["ranked"][:5]]
        self.assertTrue(forecast(self.c, tr, 1, strong)["sufficient"])

    def test_metrics_file_reports_honest_auc(self):
        import json
        m = json.loads(Path("data/models/metrics.json").read_text())
        for label in ("p_bid", "p_top3"):
            rep = m["models"][label]
            self.assertGreater(rep["test_rows"], 100)
            self.assertTrue(all(0.5 <= v <= 1.0 for v in rep["test_auc"].values()), rep["test_auc"])


if __name__ == "__main__":
    unittest.main()
