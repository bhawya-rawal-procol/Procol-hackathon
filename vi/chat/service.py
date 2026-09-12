"""Chat orchestration: pick engine → answer via tools → final guard pass on the text → persist + audit.

The final guard pass is belt-and-braces: tools already return guarded data, but the reply text is
scanned again so a competitor name can never reach the vendor even if an engine paraphrases carelessly.
"""
from __future__ import annotations

import json
import sqlite3
import uuid

from .. import audit
from ..db import now_iso, rows
from .llm import ClaudeEngine, api_key, model_name, set_api_key, test_connection
from .oai import OpenAIEngine, configured as oai_provider, settings as oai_settings
from .offline import HELP, OfflineEngine
from .tools import VendorTools, context_summary


def new_session() -> str:
    return uuid.uuid4().hex[:12]


def pick_engine(tools: VendorTools, force_offline: bool = False):
    """Claude first (a key pasted into the UI wins), then Groq/OpenAI-dialect, else offline."""
    if force_offline:
        return OfflineEngine(tools)
    if ClaudeEngine.available():
        return ClaudeEngine(tools)
    if OpenAIEngine.available():
        return OpenAIEngine(tools)
    return OfflineEngine(tools)


def engine_status() -> dict:
    if ClaudeEngine.available():
        return {"engine": "anthropic", "model": model_name(), "has_key": True}
    p = oai_provider()
    if p:
        return {"engine": p, "model": oai_settings(p)["model"], "has_key": True}
    return {"engine": "offline", "model": None, "has_key": bool(api_key())}


def connect_claude(key: str | None, model: str | None = None) -> dict:
    set_api_key(key, model)
    if not key:
        return {**engine_status(), "ok": True, "message": "Claude disconnected; offline fallback engine active."}
    res = test_connection()
    if not res["ok"]:
        set_api_key(None)
        return {**engine_status(), "ok": False, "message": res["error"]}
    return {**engine_status(), "ok": True, "message": f"Connected to {res['model']}."}


def history(conn: sqlite3.Connection, session_id: str, vendor: int) -> list[dict]:
    return rows(conn, """SELECT role, content, tools_json, engine, created_at FROM chat_messages
                         WHERE session_id=? AND vendor_company_id=? ORDER BY id""", (session_id, vendor))


def greeting(conn: sqlite3.Connection, vendor: int) -> dict:
    t = VendorTools(conn, vendor)
    ctx = context_summary(t)
    tot = ctx["totals"] or {}
    lost = [e for e in (ctx["recent_events"] or []) if e["outcome"] == "lost"]
    hint = f' Try: “why did I lose the {lost[0]["title"].split(" — ")[0]}?”' if lost else ""
    text = (f"Hi {ctx['vendor']}. I can see your own record here: {tot.get('won', 0)} won, {tot.get('lost', 0)} lost, "
            f"{tot.get('no_bid', 0)} skipped across {ctx['habits'].get('invites')} invites. I never see other vendors' prices or names.{hint}")
    return {"text": text, "suggestions": [
        "Which events did I lose recently?", "What price should I quote in " + (ctx["categories"] or ["Steel"])[0] + "?",
        "How do I do on counter-offers?", "How is my delivery performance?", "Where am I weak technically?", "Is my profile complete?"],
        **engine_status(), "policy": t.policy}


def chat(conn: sqlite3.Connection, vendor: int, session_id: str | None, text: str, force_offline: bool = False) -> dict:
    session_id = session_id or new_session()
    text = (text or "").strip()
    if not text:
        return {"session_id": session_id, "reply": HELP, "tools": [], "engine": "offline", "guard_audit": []}

    tools = VendorTools(conn, vendor)
    hist = history(conn, session_id, vendor)
    engine = pick_engine(tools, force_offline)
    try:
        reply = engine.reply(text, hist)
    except Exception as e:                      # LLM outage → fall back, never fail the vendor
        if engine.name != "offline":
            engine = OfflineEngine(tools)
            reply = engine.reply(text, hist) + "\n\n(Assistant fell back to offline mode.)"
        else:
            raise e

    final = tools.guard.apply({"reply": reply}, "relative_only")     # text-level redaction of any other vendor's name
    reply = final.payload.get("reply", reply)
    guard_audit = tools.audit + final.audit

    now = now_iso()
    conn.execute("INSERT INTO chat_messages(session_id, vendor_company_id, role, content, created_at) VALUES (?,?,?,?,?)",
                 (session_id, vendor, "user", text, now))
    conn.execute("""INSERT INTO chat_messages(session_id, vendor_company_id, role, content, tools_json, engine, guard_audit_json, created_at)
                    VALUES (?,?,?,?,?,?,?,?)""",
                 (session_id, vendor, "assistant", reply, json.dumps(engine.calls), engine.name, json.dumps(guard_audit), now))
    conn.commit()
    audit.log(conn, "vendor", vendor, "chat", {"session_id": session_id, "question": text, "engine": engine.name},
              guard_audit, reply)
    return {"session_id": session_id, "reply": reply, "tools": engine.calls, "engine": engine.name, "guard_audit": guard_audit}
