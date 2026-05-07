"""Day 4. Scenario engine tests.

Each shock type gets a focused test. Filters (weeks, category) are
exercised on top.
"""
from __future__ import annotations

from cashflow_schema import WEEK_COUNT, CashflowLine
from scenario import Shock, apply_shock, shock_from_dict, shock_to_dict


def _line(name: str, line_type: str, amount: float, category: str = "") -> CashflowLine:
    return CashflowLine(
        name=name, type=line_type, category=category,
        amounts=[amount] * WEEK_COUNT,
    )


def test_revenue_pct_shock_reduces_receipts() -> None:
    base = [_line("AR", "receipt", 1_000)]
    out = apply_shock(base, Shock(type="revenue_pct", magnitude=-0.20, weeks=[1, 2, 3]))
    line = out[0]
    assert line.amounts[0] == 800.0
    assert line.amounts[1] == 800.0
    assert line.amounts[2] == 800.0
    assert line.amounts[3] == 1_000.0  # outside weeks filter
    assert line.source == "scenario"


def test_cost_pct_shock_targets_payments_only() -> None:
    base = [_line("Rent", "payment", 500), _line("AR", "receipt", 1_000)]
    out = apply_shock(base, Shock(type="cost_pct", magnitude=0.10))
    rent = next(l for l in out if l.name == "Rent")
    ar = next(l for l in out if l.name == "AR")
    assert rent.amounts[0] == 550.0
    assert ar.amounts[0] == 1_000.0  # untouched


def test_payment_delay_days_shifts_into_future() -> None:
    line = CashflowLine(
        name="Supplier", type="payment", category="rent",
        amounts=[100, 0, 0] + [0] * (WEEK_COUNT - 3),
    )
    out = apply_shock([line], Shock(type="payment_delay_days", magnitude=14))
    # 14 days = 2 weeks shift. The W1 100 should land in W3.
    assert out[0].amounts[0] == 0.0
    assert out[0].amounts[2] == 100.0


def test_payment_delay_drops_amount_off_horizon() -> None:
    line = CashflowLine(
        name="LatePayer", type="payment", category="rent",
        amounts=[0] * (WEEK_COUNT - 1) + [200],
    )
    out = apply_shock([line], Shock(type="payment_delay_days", magnitude=14))
    # W13 amount shifted by 2 weeks ends up off-horizon (dropped)
    if out:  # the line may be dropped entirely
        assert sum(out[0].amounts) == 0.0


def test_payroll_delta_adds_per_week() -> None:
    base = [_line("Payroll", "payroll", 10_000)]
    out = apply_shock(base, Shock(type="payroll_delta", magnitude=2_000, weeks=[5, 6]))
    line = out[0]
    assert line.amounts[4] == 12_000.0
    assert line.amounts[5] == 12_000.0
    assert line.amounts[6] == 10_000.0  # outside weeks filter


def test_oneoff_amount_appends_new_line() -> None:
    base = [_line("AR", "receipt", 1_000)]
    out = apply_shock(base, Shock(
        type="oneoff_amount", magnitude=30_000.0,
        one_off_week=8, one_off_kind="receipt",
    ))
    assert len(out) == 2
    one_off = [l for l in out if "Scenario one-off" in l.name][0]
    assert one_off.amounts[7] == 30_000.0  # W8 = index 7
    assert sum(one_off.amounts) == 30_000.0


def test_tax_defer_weeks_pushes_tax_payments_forward() -> None:
    line = CashflowLine(
        name="VAT", type="tax", category="VAT",
        amounts=[0, 0, 0, 8_000] + [0] * 9,  # VAT in W4
    )
    out = apply_shock([line], Shock(type="tax_defer_weeks", magnitude=4))
    # Original W4 amount should now be in W8.
    assert out[0].amounts[3] == 0.0
    assert out[0].amounts[7] == 8_000.0


def test_category_filter_targets_only_matching_lines() -> None:
    base = [
        _line("Rent",         "payment", 500, category="rent"),
        _line("Contractors",  "payment", 800, category="contractors"),
    ]
    out = apply_shock(base, Shock(
        type="cost_pct", magnitude=-0.10,
        category_filter=["rent"],
    ))
    rent = next(l for l in out if l.name == "Rent")
    contractors = next(l for l in out if l.name == "Contractors")
    assert rent.amounts[0] == 450.0
    assert contractors.amounts[0] == 800.0  # untouched


def test_shock_from_dict_validates_type() -> None:
    import pytest
    with pytest.raises(ValueError, match="Unsupported shock type"):
        shock_from_dict({"type": "rocket_fuel"})


def test_shock_round_trip_through_dict() -> None:
    s = Shock(type="revenue_pct", magnitude=-0.15, weeks=[2, 3, 4])
    d = shock_to_dict(s)
    s2 = shock_from_dict(d)
    assert s2.type == s.type
    assert s2.magnitude == s.magnitude
    assert s2.weeks == s.weeks
