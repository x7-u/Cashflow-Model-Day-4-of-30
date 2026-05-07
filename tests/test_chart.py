"""Day 4. Chart smoke tests.

Just enough to catch matplotlib backend / rendering regressions. We
verify that PNG bytes come back non-empty with the right magic header
and that the SVG helper produces something parseable.
"""
from __future__ import annotations

import datetime as dt

from cashflow_maths import compute_weeks
from cashflow_schema import CashflowLine, CashflowMetadata
from chart import render_balance_line_png, render_inline_svg, render_waterfall_png


def _md(opening: float = 10_000) -> CashflowMetadata:
    return CashflowMetadata(
        company="X", currency="GBP", opening_balance=opening,
        start_date=dt.date(2026, 4, 6), period_label="Q2 26",
    )


def _weeks():
    md = _md(opening=10_000)
    line = CashflowLine(
        name="AR", type="receipt", category="AR",
        amounts=[1_000] * 13,
    )
    payroll = CashflowLine(
        name="P", type="payroll", category="payroll",
        amounts=[800] * 13,
    )
    return compute_weeks([line, payroll], md)


def test_waterfall_returns_png_bytes() -> None:
    weeks = _weeks()
    data = render_waterfall_png(weeks, title="Waterfall test")
    assert isinstance(data, bytes)
    assert len(data) > 1_000  # a valid 10-week waterfall is at least 1 KB
    assert data.startswith(b"\x89PNG\r\n\x1a\n"), "must start with PNG magic header"


def test_balance_line_returns_png_bytes() -> None:
    weeks = _weeks()
    data = render_balance_line_png(
        weeks, title="Closing balance test",
        buffer=2_000.0, runway_week=None,
    )
    assert isinstance(data, bytes)
    assert data.startswith(b"\x89PNG\r\n\x1a\n")


def test_inline_svg_is_well_formed() -> None:
    closing = [10_000, 9_500, 9_200, 8_700, 8_500, 8_200, 8_000, 7_500, 7_900, 8_400, 8_900, 9_500, 10_200]
    svg = render_inline_svg(closing)
    assert svg.startswith("<svg ")
    assert svg.endswith("</svg>")
    assert "M " in svg
    assert "<circle" in svg


def test_inline_svg_handles_empty_input() -> None:
    svg = render_inline_svg([])
    assert "<svg" in svg
