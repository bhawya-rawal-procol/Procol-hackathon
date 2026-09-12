"""SQLite access helpers. Plain SQL only — no ORM — so every query ports to Rails/Postgres."""
from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

DEFAULT_DB = os.environ.get("VI_DB", "data/vendor_intelligence.db")
SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def connect(db_path: str = DEFAULT_DB) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_PATH.read_text())
    conn.commit()


def reset_db(db_path: str) -> sqlite3.Connection:
    """Drop the file and rebuild the schema. Used by the seeder."""
    p = Path(db_path)
    for suffix in ("", "-wal", "-shm"):
        f = Path(str(p) + suffix)
        if f.exists():
            f.unlink()
    conn = connect(db_path)
    init_schema(conn)
    return conn


@contextmanager
def tx(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def rows(conn: sqlite3.Connection, sql: str, params: tuple | dict = ()) -> list[dict[str, Any]]:
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def one(conn: sqlite3.Connection, sql: str, params: tuple | dict = ()) -> dict[str, Any] | None:
    r = conn.execute(sql, params).fetchone()
    return dict(r) if r else None


def scalar(conn: sqlite3.Connection, sql: str, params: tuple | dict = ()) -> Any:
    r = conn.execute(sql, params).fetchone()
    return r[0] if r else None


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def iso(dt: datetime) -> str:
    return dt.replace(microsecond=0).isoformat()
