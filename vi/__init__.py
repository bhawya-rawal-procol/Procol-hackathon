"""Vendor Intelligence prototype. Loads .env (if present) before anything reads os.environ."""
from .env import load as _load_env

_load_env()
