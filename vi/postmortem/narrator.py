"""Turns GUARDED check results into a 3-line vendor-facing story plus one 'next time' action.

Two implementations, same contract:
  template  — deterministic, offline, always available
  anthropic — used only when ANTHROPIC_API_KEY is set; receives ONLY the guarded payload

Contract: narrate(checks, ctx) -> {"narration": str, "next_action": str, "narrator": "template"|"anthropic"}
"""
from __future__ import annotations

import json
import os

from .checks import SEVERITY_ORDER

NEXT_ACTION = {
    "timing": "Set a same-day rule for counter-offers and best-offer requests — replies that land after the window are treated as declines.",
    "price": "Before the next event in this category, price within 3% of your own best recent quote; your win rate falls sharply above that.",
    "technical": "Refresh the weakest section's documentation before the next RFP — certifications and past-performance evidence are usually the gap.",
    "terms": "Match the buyer's asked payment and delivery terms in the quote itself; negotiate them separately if you must.",
}
ORDER = ["timing", "price", "technical", "terms"]


def _lead(checks: dict) -> str | None:
    ranked = sorted(((SEVERITY_ORDER.get(c.get("severity", "na"), -1), -ORDER.index(k), k)
                     for k, c in checks.items() if k in ORDER), reverse=True)
    for sev, _, k in ranked:
        if sev >= 1:
            return k
    return None


def template_narrate(checks: dict, ctx: dict) -> dict:
    lead = _lead(checks)
    lines = []
    if ctx.get("won"):
        lines.append(f"You won {ctx['title']}.")
    elif lead is None:
        lines.append(f"You lost {ctx['title']} on a close call — none of the four checks flagged a clear cause.")
    else:
        lines.append(f"You lost {ctx['title']}. The main factor was {lead}.")
    for k in ORDER:
        c = checks.get(k)
        if c and c.get("severity") not in (None, "na") and (k == lead or c.get("severity") in ("high", "medium")):
            lines.append(c["signal"])
    lines = lines[:3]
    if len(lines) < 3:
        ok_lines = [checks[k]["signal"] for k in ORDER if k in checks and checks[k].get("severity") == "ok"]
        lines += ok_lines[: 3 - len(lines)]
    action = NEXT_ACTION[lead] if lead else "Keep doing what you did — the loss was not driven by anything in your control here."
    return {"narration": " ".join(lines), "next_action": action, "narrator": "template"}


def anthropic_narrate(checks: dict, ctx: dict) -> dict | None:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return None
    try:
        import requests
    except ImportError:
        return None
    safe_ctx = {"title": ctx["title"], "rfx_mode": ctx["rfx_mode"], "category": ctx["category"], "won": ctx["won"]}
    prompt = (
        "You write short, direct feedback to a supplier about a sourcing event they lost. "
        "You are given ONLY that supplier's own figures and relative figures (e.g. % above the lowest bid). "
        "Never invent competitor prices, names or ranks. Write exactly 3 sentences of narration, then one line "
        "starting with 'Next time:' with a single concrete action.\n\n"
        f"Event: {json.dumps(safe_ctx)}\nChecks: {json.dumps(checks)}"
    )
    try:
        api_url = os.environ.get("ANTHROPIC_API_URL", "https://api.anthropic.com/v1/messages")
        r = requests.post(api_url, timeout=20,
                          headers={"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                          json={"model": os.environ.get("VI_ANTHROPIC_MODEL", "claude-sonnet-4-5"), "max_tokens": 300,
                                "messages": [{"role": "user", "content": prompt}]})
        r.raise_for_status()
        text = "".join(b.get("text", "") for b in r.json().get("content", []))
        narration, _, action = text.partition("Next time:")
        return {"narration": narration.strip(), "next_action": action.strip() or NEXT_ACTION.get(_lead(checks) or "price"),
                "narrator": "anthropic"}
    except Exception:
        return None


def narrate(checks: dict, ctx: dict) -> dict:
    return anthropic_narrate(checks, ctx) or template_narrate(checks, ctx)
