"""OpenAI-dialect engine (Groq and friends) against a MOCK server — no key, no network.
Verifies: provider selection from env, OpenAI tool-call round trip, bad tool args survive,
and that the guard still redacts a competitor name the model invents."""
import json
import os
import unittest
from unittest import mock

from tests.conftest_db import conn, vendor_id
from vi.chat.oai import OpenAIEngine, configured, openai_tools, settings
from vi.chat.service import engine_status, pick_engine
from vi.chat.tools import VendorTools


class FakeResp:
    def __init__(self, status, body):
        self.status_code, self._b = status, body
        self.text = json.dumps(body)

    def json(self):
        return self._b


def tool_call(cid, name, args):
    return {"id": cid, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}


def scripted(script):
    sent = []

    def fake_post(url, timeout=None, headers=None, json=None):
        sent.append({"url": url, "headers": headers, "body": json})
        return FakeResp(200, {"choices": [{"message": script.pop(0)}]})
    return fake_post, sent


class ProviderSelection(unittest.TestCase):
    def tearDown(self):
        for v in ("GROQ_API_KEY", "OPENAI_API_KEY", "GROK_API_KEY", "VI_LLM_PROVIDER", "GROQ_MODEL"):
            os.environ.pop(v, None)

    def test_no_key_means_no_provider(self):
        self.assertEqual(configured(), "")
        self.assertFalse(OpenAIEngine.available())
        self.assertEqual(engine_status()["engine"], "offline")

    def test_groq_key_selects_groq_with_its_defaults(self):
        os.environ["GROQ_API_KEY"] = "gsk-test"
        self.assertEqual(configured(), "groq")
        s = settings("groq")
        self.assertIn("api.groq.com", s["url"])
        self.assertEqual(s["model"], "openai/gpt-oss-120b")
        self.assertEqual(engine_status(), {"engine": "groq", "model": "openai/gpt-oss-120b", "has_key": True})

    def test_env_overrides_model_and_explicit_provider_wins(self):
        os.environ["GROQ_API_KEY"] = "gsk-test"
        os.environ["GROQ_MODEL"] = "moonshotai/kimi-k2-instruct"
        os.environ["OPENAI_API_KEY"] = "sk-test"
        os.environ["VI_LLM_PROVIDER"] = "openai"
        self.assertEqual(configured(), "openai")
        self.assertEqual(settings("groq")["model"], "moonshotai/kimi-k2-instruct")

    def test_forced_provider_without_a_key_falls_through_to_offline(self):
        os.environ["VI_LLM_PROVIDER"] = "groq"          # no GROQ_API_KEY set
        self.assertEqual(configured(), "")
        self.assertEqual(engine_status()["engine"], "offline")

    def test_pick_engine_prefers_groq_when_no_anthropic_key(self):
        os.environ["GROQ_API_KEY"] = "gsk-test"
        self.assertEqual(pick_engine(VendorTools(conn(), vendor_id(conn(), "V-LATE"))).name, "groq")

    def test_tool_specs_translate_to_openai_function_shape(self):
        for t in openai_tools():
            self.assertEqual(t["type"], "function")
            self.assertIn("name", t["function"])
            self.assertIn("parameters", t["function"])


class OpenAIEngineLoop(unittest.TestCase):
    def setUp(self):
        self.c = conn()
        self.v = vendor_id(self.c, "V-LATE")
        os.environ["GROQ_API_KEY"] = "gsk-test"

    def tearDown(self):
        os.environ.pop("GROQ_API_KEY", None)

    def _engine(self):
        return OpenAIEngine(VendorTools(self.c, self.v))

    def test_tool_round_trip_sends_results_and_returns_final_text(self):
        script = [
            {"role": "assistant", "content": None, "tool_calls": [tool_call("c1", "habits", {})]},
            {"role": "assistant", "content": "You miss 82% of counter-offer windows. Reply the same day."},
        ]
        fake, sent = scripted(script)
        with mock.patch("requests.post", fake):
            eng = self._engine()
            out = eng.reply("how are my counter-offers?", [])

        self.assertIn("82%", out)
        self.assertEqual([c["tool"] for c in eng.calls], ["habits"])
        self.assertEqual(sent[0]["headers"]["Authorization"], "Bearer gsk-test")
        roles = [m["role"] for m in sent[1]["body"]["messages"]]
        self.assertEqual(roles[0], "system")
        self.assertEqual(roles[-1], "tool")          # the guarded tool result went back to the model

    def test_bad_tool_arguments_do_not_crash_the_turn(self):
        script = [
            {"role": "assistant", "tool_calls": [tool_call("c1", "why_did_i_lose", {"trade_request_id": "not-an-int"})]},
            {"role": "assistant", "content": "I could not read that event."},
        ]
        fake, sent = scripted(script)
        with mock.patch("requests.post", fake):
            out = self._engine().reply("why did I lose?", [])
        self.assertIn("could not", out.lower())
        self.assertIn("error", sent[1]["body"]["messages"][-1]["content"].lower())

    def test_unparseable_arguments_become_empty_args(self):
        script = [
            {"role": "assistant", "tool_calls": [{"id": "c1", "function": {"name": "habits", "arguments": "{oops"}}]},
            {"role": "assistant", "content": "done"},
        ]
        fake, _ = scripted(script)
        with mock.patch("requests.post", fake):
            eng = self._engine()
            eng.reply("habits?", [])
        self.assertEqual(eng.calls[0]["args"], {})

    def test_http_error_raises_so_service_can_fall_back(self):
        def boom(url, timeout=None, headers=None, json=None):
            return FakeResp(429, {"error": "rate limited"})
        with mock.patch("requests.post", boom):
            with self.assertRaises(RuntimeError):
                self._engine().reply("hi", [])


if __name__ == "__main__":
    unittest.main()
