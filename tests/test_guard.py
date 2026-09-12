"""ConfidentialityGuard — if any of these fail, the product cannot ship."""
import json
import unittest

from vi.guard import ConfidentialityGuard, strip_restricted_technical

OTHERS = ["Shakti Enterprises", "Omkar Industrial Supplies", "Arihant Metals"]


def guard() -> ConfidentialityGuard:
    return ConfidentialityGuard(own_vendor_id=101, own_vendor_name="Rathi Metallurgicals Pvt Ltd",
                                buyer_name="Apex Steelworks Ltd", other_vendor_names=OTHERS)


# A deliberately "leaky" payload, as a careless upstream might build it.
LEAKY = {
    "event": {"title": "Steel RFQ", "buyer": "Apex Steelworks Ltd"},
    "price": {
        "own_total": 1_250_000, "gap_to_l1_pct": 4.2, "rank_position": 3, "n_bidders": 7,
        "l1_total": 1_199_000,                       # forbidden: competitor absolute price
        "l1_vendor_name": "Shakti Enterprises",      # forbidden: competitor name
        "winner": {"id": 105, "name": "Shakti Enterprises", "total": 1_199_000},
        "rankings": [{"vendor": "Omkar Industrial Supplies", "rank": 1}],
        "note": "You lost to Shakti Enterprises by 4%",   # competitor name inside prose
    },
    "technical": {"avg_pct": 71.0, "weakest_section": "quality_certifications"},
    "peers": {"category_on_time_median": 0.91, "category_on_time_k": 2,     # k < 3 -> strip
              "category_gap_median": 2.1, "category_gap_k": 5},              # k >= 3 -> keep
}


class GuardStripsCompetitorData(unittest.TestCase):
    def setUp(self):
        self.res = guard().apply(LEAKY, "relative_plus_technical")
        self.flat = json.dumps(self.res.payload)

    def test_no_competitor_absolute_price(self):
        self.assertNotIn("l1_total", self.res.payload["price"])
        self.assertNotIn("1199000", self.flat)

    def test_no_competitor_names_anywhere(self):
        for name in OTHERS:
            self.assertNotIn(name, self.flat)
        self.assertIn("[another vendor]", self.res.payload["price"]["note"])

    def test_no_winner_or_rankings_blocks(self):
        self.assertNotIn("winner", self.res.payload["price"])
        self.assertNotIn("rankings", self.res.payload["price"])
        self.assertNotIn("l1_vendor_name", self.res.payload["price"])

    def test_relative_and_own_fields_survive(self):
        p = self.res.payload["price"]
        self.assertEqual(p["own_total"], 1_250_000)
        self.assertEqual(p["gap_to_l1_pct"], 4.2)
        self.assertEqual(p["rank_position"], 3)
        self.assertEqual(p["n_bidders"], 7)

    def test_audit_explains_every_removal(self):
        reasons = {a["reason"] for a in self.res.audit}
        self.assertIn("competitor_absolute_data_key", reasons)
        self.assertIn("competitor_name_in_text", reasons)
        self.assertGreaterEqual(self.res.stripped_count, 5)


class GuardKAnonymity(unittest.TestCase):
    def test_median_with_k_below_3_is_stripped(self):
        res = guard().apply(LEAKY, "relative_plus_technical")
        self.assertNotIn("category_on_time_median", res.payload["peers"])
        self.assertIn("category_gap_median", res.payload["peers"])
        self.assertTrue(any("k-anonymity" in a["reason"] for a in res.audit))

    def test_median_without_any_k_is_stripped(self):
        res = guard().apply({"x_median": 5.0}, "relative_only")
        self.assertEqual(res.payload, {})


class GuardPolicies(unittest.TestCase):
    def test_policy_none_blanks_everything(self):
        res = guard().apply(LEAKY, "none")
        self.assertEqual(res.payload, {})
        self.assertEqual(res.audit[0]["action"], "blank_all")

    def test_relative_only_removes_technical(self):
        res = guard().apply(LEAKY, "relative_only")
        self.assertNotIn("technical", res.payload)
        self.assertIn("price", res.payload)

    def test_relative_plus_technical_keeps_own_technical(self):
        res = guard().apply(LEAKY, "relative_plus_technical")
        self.assertEqual(res.payload["technical"]["weakest_section"], "quality_certifications")

    def test_unknown_policy_rejected(self):
        with self.assertRaises(ValueError):
            guard().apply(LEAKY, "everything_please")

    def test_restricted_scores_never_shown(self):
        kept, audit = strip_restricted_technical([
            {"section_key": "a", "score_type": "restricted", "pct": 40},
            {"section_key": "b", "score_type": "unrestricted", "pct": 80},
        ])
        self.assertEqual([s["section_key"] for s in kept], ["b"])
        self.assertEqual(len(audit), 1)


class GuardIsPure(unittest.TestCase):
    def test_input_not_mutated(self):
        before = json.dumps(LEAKY, sort_keys=True)
        guard().apply(LEAKY, "relative_plus_technical")
        self.assertEqual(before, json.dumps(LEAKY, sort_keys=True))


if __name__ == "__main__":
    unittest.main()
