"""Tests must not inherit the developer's .env — a real key in it would make the engine-selection
tests assert against a live provider. Runs before `vi` is imported, so vi/env.py loads nothing."""
import os

os.environ["VI_ENV_FILE"] = os.path.join(os.path.dirname(__file__), "no-such.env")
for _var in ("ANTHROPIC_API_KEY", "ANTHROPIC_API_URL", "VI_ANTHROPIC_MODEL",
             "GROQ_API_KEY", "GROQ_API_URL", "GROQ_MODEL",
             "OPENAI_API_KEY", "OPENAI_API_URL", "OPENAI_MODEL",
             "GROK_API_KEY", "XAI_API_KEY", "VI_LLM_PROVIDER"):
    os.environ.pop(_var, None)
