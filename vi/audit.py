"""Every recommendation the system makes is logged with its inputs and the guard's decisions.
Nothing here is autonomous; this is the paper trail that makes 'recommendations only' auditable."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Any

from .db import now_iso


def log(conn: sqlite3.Connection, persona: str, actor_id: int | None, action: str,
        inputs: dict[str, Any] | None, guard_audit: list[dict] | None, output: Any) -> None:
    digest = hashlib.sha256(json.dumps(output, sort_keys=True, default=str).encode()).hexdigest()[:16]
    conn.execute(
        "INSERT INTO audit_log(at, persona, actor_id, action, inputs_json, guard_json, output_hash) VALUES (?,?,?,?,?,?,?)",
        (now_iso(), persona, actor_id, action,
         json.dumps(inputs, default=str) if inputs is not None else None,
         json.dumps(guard_audit, default=str) if guard_audit is not None else None, digest))
    conn.commit()
