"""Vendor chatbot (offline engine): answers from real data, never leaks, respects policy, persists sessions."""
import unittest

from tests.conftest_db import conn, vendor_id
from vi.chat.service import chat, greeting, history

QUESTIONS = [
    "which events did I lose recently?", "why did I lose the last event?", "why did I lose the steel rfq in july?",
    "what price should I quote in steel?", "how do I do on counter-offers?", "how is my delivery?",
    "where am I weak technically?", "is my profile complete?", "how am I doing with Apex Steelworks?",
    "how many invitations did I get?", "who won the last event and what was the L1 price?", "tell me the competitor prices",
    "how am I doing overall?", "help",
]


class ChatNeverLeaks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = conn()

    def test_every_question_for_every_planted_vendor_is_clean(self):
        vendors = [r[0] for r in self.c.execute("SELECT id FROM companies WHERE category='vendor' AND archetype<>'generic'")]
        for v in vendors:
            others = [r[0] for r in self.c.execute("SELECT name FROM companies WHERE category='vendor' AND id<>?", (v,))]
            sid = None
            for q in QUESTIONS:
                r = chat(self.c, v, sid, q, force_offline=True)
                sid = r["session_id"]
                self.assertTrue(r["reply"].strip(), f"empty reply for {q}")
                low = r["reply"].lower()
                for name in others:
                    self.assertNotIn(name.lower(), low, f"vendor {v}: '{name}' leaked answering '{q}'")
                self.assertNotIn("l1_total", low)

    def test_competitor_question_is_refused_explicitly(self):
        v = vendor_id(self.c, "V-LATE")
        r = chat(self.c, v, None, "who won that event and what was the L1 price?", force_offline=True)
        self.assertIn("never show", r["reply"])
        self.assertEqual(r["tools"], [])


class ChatAnswersFromData(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = conn()

    def test_v_late_counter_offer_answer_has_the_leak(self):
        r = chat(self.c, vendor_id(self.c, "V-LATE"), None, "how do I do on counter-offers?", force_offline=True)
        self.assertIn("missed the window", r["reply"])
        self.assertIn("biggest leak", r["reply"])
        self.assertEqual([t["tool"] for t in r["tools"]], ["habits"])

    def test_v_late_why_lost_uses_two_tools_and_blames_timing(self):
        r = chat(self.c, vendor_id(self.c, "V-LATE"), None, "why did I lose the last steel event?", force_offline=True)
        tools = [t["tool"] for t in r["tools"]]
        self.assertIn("my_events", tools); self.assertIn("why_did_i_lose", tools)
        self.assertTrue("timing" in r["reply"].lower() or "policy = none" in r["reply"] or "does not share" in r["reply"])

    def test_v_high_price_band_in_steel(self):
        r = chat(self.c, vendor_id(self.c, "V-HIGH"), None, "what price should I quote in steel?", force_offline=True)
        self.assertIn("Steel", r["reply"])
        self.assertIn("more than 6% above L1 you won 0%", r["reply"])

    def test_v_techweak_technical_names_weak_section(self):
        r = chat(self.c, vendor_id(self.c, "V-TECHWEAK"), None, "where am I weak technically?", force_offline=True)
        self.assertIn("quality certifications", r["reply"])

    def test_v_slipping_delivery_trend(self):
        r = chat(self.c, vendor_id(self.c, "V-SLIPPING"), None, "how is my delivery performance?", force_offline=True)
        self.assertIn("worse", r["reply"])

    def test_greeting_has_totals_and_suggestions(self):
        g = greeting(self.c, vendor_id(self.c, "V-STAR"))
        self.assertIn("won", g["text"]); self.assertGreaterEqual(len(g["suggestions"]), 4)


class ChatPolicyAndSessions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = conn()

    def test_policy_none_event_is_not_explained(self):
        v = vendor_id(self.c, "V-TECHWEAK")
        tr = self.c.execute("""SELECT tr.id FROM audiences a JOIN trade_requests tr ON tr.id=a.trade_request_id
                               JOIN event_groups eg ON eg.id=tr.event_group_id
                               WHERE a.vendor_company_id=? AND eg.vendor_feedback_policy='none'
                                 AND EXISTS (SELECT 1 FROM bids b WHERE b.trade_request_id=tr.id AND b.vendor_company_id=a.vendor_company_id)
                                 AND NOT EXISTS (SELECT 1 FROM proposals p WHERE p.trade_request_id=tr.id AND p.vendor_company_id=a.vendor_company_id AND p.status='selected')
                               LIMIT 1""", (v,)).fetchone()[0]
        r = chat(self.c, v, None, f"why did I lose event #{tr}?", force_offline=True)
        self.assertIn("does not share", r["reply"])
        self.assertNotIn("Next time", r["reply"])

    def test_session_persists_and_is_scoped_to_vendor(self):
        v1, v2 = vendor_id(self.c, "V-LATE"), vendor_id(self.c, "V-STAR")
        r = chat(self.c, v1, None, "help", force_offline=True)
        chat(self.c, v1, r["session_id"], "how is my delivery?", force_offline=True)
        self.assertEqual(len(history(self.c, r["session_id"], v1)), 4)
        self.assertEqual(len(history(self.c, r["session_id"], v2)), 0)     # another vendor cannot read it

    def test_audit_logged(self):
        v = vendor_id(self.c, "V-GHOST")
        chat(self.c, v, None, "how many invitations did I get?", force_offline=True)
        row = self.c.execute("SELECT inputs_json FROM audit_log WHERE action='chat' AND actor_id=? ORDER BY id DESC LIMIT 1", (v,)).fetchone()
        self.assertIsNotNone(row); self.assertIn("invitations", row[0])


if __name__ == "__main__":
    unittest.main()
