"""Minimal .env loader — no dependency, no magic, ~40 lines.

Reads KEY=VALUE lines from the project's .env into os.environ at package import.
Real environment variables always win, so `ANTHROPIC_API_KEY=x make serve` still
overrides the file. Nothing here ever writes a key back to disk.
"""
from __future__ import annotations

import os
from pathlib import Path

DEFAULT_PATH = Path(__file__).resolve().parent.parent / ".env"


def parse(text: str) -> dict:
    """KEY=VALUE per line. Supports `export KEY=v`, # comments, and quoted values."""
    out: dict = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        key, sep, val = line.partition("=")
        key, val = key.strip(), val.strip()
        if not sep or not key:
            continue
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1]
        elif " #" in val:
            val = val.split(" #", 1)[0].strip()
        out[key] = val
    return out


def load(path=None, override: bool = False) -> dict:
    """Apply .env to os.environ. Returns only the keys it actually set."""
    p = Path(path or os.environ.get("VI_ENV_FILE") or DEFAULT_PATH)
    if not p.is_file():
        return {}
    applied = {}
    for k, v in parse(p.read_text()).items():
        if override or not os.environ.get(k):
            os.environ[k] = v
            applied[k] = v
    return applied
