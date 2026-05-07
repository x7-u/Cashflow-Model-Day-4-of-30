"""Day 4. Orchestrator: parse, compute, narrate.

Two main entry points:
- analyse() runs a deterministic 13-week forecast from a workbook. No AI.
- run_scenario() takes a base AnalysisResult plus a free-text user prompt,
  asks DeepSeek V4 to parse the prompt into a typed Shock, applies the
  shock, and asks DeepSeek to write a controller-voiced summary.

The AI never mutates the forecast directly. It parses intent into a
Shock; scenario.apply_shock() is what changes the maths. This keeps the
output reproducible and auditable.
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cashflow_maths import (
    HeadlineStats,
    WeekRow,
    aggregate_by_category,
    aggregate_by_type,
    compute_weeks,
    headline_stats,
    resolve_buffer,
)
from cashflow_schema import (
    CashflowLine,
    CashflowMetadata,
    parse_inputs,
)
from scenario import Shock, apply_shock, shock_from_dict, shock_to_dict

from shared.config import DEEPSEEK_MODEL_FAST
from shared.deepseek_client import ask_deepseek_json_with_stats

# ---- Result dataclasses ---------------------------------------------

@dataclass
class Commentary:
    headline: str = ""
    summary: str = ""
    interpretation: str = ""
    actions: list[str] = field(default_factory=list)
    cost_usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_hit_tokens: int = 0
    model: str = ""
    skipped: bool = False
    error: str | None = None


@dataclass
class AnalysisResult:
    metadata: CashflowMetadata
    lines: list[CashflowLine]
    weeks: list[WeekRow]
    headline: HeadlineStats
    type_totals: dict[str, float]
    category_totals: dict[str, float]
    warnings: list[str]
    source_filename: str = ""
    elapsed_ms: int = 0
    commentary: Commentary | None = None  # AI-drafted controller commentary on the base run; None if AI skipped


@dataclass
class ScenarioResult:
    base: AnalysisResult
    scenario: AnalysisResult
    shock: Shock
    user_prompt: str
    commentary: Commentary


# ---- Top-level analyse() --------------------------------------------

def analyse(
    *,
    file_bytes: bytes | None = None,
    path: Path | str | None = None,
    source_filename: str = "",
    skip_ai: bool = False,
    model: str | None = None,
    api_key: str | None = None,
) -> AnalysisResult:
    """Run the 13-week forecast and optionally narrate it with DeepSeek.

    The deterministic maths always runs. AI commentary is opt-out via
    ``skip_ai=True`` (used by tests + comparison flows). Cost is around
    $0.0005 per call on ``deepseek-chat``, comfortably under 1¢.
    """
    import time as _time
    started = _time.time()

    parsed = parse_inputs(
        file_bytes=file_bytes, path=path, source_filename=source_filename,
    )
    weeks = compute_weeks(parsed.lines, parsed.metadata)
    buffer = resolve_buffer(parsed.lines, parsed.metadata)
    headline = headline_stats(weeks, parsed.metadata, buffer=buffer)
    type_totals = aggregate_by_type(parsed.lines)

    result = AnalysisResult(
        metadata=parsed.metadata,
        lines=parsed.lines,
        weeks=weeks,
        headline=headline,
        type_totals=type_totals,
        category_totals=aggregate_by_category(parsed.lines),
        warnings=parsed.warnings,
        source_filename=source_filename,
        elapsed_ms=0,  # set below after the AI call
    )

    if skip_ai:
        result.commentary = Commentary(skipped=True)
    else:
        result.commentary = narrate_forecast(
            base=result, model=model, api_key=api_key,
        )

    result.elapsed_ms = int((_time.time() - started) * 1000)
    return result


# ---- Base-run AI commentary -----------------------------------------

NARRATE_SYSTEM_PROMPT = (
    "You are a senior financial controller drafting commentary on a "
    "13-week cash flow forecast for the board pack. Write in first-person "
    "plural ('we', 'our'). Cite specific GBP figures. Attribute drivers "
    "to named line items or categories. Material items first. No hedging, "
    "no consultancy filler. Two to three sentences in the summary."
)

_NARRATE_SCHEMA_HINT = (
    '{\n'
    '  "headline": "1 sentence verdict citing the headline GBP figure",\n'
    '  "summary":  "2 to 3 sentences in controller voice, cite specific GBP figures",\n'
    '  "drivers":  ["short bullet on a key inflow or outflow", "short bullet"],\n'
    '  "actions":  ["short imperative", "short imperative"]\n'
    '}'
)


def narrate_forecast(
    *,
    base: AnalysisResult,
    model: str | None = None,
    api_key: str | None = None,
) -> Commentary:
    """Ask DeepSeek to write a controller-voice summary of the base forecast.

    Returns a Commentary; on API failure the Commentary carries the error
    so the UI can render a stub card instead of crashing the analysis.
    """
    digest = _build_narrate_prompt(base=base)
    try:
        data, stats = ask_deepseek_json_with_stats(
            digest,
            system=NARRATE_SYSTEM_PROMPT
                  + "\n\nSchema for your reply:\n" + _NARRATE_SCHEMA_HINT,
            max_tokens=400,
            model=(model or DEEPSEEK_MODEL_FAST),
            api_key=api_key,
        )
    except Exception as e:
        return Commentary(
            headline=f"[AI commentary unavailable: {_scrub(e)}]",
            error=_scrub(e),
            model=model or DEEPSEEK_MODEL_FAST,
        )

    return Commentary(
        headline=str(data.get("headline") or "")[:280],
        summary=str(data.get("summary") or ""),
        interpretation="",  # not used on base runs
        actions=(
            [str(x) for x in (data.get("drivers") or [])][:5]
            + [str(x) for x in (data.get("actions") or [])][:5]
        ),
        cost_usd=stats.cost_usd,
        input_tokens=stats.input_tokens,
        output_tokens=stats.output_tokens,
        cache_hit_tokens=stats.cache_hit_tokens,
        model=stats.model,
    )


def _build_narrate_prompt(*, base: AnalysisResult) -> str:
    h = base.headline
    lines: list[str] = []
    lines.append(
        f"Company: {base.metadata.company}  |  "
        f"Period: {base.metadata.period_label}  |  "
        f"Currency: {base.metadata.currency}"
    )
    lines.append(
        f"Opening: {_g(base.metadata.opening_balance)}  |  "
        f"Buffer: {_g(h.buffer_used)}"
    )
    lines.append("")

    lines.append("Headline (base run):")
    lines.append("opening|closing|min|min_w|max|max_w|weeks_below_zero|runway_w|total_in|total_out|cum_net|red|amber|green")
    lines.append("|".join([
        _g(h.opening_balance), _g(h.closing_balance),
        _g(h.min_balance), str(h.min_balance_week),
        _g(h.max_balance), str(h.max_balance_week),
        str(h.weeks_below_zero),
        ("none" if h.runway_weeks is None else str(h.runway_weeks)),
        _g(h.total_inflow), _g(h.total_outflow),
        _g(h.cumulative_net),
        str(h.rag_counts.get("red", 0)),
        str(h.rag_counts.get("amber", 0)),
        str(h.rag_counts.get("green", 0)),
    ]))
    lines.append("")

    lines.append("Type totals (across 13 weeks):")
    lines.append("type|total_gbp")
    for t, v in base.type_totals.items():
        lines.append(f"{t}|{_g(v)}")
    lines.append("")

    lines.append("Closing balance per week:")
    lines.append("week|closing|rag")
    for w in base.weeks:
        lines.append(f"{w.week}|{_g(w.closing)}|{w.rag}")
    lines.append("")

    return "\n".join(lines)


# ---- Scenario AI prompt ---------------------------------------------

SYSTEM_PROMPT = (
    "You are a senior financial controller advising on a 13-week cash "
    "flow model. The user describes a hypothetical scenario in plain "
    "English. Your job is two things at once: (1) parse the scenario "
    "into a typed shock the application can apply deterministically, "
    "and (2) write a short controller-voice summary of the impact. "
    "Be concrete. Cite GBP figures. Material items first. No hedging."
)


_SHOCK_TYPES_HINT = (
    "revenue_pct (magnitude is a fraction like -0.20 for -20%), "
    "cost_pct (fraction), "
    "payment_delay_days (integer days), "
    "payroll_delta (flat GBP per week), "
    "oneoff_amount (positive GBP, set one_off_kind = 'receipt' or 'payment' and one_off_week = 1..13), "
    "tax_defer_weeks (integer weeks)."
)


_SCHEMA_HINT = (
    '{\n'
    '  "interpretation": "1 sentence echoing back what you parsed (e.g. \\"Apply -20% to all receipts for weeks 1 to 3\\")",\n'
    '  "shock": {\n'
    '    "type":   "one of: revenue_pct, cost_pct, payment_delay_days, payroll_delta, oneoff_amount, tax_defer_weeks",\n'
    '    "magnitude": -0.20,\n'
    '    "weeks":  [1, 2, 3],\n'
    '    "category_filter": null,\n'
    '    "one_off_week":  null,\n'
    '    "one_off_kind":  "receipt"\n'
    '  },\n'
    '  "headline": "1 sentence verdict citing the headline GBP impact",\n'
    '  "summary":  "2 to 3 sentences in controller voice, cite specific GBP figures",\n'
    '  "actions":  ["short imperative", "short imperative"]\n'
    '}'
)


def run_scenario(
    *,
    base: AnalysisResult,
    user_prompt: str,
    model: str | None = None,
    api_key: str | None = None,
    skip_ai: bool = False,
) -> ScenarioResult:
    """Apply a scenario described in free text to the base forecast.

    On AI failure, returns a ScenarioResult with the base unchanged and
    a Commentary carrying the error. Useful for the UI to render a
    clear "AI unavailable" card without breaking the rest of the page.
    """
    if skip_ai:
        return ScenarioResult(
            base=base,
            scenario=base,
            shock=Shock(type="revenue_pct", magnitude=0.0),
            user_prompt=user_prompt,
            commentary=Commentary(skipped=True),
        )

    digest = _build_user_prompt(base=base, user_prompt=user_prompt)

    try:
        data, stats = ask_deepseek_json_with_stats(
            digest,
            system=SYSTEM_PROMPT
                  + "\n\nSupported shock types: " + _SHOCK_TYPES_HINT
                  + "\n\nSchema for your reply:\n" + _SCHEMA_HINT,
            max_tokens=500,
            model=(model or DEEPSEEK_MODEL_FAST),
            api_key=api_key,
        )
    except Exception as e:
        commentary = Commentary(
            headline=f"[AI scenario unavailable: {_scrub(e)}]",
            error=_scrub(e),
            model=model or DEEPSEEK_MODEL_FAST,
        )
        return ScenarioResult(
            base=base,
            scenario=base,
            shock=Shock(type="revenue_pct", magnitude=0.0),
            user_prompt=user_prompt,
            commentary=commentary,
        )

    try:
        shock = shock_from_dict(data.get("shock") or {})
    except ValueError as e:
        commentary = Commentary(
            headline=f"[Could not parse the scenario: {e}]",
            interpretation=str(data.get("interpretation") or ""),
            error=str(e),
            cost_usd=stats.cost_usd,
            input_tokens=stats.input_tokens,
            output_tokens=stats.output_tokens,
            cache_hit_tokens=stats.cache_hit_tokens,
            model=stats.model,
        )
        return ScenarioResult(
            base=base,
            scenario=base,
            shock=Shock(type="revenue_pct", magnitude=0.0),
            user_prompt=user_prompt,
            commentary=commentary,
        )

    shocked_lines = apply_shock(base.lines, shock)
    shocked_weeks = compute_weeks(shocked_lines, base.metadata)
    buffer = resolve_buffer(shocked_lines, base.metadata)
    shocked_headline = headline_stats(shocked_weeks, base.metadata, buffer=buffer)
    scenario_result = AnalysisResult(
        metadata=base.metadata,
        lines=shocked_lines,
        weeks=shocked_weeks,
        headline=shocked_headline,
        type_totals=aggregate_by_type(shocked_lines),
        category_totals=aggregate_by_category(shocked_lines),
        warnings=list(base.warnings),
        source_filename=base.source_filename,
        elapsed_ms=0,
    )

    commentary = Commentary(
        headline=str(data.get("headline") or "")[:280],
        summary=str(data.get("summary") or ""),
        interpretation=str(data.get("interpretation") or ""),
        actions=[str(x) for x in (data.get("actions") or [])][:5],
        cost_usd=stats.cost_usd,
        input_tokens=stats.input_tokens,
        output_tokens=stats.output_tokens,
        cache_hit_tokens=stats.cache_hit_tokens,
        model=stats.model,
    )

    return ScenarioResult(
        base=base,
        scenario=scenario_result,
        shock=shock,
        user_prompt=user_prompt,
        commentary=commentary,
    )


# ---- Prompt builders -------------------------------------------------

def _build_user_prompt(*, base: AnalysisResult, user_prompt: str) -> str:
    h = base.headline
    lines: list[str] = []
    lines.append(
        f"Company: {base.metadata.company}  |  "
        f"Period: {base.metadata.period_label}  |  "
        f"Currency: {base.metadata.currency}"
    )
    lines.append(
        f"Opening balance: {_g(base.metadata.opening_balance)}  |  "
        f"Buffer: {_g(h.buffer_used)}"
    )
    lines.append("")
    lines.append("User scenario question:")
    lines.append(user_prompt.strip())
    lines.append("")

    lines.append("Headline (base run):")
    lines.append("opening|closing|min|min_w|max|max_w|weeks_below_zero|runway_w|total_in|total_out|cum_net")
    lines.append("|".join([
        _g(h.opening_balance), _g(h.closing_balance),
        _g(h.min_balance), str(h.min_balance_week),
        _g(h.max_balance), str(h.max_balance_week),
        str(h.weeks_below_zero),
        ("none" if h.runway_weeks is None else str(h.runway_weeks)),
        _g(h.total_inflow), _g(h.total_outflow),
        _g(h.cumulative_net),
    ]))
    lines.append("")

    lines.append("Type totals (across 13 weeks):")
    lines.append("type|total_gbp")
    for t, v in base.type_totals.items():
        lines.append(f"{t}|{_g(v)}")
    lines.append("")

    lines.append("Closing balance per week:")
    lines.append("week|closing")
    for w in base.weeks:
        lines.append(f"{w.week}|{_g(w.closing)}")
    lines.append("")

    return "\n".join(lines)


def _g(v: float) -> str:
    return f"{v:.2f}"


# ---- Result serialisation -------------------------------------------

def to_dict(result: AnalysisResult) -> dict[str, Any]:
    return {
        "metadata": {
            "company": result.metadata.company,
            "currency": result.metadata.currency,
            "opening_balance": result.metadata.opening_balance,
            "start_date": result.metadata.start_date.isoformat(),
            "period_label": result.metadata.period_label,
            "buffer_amount": result.metadata.buffer_amount,
        },
        "lines": [_line_to_dict(l) for l in result.lines],
        "weeks": [_week_to_dict(w) for w in result.weeks],
        "headline": _headline_to_dict(result.headline),
        "type_totals": dict(result.type_totals),
        "category_totals": dict(result.category_totals),
        "warnings": list(result.warnings),
        "source_filename": result.source_filename,
        "elapsed_ms": result.elapsed_ms,
        "commentary": (_commentary_to_dict(result.commentary) if result.commentary else None),
    }


def scenario_to_dict(result: ScenarioResult) -> dict[str, Any]:
    return {
        "base": to_dict(result.base),
        "scenario": to_dict(result.scenario),
        "shock": shock_to_dict(result.shock),
        "user_prompt": result.user_prompt,
        "commentary": _commentary_to_dict(result.commentary),
    }


def _line_to_dict(l: CashflowLine) -> dict[str, Any]:
    return {
        "name": l.name,
        "type": l.type,
        "category": l.category,
        "amounts": list(l.amounts),
        "total": l.total(),
        "source": l.source,
    }


def _week_to_dict(w: WeekRow) -> dict[str, Any]:
    return {
        "week": w.week,
        "iso_week_label": w.iso_week_label,
        "receipts": w.receipts,
        "payments": w.payments,
        "payroll": w.payroll,
        "tax": w.tax,
        "inflow": w.inflow,
        "outflow": w.outflow,
        "net": w.net,
        "opening": w.opening,
        "closing": w.closing,
        "rag": w.rag,
        "concentration_pct": w.concentration_pct,
    }


def _headline_to_dict(h: HeadlineStats) -> dict[str, Any]:
    return {
        "opening_balance": h.opening_balance,
        "closing_balance": h.closing_balance,
        "min_balance": h.min_balance,
        "max_balance": h.max_balance,
        "min_balance_week": h.min_balance_week,
        "max_balance_week": h.max_balance_week,
        "weeks_below_zero": h.weeks_below_zero,
        "weeks_below_buffer": h.weeks_below_buffer,
        "runway_weeks": h.runway_weeks,
        "total_inflow": h.total_inflow,
        "total_outflow": h.total_outflow,
        "cumulative_net": h.cumulative_net,
        "buffer_used": h.buffer_used,
        "rag_counts": dict(h.rag_counts),
        "concentration_flag_count": h.concentration_flag_count,
    }


def _commentary_to_dict(c: Commentary) -> dict[str, Any]:
    return {
        "headline": c.headline,
        "summary": c.summary,
        "interpretation": c.interpretation,
        "actions": list(c.actions),
        "cost_usd": round(c.cost_usd, 6),
        "input_tokens": c.input_tokens,
        "output_tokens": c.output_tokens,
        "cache_hit_tokens": c.cache_hit_tokens,
        "model": c.model,
        "skipped": c.skipped,
        "error": c.error,
    }


# ---- Helpers --------------------------------------------------------

def _scrub(e: Exception) -> str:
    msg = f"{type(e).__name__}: {e}"
    msg = re.sub(r"/[^\s'\"]+|[A-Z]:\\[^\s'\"]+", "<path>", msg)
    msg = re.sub(r"sk-[A-Za-z0-9_\-]+", "sk-***", msg)
    return msg[:300]
