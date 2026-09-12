"""OpenAI-dialect chat engine: Groq, Slingring's /v1/chat/completions, xAI, OpenAI.

Same contract as ClaudeEngine — .name, .calls, .available(), .reply(text, history) — so
service.py swaps one for the other. The model still only ever sees guarded data:
VendorTools.call() runs the ConfidentialityGuard before any result is handed back, and
service.py re-scans the final text.

Configure in .env (first provider with a key wins; VI_LLM_PROVIDER forces one):
    GROQ_API_KEY   / GROQ_API_URL   / GROQ_MODEL
    OPENAI_API_KEY / OPENAI_API_URL / OPENAI_MODEL      (any OpenAI-compatible endpoint)
    GROK_API_KEY   / GROK_API_URL   / GROK_MODEL
"""
from __future__ import annotations

import json
import os
import re
import time

from .llm import SYSTEM
from .tools import TOOL_SPECS, VendorTools, context_summary, dumps

PROVIDERS = {
    "groq": {"keys": ("GROQ_API_KEY",), "url": "GROQ_API_URL", "model": "GROQ_MODEL",
             "default_url": "https://api.groq.com/openai/v1/chat/completions",
             "default_model": "openai/gpt-oss-120b"},
    "openai": {"keys": ("OPENAI_API_KEY",), "url": "OPENAI_API_URL", "model": "OPENAI_MODEL",
               "default_url": "https://api.openai.com/v1/chat/completions",
               "default_model": "gpt-4o"},
    "grok": {"keys": ("GROK_API_KEY", "XAI_API_KEY"), "url": "GROK_API_URL", "model": "GROK_MODEL",
             "default_url": "https://api.x.ai/v1/chat/completions",
             "default_model": "grok-4"},
}


def _first_env(names) -> str:
    return next((os.environ[n] for n in names if os.environ.get(n)), "")


def configured() -> str:
    """Which OpenAI-dialect provider to use, honouring an explicit VI_LLM_PROVIDER."""
    forced = (os.environ.get("VI_LLM_PROVIDER") or "").strip().lower()
    if forced:
        return forced if forced in PROVIDERS and _first_env(PROVIDERS[forced]["keys"]) else ""
    return next((p for p, c in PROVIDERS.items() if _first_env(c["keys"])), "")


def settings(provider: str) -> dict:
    c = PROVIDERS[provider]
    return {"key": _first_env(c["keys"]),
            "url": os.environ.get(c["url"]) or c["default_url"],
            "model": os.environ.get(c["model"]) or c["default_model"]}


def openai_tools() -> list:
    """Anthropic tool specs → OpenAI function specs, so both engines share one source of truth."""
    return [{"type": "function",
             "function": {"name": t["name"], "description": t["description"], "parameters": t["input_schema"]}}
            for t in TOOL_SPECS]


def _retry_after(resp) -> float:
    """Seconds to wait: the Retry-After header, else the 'try again in 13.4s' the body suggests."""
    hdr = (getattr(resp, "headers", None) or {}).get("retry-after")
    try:
        return float(hdr)
    except (TypeError, ValueError):
        pass
    m = re.search(r"try again in ([0-9.]+)s", getattr(resp, "text", "") or "")
    return float(m.group(1)) + 0.5 if m else 5.0


def _args(raw) -> dict:
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw or "{}")
    except (ValueError, TypeError):
        return {}


class OpenAIEngine:
    """Config is read at construction, so a .env edit takes effect on the next restart."""

    def __init__(self, tools: VendorTools, provider: str = ""):
        self.t = tools
        self.calls: list = []
        self.provider = provider or configured() or "openai"
        s = settings(self.provider)
        self.key, self.url, self.model = s["key"], s["url"], s["model"]
        self.name = self.provider

    @staticmethod
    def available() -> bool:
        return bool(configured())

    def _post(self, payload: dict, attempts: int = 3) -> dict:
        """429 is normal on free tiers — wait the hint the provider gives us, then retry."""
        import requests
        for i in range(attempts):
            r = requests.post(self.url, timeout=60,
                              headers={"Authorization": "Bearer " + self.key, "content-type": "application/json"},
                              json=payload)
            if r.status_code == 429 and i < attempts - 1:
                time.sleep(min(_retry_after(r), 20.0))
                continue
            if r.status_code >= 400:
                raise RuntimeError(f"{self.provider} API {r.status_code}: {r.text[:300]}")
            return r.json()
        raise RuntimeError(f"{self.provider} API: rate limited after {attempts} attempts")

    def reply(self, text: str, history: list) -> str:
        msgs = [{"role": "system", "content": SYSTEM.format(ctx=dumps(context_summary(self.t)))}]
        msgs += [{"role": m["role"], "content": m["content"]} for m in history[-16:]]
        msgs.append({"role": "user", "content": text})
        for _ in range(8):
            body = self._post({"model": self.model, "max_tokens": 800, "messages": msgs,
                               "tools": openai_tools(), "tool_choice": "auto"})
            msg = (body.get("choices") or [{}])[0].get("message") or {}
            uses = msg.get("tool_calls") or []
            if not uses:
                return (msg.get("content") or "").strip() or "(no answer)"
            msgs.append({"role": "assistant", "content": msg.get("content") or "", "tool_calls": uses})
            for u in uses:
                fn = u.get("function") or {}
                args = _args(fn.get("arguments"))
                try:
                    out = self.t.call(fn.get("name"), args)
                except Exception as e:           # bad args from the model → tell it, don't crash
                    out = {"error": f"{type(e).__name__}: {e}"}
                self.calls.append({"tool": fn.get("name"), "args": args})
                msgs.append({"role": "tool", "tool_call_id": u.get("id"), "content": dumps(out)})
        return "I could not finish answering that — please ask in a more specific way."


def test_connection() -> dict:
    """One tiny call to verify the configured key works. Returns {ok, provider, model, error?}."""
    p = configured()
    if not p:
        return {"ok": False, "error": "no OpenAI-dialect key set"}
    s = settings(p)
    import requests
    try:
        r = requests.post(s["url"], timeout=30,
                          headers={"Authorization": "Bearer " + s["key"], "content-type": "application/json"},
                          json={"model": s["model"], "max_tokens": 8,
                                "messages": [{"role": "user", "content": "ping"}]})
        if r.status_code >= 400:
            return {"ok": False, "provider": p, "error": f"HTTP {r.status_code}: {r.text[:200]}"}
        return {"ok": True, "provider": p, "model": s["model"]}
    except Exception as e:
        return {"ok": False, "provider": p, "error": str(e)}
