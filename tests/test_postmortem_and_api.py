"""Post-mortem, price band and API behaviour — including the end-to-end confidentiality check
that NO vendor-facing API response ever contains another vendor's name."""
import json
import unittest

from tests.conftest_db import conn, test_db_path, vendor_id
from vi.postmortem.service import build_post_mortem
from vi.priceband import winning_price_band


def lost_event_for(c, vendor, policy_not_none=True, missed_window=False):
    sql = """SELECT tr.id FROM audiences a JOIN trade_requests tr ON tr.id=a.trade_request_id
             JOIN event_groups eg ON eg.id=tr.event_group_id
             WHERE a.vendor_company_id=:v AND tr.status='closed'
               AND EXISTS (SELECT 1 FROM bids b WHERE b.trade_request_id=tr.id AND b.vendor_company_id=:v)
               AND NOT EXISTS (SELECT 1 FROM proposals p WHERE p.trade_request_id=tr.id AND p.vendor_company_id=:v AND p.status='selected')
               AND (:pn = 0 OR eg.vendor_feedback_policy <> 'none')
               AND (:mw = 0 OR EXISTS (SELECT 1 FROM additional_requests ar WHERE ar.trade_request_id=tr.id
                                        AND ar.vendor_company_id=:v AND ar.resolution='expired'))
             LIMIT 1"""
    r = c.execute(sql, {"v": vendor, "pn": int(policy_not_none), "mw": int(missed_window)}).fetchone()
    return r[0] if r else None


class PostMortem(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = conn()
        cls.late = vendor_id(cls.c, "V-LATE")
        cls.others = [r[0] for r in cls.c.execute("SELECT name FROM companies WHERE category='vendor' AND id<>?", (cls.late,))]

    def test_v_late_post_mortem_blames_timing(self):
        tr = lost_event_for(self.c, self.late, missed_window=True)
        self.assertIsNotNone(tr)
        pm = build_post_mortem(self.c, self.late, tr, force=True)
        self.assertTrue(pm["available"])
        self.assertEqual(pm["checks"]["timing"]["severity"], "high")
        self.assertIn("timing", pm["narration"].lower())
        self.assertTrue(pm["next_action"])

    def test_no_competitor_name_or_winner_in_any_post_mortem(self):
        for tr, in self.c.execute("""SELECT DISTINCT trade_request_id FROM audiences WHERE vendor_company_id=? LIMIT 25""", (self.late,)):
            pm = build_post_mortem(self.c, self.late, tr, force=True)
            flat = json.dumps(pm)
            for name in self.others:
                self.assertNotIn(name, flat, f"competitor name leaked in post-mortem for tr {tr}")
            self.assertNotIn("l1_total", flat)
            self.assertNotIn("winner", flat.lower().replace("why i", ""))

    def test_policy_none_blanks_post_mortem(self):
        v = vendor_id(self.c, "V-TECHWEAK")
        tr = self.c.execute("""SELECT tr.id FROM audiences a JOIN trade_requests tr ON tr.id=a.trade_request_id
                               JOIN event_groups eg ON eg.id=tr.event_group_id
                               WHERE a.vendor_company_id=? AND eg.vendor_feedback_policy='none' LIMIT 1""", (v,)).fetchone()[0]
        pm = build_post_mortem(self.c, v, tr, force=True)
        self.assertFalse(pm["available"])
        self.assertEqual(pm["checks"], {})
        self.assertIsNone(pm["narration"])

    def test_relative_only_strips_technical(self):
        v = vendor_id(self.c, "V-TECHWEAK")
        tr = lost_event_for(self.c, v)
        self.c.execute("UPDATE event_groups SET vendor_feedback_policy='relative_only' WHERE id=(SELECT event_group_id FROM trade_requests WHERE id=?)", (tr,))
        self.c.commit()
        try:
            pm = build_post_mortem(self.c, v, tr, force=True)
            self.assertNotIn("technical", pm["checks"])
            self.assertIn("price", pm["checks"])
        finally:
            self.c.execute("UPDATE event_groups SET vendor_feedback_policy='relative_plus_technical' WHERE id=(SELECT event_group_id FROM trade_requests WHERE id=?)", (tr,))
            self.c.commit()


class PriceBand(unittest.TestCase):
    def test_v_high_wins_nothing_above_6pct_in_steel(self):
        c = conn()
        pb = winning_price_band(c, vendor_id(c, "V-HIGH"))
        steel = next(cat for cat in pb["categories"] if cat["category"] == "Steel")
        far = [b for b in steel["buckets"] if b["bucket"] in ("6–10%", ">10%")]
        self.assertGreaterEqual(sum(b["bids"] for b in far), 5)
        self.assertEqual(sum(b["wins"] for b in far), 0)


class ApiConfidentiality(unittest.TestCase):
    """Every vendor-facing endpoint, for every planted vendor, must be free of other vendors' names."""
    @classmethod
    def setUpClass(cls):
        import os
        os.environ["VI_DB"] = test_db_path()
        from vi import api as api_mod
        api_mod.DB_PATH = test_db_path()
        cls.client = api_mod.app.test_client()
        cls.c = conn()

    def test_vendor_endpoints_never_leak_other_vendor_names(self):
        vendors = [r[0] for r in self.c.execute("SELECT id FROM companies WHERE category='vendor' AND archetype<>'generic'")]
        for v in vendors:
            others = [r[0] for r in self.c.execute("SELECT name FROM companies WHERE category='vendor' AND id<>?", (v,))]
            for path in (f"/api/vendor/{v}/habits", f"/api/vendor/{v}/priceband", f"/api/vendor/{v}/profile"):
                body = self.client.get(path).get_data(as_text=True)
                for name in others:
                    self.assertNotIn(name, body, f"{name} leaked via {path}")
            tr = lost_event_for(self.c, v)
            if tr:
                body = self.client.get(f"/api/vendor/{v}/events/{tr}/postmortem?force=1").get_data(as_text=True)
                for name in others:
                    self.assertNotIn(name, body)

    def test_policy_flip_removes_and_restores_feedback(self):
        v = vendor_id(self.c, "V-LATE")
        tr = lost_event_for(self.c, v)
        buyer = self.c.execute("SELECT eg.company_id FROM trade_requests tr JOIN event_groups eg ON eg.id=tr.event_group_id WHERE tr.id=?", (tr,)).fetchone()[0]
        def set_policy(policy):
            """The buyer sets this in Procol; the prototype is vendor-only, so write it directly."""
            self.c.execute("UPDATE event_groups SET vendor_feedback_policy=? WHERE company_id=?", (policy, buyer))
            self.c.commit()

        before = self.client.get(f"/api/vendor/{v}/events/{tr}/postmortem?force=1").get_json()
        self.assertTrue(before["available"])
        set_policy("none")
        after = self.client.get(f"/api/vendor/{v}/events/{tr}/postmortem?force=1").get_json()
        self.assertFalse(after["available"])
        set_policy("relative_plus_technical")
        restored = self.client.get(f"/api/vendor/{v}/events/{tr}/postmortem?force=1").get_json()
        self.assertTrue(restored["available"])

    def test_audit_log_written(self):
        v = vendor_id(self.c, "V-STAR")
        self.client.get(f"/api/vendor/{v}/priceband")
        row = self.c.execute("SELECT persona, action, guard_json FROM audit_log WHERE action='price_band' ORDER BY id DESC LIMIT 1").fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row[0], "vendor")
        self.assertIsNotNone(row[2])                      # guard decisions are recorded with the output


if __name__ == "__main__":
    unittest.main()
