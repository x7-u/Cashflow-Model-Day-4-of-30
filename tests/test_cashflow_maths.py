"""Day 4. Cashflow maths tests.

Covers per-week net, running balance, runway, never-breach case, RAG
bands, concentration flag, headline aggregates and the buffer resolver.
"""
from __future__ import annotations

import datetime as dt

from cashflow_maths import (
    CONCENTRATION_THRESHOLD,
    aggregate_by_type,
    compute_weeks,
    headline_stats,
    resolve_buffer,
)
from cashflow_schema import WEEK_COUNT, CashflowLine, CashflowMetadata


def _md(opening: float = 10_000, buffer: float | None = None) -> CashflowMetadata:
    return CashflowMetadata(
        company="X", currency="GBP", opening_balance=opening,
        start_date=dt.date(2026, 4, 6), period_label="Q2 26",
        buffer_amount=buffer,
    )


def _line(name: str, line_type: str, amounts: list[float],
          category: str = "") -> CashflowLine:
    return CashflowLine(name=name, type=line_type, category=category,
                        amounts=amounts)


def test_running_balance_rolls_forward() -> None:
    md = _md(opening=10_000)
    receipts = _line("AR", "receipt", [2_000] * WEEK_COUNT)
    payments = _line("Rent", "payment", [1_500] * WEEK_COUNT)
    weeks = compute_weeks([receipts, payments], md)
    # Each week net = +500; closing[i] = 10_000 + 500 * i
    assert weeks[0].opening == 10_000
    assert weeks[0].closing == 10_500
    assert weeks[1].opening == 10_500
    assert weeks[12].closing == 10_000 + 500 * WEEK_COUNT


def test_runway_zero_crossing() -> None:
    md = _md(opening=2_000, buffer=0)
    payments = _line("Rent", "payment", [1_500] * WEEK_COUNT)
    weeks = compute_weeks([payments], md)
    h = headline_stats(weeks, md, buffer=0)
    # Opening 2000, weekly net -1500. W1 closing 500 (>=0), W2 -1000 (<0).
    assert h.runway_weeks == 2
    assert h.weeks_below_zero == WEEK_COUNT - 1


def test_never_breach_returns_none() -> None:
    md = _md(opening=100_000)
    receipts = _line("AR", "receipt", [10_000] * WEEK_COUNT)
    weeks = compute_weeks([receipts], md)
    h = headline_stats(weeks, md, buffer=0)
    assert h.runway_weeks is None


def test_rag_bands() -> None:
    md = _md(opening=10_000, buffer=5_000)
    # Pull balance below buffer in W1 (-> amber) and below zero in W3 (-> red).
    payroll = _line("Pay", "payroll", [6_000, 0, 5_500] + [0] * 10)
    weeks = compute_weeks([payroll], md)
    # W1: opening 10k, payroll 6k -> closing 4k -> below buffer 5k -> amber
    # W2: closing 4k -> below buffer -> amber
    # W3: closing 4k - 5.5k = -1.5k -> red
    assert weeks[0].rag == "amber"
    assert weeks[2].rag == "red"


def test_concentration_flag_trips() -> None:
    md = _md(opening=10_000)
    big = _line("BigCo", "receipt", [100_000] + [0] * 12)
    small = _line("SmallCo", "receipt", [1_000] + [0] * 12)
    weeks = compute_weeks([big, small], md)
    # BigCo dominates W1 gross flow, concentration ~100/101 well above 25%.
    assert weeks[0].concentration_pct is not None
    assert weeks[0].concentration_pct > CONCENTRATION_THRESHOLD


def test_headline_totals() -> None:
    md = _md(opening=0)
    receipts = _line("AR", "receipt", [1_000] * WEEK_COUNT)
    payroll = _line("Pay", "payroll", [500] * WEEK_COUNT)
    weeks = compute_weeks([receipts, payroll], md)
    h = headline_stats(weeks, md, buffer=resolve_buffer([receipts, payroll], md))
    assert h.total_inflow == 1_000 * WEEK_COUNT
    assert h.total_outflow == 500 * WEEK_COUNT
    assert h.cumulative_net == 500 * WEEK_COUNT


def test_buffer_resolver_uses_metadata_first() -> None:
    md = _md(opening=10_000, buffer=999.0)
    payroll = _line("P", "payroll", [10_000] * WEEK_COUNT)
    assert resolve_buffer([payroll], md) == 999.0


def test_buffer_resolver_fallback_uses_payroll() -> None:
    md = _md(opening=10_000, buffer=None)
    # Total payroll £30k over 13 weeks. Monthly = 30k / 3 = £10k.
    payroll = _line("P", "payroll", [10_000, 0, 0] * 4 + [0])  # 4 chunks of 10k = 40k
    payments = _line("R", "payment", [100] * WEEK_COUNT)  # tiny, monthly_payroll wins
    buf = resolve_buffer([payroll, payments], md)
    assert buf > 10_000  # at least monthly payroll


def test_aggregate_by_type_sums_correctly() -> None:
    receipts = _line("A", "receipt", [100] * WEEK_COUNT)
    payments = _line("B", "payment", [50] * WEEK_COUNT)
    out = aggregate_by_type([receipts, payments])
    assert out["receipt"] == 100 * WEEK_COUNT
    assert out["payment"] == 50 * WEEK_COUNT
    assert out["payroll"] == 0
    assert out["tax"] == 0
