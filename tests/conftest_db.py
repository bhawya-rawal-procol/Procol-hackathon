"""Shared test fixture: a freshly seeded DB with vendor_profiles built, created once per test run."""
from __future__ import annotations

import os
import tempfile
from datetime import datetime, timezone
from functools import lru_cache

from vi.db import connect
from vi.facts.build import build_all
from vi.seed.generate import NOW, seed

AS_OF = NOW


@lru_cache(maxsize=1)
def test_db_path() -> str:
    path = os.path.join(tempfile.mkdtemp(prefix="vi-test-"), "vi.db")
    seed(path, seed=42)
    conn = connect(path)
    build_all(conn, AS_OF)
    conn.close()
    return path


def conn():
    return connect(test_db_path())


def vendor_id(conn_, archetype: str) -> int:
    return conn_.execute("SELECT id FROM companies WHERE archetype=?", (archetype,)).fetchone()[0]
