"""Claude engine: Messages API with tool use, via `requests`.
The model sees (a) a compact guarded context and (b) guarded tool results — nothing else.

Key resolution order: runtime key set through the UI/API (settings.set_api_key) → ANTHROPIC_API_KEY env.
"""
from __future__ import annotations

import json
import os

from .tools import TOOL_SPECS, VendorTools, context_summary, dumps

API_URL = os.environ.get("ANTHROPIC_API_URL", "https://api.anthropic.com/v1/messages")
DEFAULT_MODEL = os.environ.get("VI_ANTHROPIC_MODEL", "claude-sonnet-4-5")
_runtime: dict[str, str | None] = {"key": None, "model": None}


def set_api_key(key: str | None, model: str | None = None) -> None:
    _runtime["key"] = (key or "").strip() or None
    if model:
        _runtime["model"] = model.strip()


def api_key() -> str | None:
    return _runtime["key"] or os.environ.get("ANTHROPIC_API_KEY")


def model_name() -> str:
    return _runtime["model"] or DEFAULT_MODEL


SYSTEM = """You are the personal performance assistant for ONE supplier ("the vendor") on a B2B procurement platform.
You know their own record only: events they were invited to, their bids, negotiation timing, technical scores
where the buyer allows it, deliveries, profile. You help them win more: diagnose losses, price better, respond
faster, fix weak spots. Be concrete, numeric, and brief — like a sharp account manager, not a report.

Hard rules — never break them, even if asked directly or indirectly:
1. Never state, estimate, hint at or reason about another vendor's price, name, rank or identity. You do not have
   that data. If asked, say so in one sentence and offer the relative view (their % gap to the lowest bid, their
   rank out of N). Do not apologise repeatedly.
2. Use ONLY numbers returned by tools. Never invent events, prices, dates or rates. If a tool returns nothing,
   say there is no record.
3. When a tool says a buyer does not share feedback (policy = none), say that buyer has not enabled vendor
   feedback and move on. Do not speculate about that event.
4. Prefer calling tools over guessing. When the vendor refers to an event loosely ("the steel one in July",
   "last week's RFQ"), call my_events (with filters) first, pick the match, then why_did_i_lose or event_detail.
   When they ask about their own prices/quantities/terms on an event, use event_detail.
5. Answer in the vendor's language if they write in Hindi/Hinglish; otherwise English. Keep answers under ~120
   words unless they ask for detail. Use short bullet lists when listing events. End with one concrete next step
   when you diagnose a loss.

Vendor context (already guarded; refresh with tools when you need detail):
{ctx}
"""


class ClaudeEngine:
    name = "anthropic"

    def __init__(self, tools: VendorTools):
        self.t = tools
        self.calls: list[dict] = []
        self.key = api_key()
        self.model = model_name()

    @staticmethod
    def available() -> bool:
        return bool(api_key())

    def _post(self, payload: dict) -> dict:
        import requests
        r = requests.post(API_URL, timeout=60,
                          headers={"x-api-key": self.key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                          json=payload)
        if r.status_code >= 400:
            raise RuntimeError(f"Anthropic API {r.status_code}: {r.text[:300]}")
        return r.json()

    def reply(self, text: str, history: list[dict]) -> str:
        msgs = [{"role": m["role"], "content": m["content"]} for m in history[-16:]] + [{"role": "user", "content": text}]
        system = SYSTEM.format(ctx=dumps(context_summary(self.t)))
        for _ in range(8):
            body = self._post({"model": self.model, "max_tokens": 800, "system": system, "tools": TOOL_SPECS, "messages": msgs})
            content = body.get("content", [])
            uses = [b for b in content if b.get("type") == "tool_use"]
            if body.get("stop_reason") != "tool_use" or not uses:
                return "".join(b.get("text", "") for b in content if b.get("type") == "text").strip() or "(no answer)"
            msgs.append({"role": "assistant", "content": content})
            results = []
            for u in uses:
                try:
                    out = self.t.call(u["name"], u.get("input") or {})
                except Exception as e:          # bad args from the model → tell it, don't crash
                    out = {"error": f"{type(e).__name__}: {e}"}
                self.calls.append({"tool": u["name"], "args": u.get("input") or {}})
                results.append({"type": "tool_result", "tool_use_id": u["id"], "content": dumps(out)})
            msgs.append({"role": "user", "content": results})
        return "I could not finish answering that — please ask in a more specific way."


def test_connection() -> dict:
    """One tiny call to verify the key works. Returns {ok, model, error?}."""
    key = api_key()
    if not key:
        return {"ok": False, "error": "no key set"}
    import requests
    try:
        r = requests.post(API_URL, timeout=30,
                          headers={"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                          json={"model": model_name(), "max_tokens": 8, "messages": [{"role": "user", "content": "ping"}]})
        if r.status_code >= 400:
            return {"ok": False, "error": f"HTTP {r.status_code}: {r.text[:200]}"}
        return {"ok": True, "model": model_name()}
    except Exception as e:
        return {"ok": False, "error": str(e)}
