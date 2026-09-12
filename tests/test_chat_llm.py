"""Claude engine protocol test with a MOCK Anthropic server (no key, no network).
Verifies: system+tools sent → tool_use handled → tool_result returned → final text; bad tool args survive;
runtime key connect/disconnect; and the final guard redacts a competitor name even if the model emits one."""
import json
import unittest
from unittest import mock

from tests.conftest_db import conn, vendor_id
from vi.chat import llm
from vi.chat.service import chat, connect_claude, engine_status


class FakeResp:
    def __init__(self, status, body):
        self.status_code, self._b = status, body
        self.text = json.dumps(body)

    def json(self):
        return self._b


def scripted_model(script):
    """Returns a fake requests.post that replays `script` (a list of API bodies) and records requests."""
    sent = []

    def fake_post(url, timeout=None, headers=None, json=None):
        sent.append(json)
        if json.get("max_tokens") == 8:                       # test_connection ping
            return FakeResp(200, {"content": [{"type": "text", "text": "pong"}], "stop_reason": "end_turn"})
        return FakeResp(200, script.pop(0))
    return fake_post, sent


class ClaudeEngineLoop(unittest.TestCase):
    def setUp(self):
        self.c = conn()
        self.v = vendor_id(self.c, "V-LATE")
        self.others = [r[0] for r in self.c.execute("SELECT name FROM companies WHERE category='vendor' AND id<>?", (self.v,))]

    def tearDown(self):
        llm.set_api_key(None)

    def test_tool_use_round_trip_and_final_answer(self):
        lost = self.c.execute("""SELECT tr.id FROM audiences a JOIN trade_requests tr ON tr.id=a.trade_request_id
                                 JOIN event_groups eg ON eg.id=tr.event_group_id
                                 WHERE a.vendor_company_id=? AND eg.vendor_feedback_policy<>'none'
                                   AND EXISTS (SELECT 1 FROM bids b WHERE b.trade_request_id=tr.id AND b.vendor_company_id=a.vendor_company_id)
                                   AND NOT EXISTS (SELECT 1 FROM proposals p WHERE p.trade_request_id=tr.id AND p.vendor_company_id=a.vendor_company_id AND p.status='selected')
                                 LIMIT 1""", (self.v,)).fetchone()[0]
        script = [
            {"stop_reason": "tool_use", "content": [{"type": "tool_use", "id": "t1", "name": "my_events", "input": {"outcome": "lost", "limit": 3}}]},
            {"stop_reason": "tool_use", "content": [{"type": "tool_use", "id": "t2", "name": "why_did_i_lose", "input": {"trade_request_id": lost}}]},
            {"stop_reason": "end_turn", "content": [{"type": "text", "text": "You lost mainly on timing — reply to counter-offers inside the window."}]},
        ]
        fake, sent = scripted_model(script)
        with mock.patch("requests.post", fake):
            self.assertTrue(connect_claude("sk-test")["ok"])
            self.assertEqual(engine_status()["engine"], "anthropic")
            r = chat(self.c, self.v, None, "why did I lose recently?")
        self.assertEqual(r["engine"], "anthropic")
        self.assertIn("timing", r["reply"])
        self.assertEqual([t["tool"] for t in r["tools"]], ["my_events", "why_did_i_lose"])
        first = sent[1]                                        # first real chat request (index 0 was the ping)
        self.assertIn("tools", first); self.assertTrue(any(t["name"] == "event_detail" for t in first["tools"]))
        self.assertIn("Never state", first["system"])
        third = sent[3]                                        # request carrying the second tool_result
        last_user = third["messages"][-1]
        self.assertEqual(last_user["role"], "user")
        self.assertEqual(last_user["content"][0]["type"], "tool_result")
        payload = json.loads(last_user["content"][0]["content"])
        self.assertTrue(payload.get("available"))
        for name in self.others:                               # tool results handed to the model are already clean
            self.assertNotIn(name, last_user["content"][0]["content"])

    def test_model_naming_a_competitor_is_redacted_by_final_guard(self):
        leak = f"You lost to {self.others[0]} who quoted lower."
        fake, _ = scripted_model([{"stop_reason": "end_turn", "content": [{"type": "text", "text": leak}]}])
        with mock.patch("requests.post", fake):
            connect_claude("sk-test")
            r = chat(self.c, self.v, None, "who beat me?")
        self.assertNotIn(self.others[0], r["reply"])
        self.assertIn("[another vendor]", r["reply"])
        self.assertTrue(any(a["reason"] == "competitor_name_in_text" for a in r["guard_audit"]))

    def test_bad_tool_args_are_reported_not_fatal(self):
        script = [
            {"stop_reason": "tool_use", "content": [{"type": "tool_use", "id": "t1", "name": "event_detail", "input": {"trade_request_id": "not-a-number"}}]},
            {"stop_reason": "end_turn", "content": [{"type": "text", "text": "I could not find that event; which one did you mean?"}]},
        ]
        fake, sent = scripted_model(script)
        with mock.patch("requests.post", fake):
            connect_claude("sk-test")
            r = chat(self.c, self.v, None, "show me event xyz")
        self.assertIn("which one", r["reply"])
        self.assertIn("error", json.loads(sent[2]["messages"][-1]["content"][0]["content"]))

    def test_api_failure_falls_back_to_offline(self):
        def boom(url, timeout=None, headers=None, json=None):
            if json.get("max_tokens") == 8:
                return FakeResp(200, {"content": [{"type": "text", "text": "pong"}], "stop_reason": "end_turn"})
            return FakeResp(529, {"error": "overloaded"})
        with mock.patch("requests.post", boom):
            connect_claude("sk-test")
            r = chat(self.c, self.v, None, "how do I do on counter-offers?")
        self.assertEqual(r["engine"], "offline")
        self.assertIn("fell back", r["reply"])

    def test_bad_key_is_rejected_and_engine_stays_offline(self):
        def unauthorized(url, timeout=None, headers=None, json=None):
            return FakeResp(401, {"error": {"message": "invalid x-api-key"}})
        with mock.patch("requests.post", unauthorized):
            res = connect_claude("sk-bad")
        self.assertFalse(res["ok"]); self.assertEqual(res["engine"], "offline")


if __name__ == "__main__":
    unittest.main()
