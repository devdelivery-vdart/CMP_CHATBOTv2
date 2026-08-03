"""
Loads all configuration (DB credentials + API keys) from environment
variables / a local .env file. Nothing sensitive is ever hardcoded here.
"""

import os
from dotenv import load_dotenv

# Loads variables from a ".env" file sitting next to this script, if present.
load_dotenv()


def _require(name: str) -> str:
    """Fetch an env var, or fail loudly with a clear message if it's missing."""
    value = os.getenv(name)
    if not value:
        raise RuntimeError(
            f"Missing required environment variable: {name}. "
            f"Did you copy .env.example to .env and fill it in?"
        )
    return value


# ---- Database config ----
DB_HOST = os.getenv("DB_HOST", "127.0.0.1")
DB_PORT = int(os.getenv("DB_PORT", "3306"))
DB_USER = _require("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
DB_NAME = _require("DB_NAME")

# ---- LLM provider keys ----
# Both are optional at the config level -- whichever provider(s) are
# actually listed in providers/provider_chain.py determine what's really
# needed. If you remove a provider from that chain, its key here becomes
# irrelevant.
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

if not GROQ_API_KEY and not OPENAI_API_KEY:
    print(
        "[config] Warning: neither GROQ_API_KEY nor OPENAI_API_KEY is set. "
        "At least one provider needs to be configured for the pipeline to work."
    )

# NOTE: the allow-list of queryable tables is NOT defined here anymore.
# It's derived automatically from whatever's registered (and enabled) in
# the tables/ folder -- see tables/registry.py. This means adding a new
# masked view never requires touching config.py.
