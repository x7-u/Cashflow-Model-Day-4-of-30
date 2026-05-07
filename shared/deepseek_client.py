"""DeepSeek client wrapper used from Day 4 onwards.

DeepSeek's API is OpenAI-compatible, so we use the openai SDK pointed at
the DeepSeek base URL. The function shapes mirror shared/llm_client.py so
call sites can swap providers with minimal churn.

Why DeepSeek for Day 4+:
- Roughly 5x to 15x cheaper than Claude Haiku 4.5 on the JSON-shaped
  workloads we use (around $0.0001 to $0.0005 per scenario versus
  $0.002 on Haiku).
- JSON mode (response_format={"type": "json_object"}) is reliable.
- Automatic prefix caching means we don't need explicit cache_control
  hints; identical prefixes within 24 hours hit the cache and are billed
  at the cache-hit rate.

Days 1 to 3 keep using Claude via shared/llm_client.py, untouched.
"""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Any

from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI, RateLimitError

from shared.config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL_FAST

log = logging.getLogger(__name__)

_default_client: OpenAI | None = None

# USD per 1M tokens. DeepSeek V4 indicative pricing as of 2026-05;
# verify against the live rate card. Cache hits are roughly 25% of cache miss.
PRICES: dict[str, tuple[float, float, float]] = {
    # model_substring : (input_miss_per_1M, input_hit_per_1M, output_per_1M)
    "deepseek-chat":     (0.27, 0.07, 1.10),
    "deepseek-reasoner": (0.55, 0.14, 2.19),
    "deepseek-v4":       (0.27, 0.07, 1.10),
}


@dataclass
class CallResult:
    text: str
    input_tokens: int
    output_tokens: int
    cache_hit_tokens: int
    cache_miss_tokens: int
    cost_usd: float
    model: str
    latency_ms: int = 0


def _get_default_client() -> OpenAI:
    global _default_client
    if _default_client is None:
        if not DEEPSEEK_API_KEY or DEEPSEEK_API_KEY.startswith("sk-placeholder"):
            raise RuntimeError(
                "DEEPSEEK_API_KEY is missing or still a placeholder. "
                "Copy .env.example to .env and add your real key."
            )
        _default_client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)
    return _default_client


def _client_for(api_key: str | None) -> OpenAI:
    if api_key:
        return OpenAI(api_key=api_key, base_url=DEEPSEEK_BASE_URL)
    return _get_default_client()


def _price_for(model: str) -> tuple[float, float, float]:
    for key, prices in PRICES.items():
        if key in model:
            return prices
    return (0.27, 0.07, 1.10)  # safe default = chat tier


def _estimate_cost(usage: Any, model: str) -> tuple[float, int, int, int, int]:
    """Return (cost_usd, input_tokens, output_tokens, cache_hit, cache_miss).

    DeepSeek's usage object exposes prompt_cache_hit_tokens and
    prompt_cache_miss_tokens when caching is in play. Falls back gracefully
    when those keys are absent.
    """
    in_miss_per_1m, in_hit_per_1m, out_per_1m = _price_for(model)
    inp = int(getattr(usage, "prompt_tokens", 0) or 0)
    out = int(getattr(usage, "completion_tokens", 0) or 0)
    # OpenAI SDK exposes provider-specific extras via the underlying dict.
    extras = getattr(usage, "model_extra", None) or {}
    if not extras and hasattr(usage, "to_dict"):
        try:
            extras = usage.to_dict()
        except Exception:
            extras = {}
    hit = int(extras.get("prompt_cache_hit_tokens", 0) or 0)
    miss = int(extras.get("prompt_cache_miss_tokens", inp - hit) or 0)
    if hit + miss <= 0:
        miss = inp
        hit = 0
    cost = (
        miss * in_miss_per_1m / 1_000_000
        + hit  * in_hit_per_1m  / 1_000_000
        + out  * out_per_1m     / 1_000_000
    )
    return (cost, inp, out, hit, miss)


def _parse_json_loose(raw: str) -> dict:
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.MULTILINE).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
        if m:
            return json.loads(m.group(0))
        raise


def ask_deepseek_call(
    prompt: str,
    *,
    system: str | None = None,
    max_tokens: int = 1000,
    model: str | None = None,
    api_key: str | None = None,
    json_mode: bool = False,
    temperature: float = 0.2,
    retries: int = 2,
    timeout: float = 30.0,
) -> CallResult:
    """Call DeepSeek with the given prompt and return text + token / cost stats."""
    client = _client_for(api_key)
    model = model or DEEPSEEK_MODEL_FAST

    messages: list[dict] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    kwargs: dict = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "timeout": timeout,
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}

    last_exc: Exception | None = None
    started = time.time()
    for attempt in range(retries + 1):
        try:
            resp = client.chat.completions.create(**kwargs)
            usage = getattr(resp, "usage", None)
            cost, inp, out, hit, miss = _estimate_cost(usage, model)
            text = (resp.choices[0].message.content or "") if resp.choices else ""
            return CallResult(
                text=text,
                input_tokens=inp,
                output_tokens=out,
                cache_hit_tokens=hit,
                cache_miss_tokens=miss,
                cost_usd=cost,
                model=model,
                latency_ms=int((time.time() - started) * 1000),
            )
        except (APIConnectionError, APITimeoutError, RateLimitError, APIStatusError) as e:
            last_exc = e
            if attempt < retries:
                time.sleep(0.5 * (2 ** attempt))
                continue
            raise
        except Exception as e:
            last_exc = e
            raise
    raise last_exc  # type: ignore[misc]


def ask_deepseek(
    prompt: str,
    system: str | None = None,
    max_tokens: int = 1000,
    **kwargs: Any,
) -> str:
    """Backwards-compatible: text-only response."""
    return ask_deepseek_call(prompt, system=system, max_tokens=max_tokens, **kwargs).text


def ask_deepseek_json(
    prompt: str,
    *,
    system: str | None = None,
    max_tokens: int = 1500,
    model: str | None = None,
    api_key: str | None = None,
) -> dict:
    """Ask for a JSON object. Tolerates code fences and stray prose."""
    sys_payload = system
    if sys_payload:
        sys_payload = sys_payload + "\n\nReturn ONLY a single valid JSON object. No prose, no markdown fences."
    else:
        sys_payload = "Return ONLY a single valid JSON object. No prose, no markdown fences."
    res = ask_deepseek_call(
        prompt,
        system=sys_payload,
        max_tokens=max_tokens,
        model=model,
        api_key=api_key,
        json_mode=True,
    )
    return _parse_json_loose(res.text)


def ask_deepseek_json_with_stats(
    prompt: str,
    *,
    system: str | None = None,
    max_tokens: int = 1500,
    model: str | None = None,
    api_key: str | None = None,
) -> tuple[dict, CallResult]:
    """Same as ask_deepseek_json but also returns the raw CallResult (cost stats)."""
    sys_payload = system
    if sys_payload:
        sys_payload = sys_payload + "\n\nReturn ONLY a single valid JSON object. No prose, no markdown fences."
    else:
        sys_payload = "Return ONLY a single valid JSON object. No prose, no markdown fences."
    res = ask_deepseek_call(
        prompt,
        system=sys_payload,
        max_tokens=max_tokens,
        model=model,
        api_key=api_key,
        json_mode=True,
    )
    return _parse_json_loose(res.text), res
