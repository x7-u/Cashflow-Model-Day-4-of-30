"""Shared config -- loads .env once and exposes constants."""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env", override=True)

ANTHROPIC_API_KEY: str | None = os.getenv("ANTHROPIC_API_KEY")
DEEPSEEK_API_KEY: str | None = os.getenv("DEEPSEEK_API_KEY")
FRED_API_KEY: str | None = os.getenv("FRED_API_KEY")
NEWS_API_KEY: str | None = os.getenv("NEWS_API_KEY")
BASE_CURRENCY: str = os.getenv("BASE_CURRENCY", "GBP")

# Default Claude model for general-purpose use.
# (Brief lists claude-sonnet-4-20250514, that alias is retired; current Sonnet
# is claude-sonnet-4-6.)
CLAUDE_MODEL: str = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")

# Cost-conscious Claude model. Prefer this for short structured-JSON tasks
# on Days 1 to 3 (Day 4 onwards uses DeepSeek instead).
CLAUDE_MODEL_FAST: str = os.getenv("CLAUDE_MODEL_FAST", "claude-haiku-4-5-20251001")

# Reasoning-heavy Claude model. Prefer this only when nuance matters more than cost.
CLAUDE_MODEL_DEEP: str = os.getenv("CLAUDE_MODEL_DEEP", "claude-opus-4-7")

# DeepSeek default model. Day 4 onwards uses DeepSeek V4 (latest chat alias,
# which currently resolves to V4) for cost efficiency. Roughly 5x to 15x
# cheaper than Claude Haiku 4.5 on JSON-shaped finance workloads.
DEEPSEEK_MODEL_FAST: str = os.getenv("DEEPSEEK_MODEL_FAST", "deepseek-chat")

# DeepSeek reasoning model alias. Reserved for tasks where step-by-step
# reasoning matters; uses the R-series under the hood.
DEEPSEEK_MODEL_DEEP: str = os.getenv("DEEPSEEK_MODEL_DEEP", "deepseek-reasoner")

# DeepSeek API base URL. Override only if you are routing via a proxy.
DEEPSEEK_BASE_URL: str = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
