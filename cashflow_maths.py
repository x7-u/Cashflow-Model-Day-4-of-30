"""Day 4. Pure cash flow maths.

Inputs: a list of CashflowLine plus a CashflowMetadata. Outputs:
- list[WeekRow] (per-week receipts, payments, payroll, tax, net,
  opening, closing, RAG, concentration flag).
- HeadlineStats (totals, min/max, runway, weeks below zero, RAG counts).

No IO. No Anthropic / DeepSeek calls. Every branch hit by tests.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Literal

from cashflow_schema import (
    WEEK_COUNT,
    CashflowLine,
    CashflowMetadata,
    week_iso_label,
)

CONCENTRATION_THRESHOLD = 0.25  # 25% of gross flow in a single line trips the flag
DEFAULT_BUFFER_PAYROLL_MONTHS = 1.0
DEFAULT_BUFFER_OUTFLOW_WEEKS = 4


@dataclass
class WeekRow:
    week: int                       # 1..13
    iso_week_label: str
    receipts: float
    payments: float
    payroll: float
    tax: float
    inflow: float                   # = receipts
    outflow: float                  # = payments + payroll + tax
    net: float                      # = inflow - outflow
    opening: float
    closing: float
    rag: Literal["green", "amber", "red"]
    concentration_pct: float | None  # max single-line / gross flow this week


@dataclass
class HeadlineStats:
    opening_balance: float
    closing_balance: float
    min_balance: float
    max_balance: float
    min_balance_week: int
    max_balance_week: int
    weeks_below_zero: int
    weeks_below_buffer: int
    runway_weeks: int | None        # first week closing < 0; None if never
    total_inflow: float
    total_outflow: float
    cumulative_net: float           # closing[13] - opening
    buffer_used: float              # the resolved buffer value
    rag_counts: dict[str, int] = field(default_factory=dict)
    concentration_flag_count: int = 0


# ---- Public API ------------------------------------------------------

def compute_weeks(
    lines: list[CashflowLine],
    metadata: CashflowMetadata,
) -> list[WeekRow]:
    """Roll forward 13 weeks of opening / net / closing using the supplied lines."""
    weeks: list[WeekRow] = []
    running_open = metadata.opening_balance
    buffer = resolve_buffer(lines, metadata)

    for w in range(1, WEEK_COUNT + 1):
        receipts = sum(l.amounts[w - 1] for l in lines if l.type == "receipt")
        payments = sum(l.amounts[w - 1] for l in lines if l.type == "payment")
        payroll = sum(l.amounts[w - 1] for l in lines if l.type == "payroll")
        tax = sum(l.amounts[w - 1] for l in lines if l.type == "tax")
        inflow = receipts
        outflow = payments + payroll + tax
        net = inflow - outflow
        closing = running_open + net

        rag = _classify_rag(closing, buffer)
        concentration = _concentration_for_week(lines, w)

        weeks.append(WeekRow(
            week=w,
            iso_week_label=week_iso_label(metadata.start_date, w),
            receipts=receipts,
            payments=payments,
            payroll=payroll,
            tax=tax,
            inflow=inflow,
            outflow=outflow,
            net=net,
            opening=running_open,
            closing=closing,
            rag=rag,
            concentration_pct=concentration,
        ))
        running_open = closing

    return weeks


def headline_stats(
    weeks: list[WeekRow],
    metadata: CashflowMetadata,
    *,
    buffer: float,
) -> HeadlineStats:
    """Aggregate per-week numbers into the controller-facing summary."""
    if not weeks:
        return HeadlineStats(
            opening_balance=metadata.opening_balance,
            closing_balance=metadata.opening_balance,
            min_balance=metadata.opening_balance,
            max_balance=metadata.opening_balance,
            min_balance_week=0, max_balance_week=0,
            weeks_below_zero=0, weeks_below_buffer=0, runway_weeks=None,
            total_inflow=0.0, total_outflow=0.0, cumulative_net=0.0,
            buffer_used=buffer,
        )

    closings = [w.closing for w in weeks]
    min_balance = min(closings)
    max_balance = max(closings)
    min_balance_week = closings.index(min_balance) + 1
    max_balance_week = closings.index(max_balance) + 1

    weeks_below_zero = sum(1 for c in closings if c < 0)
    weeks_below_buffer = sum(1 for c in closings if 0 <= c < buffer)

    runway: int | None = None
    for i, c in enumerate(closings, start=1):
        if c < 0:
            runway = i
            break

    rag_counts: dict[str, int] = {"green": 0, "amber": 0, "red": 0}
    for w in weeks:
        rag_counts[w.rag] = rag_counts.get(w.rag, 0) + 1

    concentration_flag_count = sum(
        1 for w in weeks
        if w.concentration_pct is not None and w.concentration_pct >= CONCENTRATION_THRESHOLD
    )

    return HeadlineStats(
        opening_balance=metadata.opening_balance,
        closing_balance=closings[-1],
        min_balance=min_balance,
        max_balance=max_balance,
        min_balance_week=min_balance_week,
        max_balance_week=max_balance_week,
        weeks_below_zero=weeks_below_zero,
        weeks_below_buffer=weeks_below_buffer,
        runway_weeks=runway,
        total_inflow=sum(w.inflow for w in weeks),
        total_outflow=sum(w.outflow for w in weeks),
        cumulative_net=closings[-1] - metadata.opening_balance,
        buffer_used=buffer,
        rag_counts=rag_counts,
        concentration_flag_count=concentration_flag_count,
    )


def resolve_buffer(
    lines: Iterable[CashflowLine],
    metadata: CashflowMetadata,
) -> float:
    """Resolve the liquidity buffer for the RAG bands.

    Order of precedence:
    1. metadata.buffer_amount if provided.
    2. Larger of (1 month payroll) or (4 weeks of average non-payroll outflows).
    3. Zero if no signal at all.
    """
    if metadata.buffer_amount is not None and metadata.buffer_amount >= 0:
        return float(metadata.buffer_amount)

    lines = list(lines)
    payroll_total = sum(
        l.total() for l in lines if l.type == "payroll"
    )
    # 1 month of payroll, assuming the 13-week horizon covers ~3 months.
    monthly_payroll = (payroll_total / 3.0) if payroll_total else 0.0

    other_outflow_total = sum(
        l.total() for l in lines if l.type in ("payment", "tax")
    )
    weekly_other_outflow = other_outflow_total / WEEK_COUNT if other_outflow_total else 0.0
    four_weeks_other = 4 * weekly_other_outflow

    return max(monthly_payroll, four_weeks_other, 0.0)


# ---- Internal helpers -----------------------------------------------

def _classify_rag(closing: float, buffer: float) -> Literal["green", "amber", "red"]:
    if closing < 0:
        return "red"
    if closing < buffer:
        return "amber"
    return "green"


def _concentration_for_week(lines: list[CashflowLine], w: int) -> float | None:
    """Largest absolute line amount divided by gross flow for the given week.

    Returns None when there is no flow at all (avoids 0/0).
    """
    amounts = [abs(l.amounts[w - 1]) for l in lines]
    gross = sum(amounts)
    if gross <= 0:
        return None
    largest = max(amounts) if amounts else 0.0
    return largest / gross


# ---- Re-exports for the pipeline + writers --------------------------

def aggregate_by_type(lines: list[CashflowLine]) -> dict[str, float]:
    """Total per type across all 13 weeks. Used in the AI digest."""
    out: dict[str, float] = {"receipt": 0.0, "payment": 0.0, "payroll": 0.0, "tax": 0.0}
    for l in lines:
        out[l.type] = out.get(l.type, 0.0) + l.total()
    return out


def aggregate_by_category(lines: list[CashflowLine]) -> dict[str, float]:
    """Total per category across all 13 weeks. Empty category groups under 'uncategorised'."""
    out: dict[str, float] = {}
    for l in lines:
        key = l.category or "uncategorised"
        out[key] = out.get(key, 0.0) + l.total()
    return out
