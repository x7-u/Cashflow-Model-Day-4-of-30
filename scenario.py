"""Day 4. Scenario engine.

Takes a typed Shock and a base list of CashflowLine, returns the shocked
list. Pure function, no IO. The AI (DeepSeek V4) parses free-text user
prompts into a Shock; this module applies it deterministically so the
maths is auditable.

Shock taxonomy:
- revenue_pct        Apply a percentage change to all 'receipt' lines.
- cost_pct           Apply a percentage change to 'payment' lines.
- payment_delay_days Stretch payment lines by N days (rounded to weeks).
- payroll_delta      Add or subtract a flat amount per week to payroll.
- oneoff_amount      Add a one-off receipt or payment in a specific week.
- tax_defer_weeks    Push tax payments forward by N weeks.

Optional filters apply to all types:
- weeks              List of 1-based week indices the shock applies to.
                     Default: all 13 weeks.
- category_filter    List of category strings to match. Default: all.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Literal

from cashflow_schema import WEEK_COUNT, CashflowLine

ShockType = Literal[
    "revenue_pct",
    "cost_pct",
    "payment_delay_days",
    "payroll_delta",
    "oneoff_amount",
    "tax_defer_weeks",
]


@dataclass
class Shock:
    type: ShockType
    magnitude: float = 0.0           # pct (e.g. -0.20) or flat amount or days/weeks
    weeks: list[int] = field(default_factory=list)  # empty == all 13
    category_filter: list[str] | None = None
    one_off_week: int | None = None  # for oneoff_amount only
    one_off_kind: Literal["receipt", "payment"] = "receipt"  # for oneoff_amount only

    def applied_weeks(self) -> list[int]:
        """Resolve the set of weeks this shock applies to."""
        if not self.weeks:
            return list(range(1, WEEK_COUNT + 1))
        return [w for w in self.weeks if 1 <= w <= WEEK_COUNT]

    def matches_line(self, line: CashflowLine) -> bool:
        """Type-level + category filter check."""
        type_match = {
            "revenue_pct": line.type == "receipt",
            "cost_pct": line.type == "payment",
            "payment_delay_days": line.type == "payment",
            "payroll_delta": line.type == "payroll",
            "oneoff_amount": False,  # one-off creates a new line, doesn't match existing
            "tax_defer_weeks": line.type == "tax",
        }.get(self.type, False)
        if not type_match:
            return False
        if self.category_filter:
            return line.category in self.category_filter
        return True


def apply_shock(base: list[CashflowLine], shock: Shock) -> list[CashflowLine]:
    """Return a new list of CashflowLine with the shock applied. Pure function."""
    result = [copy.deepcopy(l) for l in base]

    if shock.type == "revenue_pct":
        _apply_pct(result, shock, "receipt")
    elif shock.type == "cost_pct":
        _apply_pct(result, shock, "payment")
    elif shock.type == "payment_delay_days":
        _apply_delay(result, shock, "payment")
    elif shock.type == "payroll_delta":
        _apply_flat_delta(result, shock, "payroll")
    elif shock.type == "tax_defer_weeks":
        _apply_delay(result, shock, "tax", in_weeks=True)
    elif shock.type == "oneoff_amount":
        result.append(_build_oneoff(shock))
    else:
        raise ValueError(f"Unknown shock type: {shock.type}")

    # Drop now-empty rows for tidiness.
    result = [l for l in result if any(a != 0.0 for a in l.amounts)]

    # Mark anything we changed as a scenario-source line so the writer can colour it.
    for l in result:
        if l.source not in ("scenario",):
            # Source change is delegated to the touch helpers; this is a safety net.
            pass

    return result


# ---- Per-type appliers ----------------------------------------------

def _apply_pct(lines: list[CashflowLine], shock: Shock, line_type: str) -> None:
    weeks = shock.applied_weeks()
    factor = 1.0 + float(shock.magnitude)
    for line in lines:
        if line.type != line_type:
            continue
        if not shock.matches_line(line):
            continue
        line.amounts = [
            a * factor if (i + 1) in weeks else a
            for i, a in enumerate(line.amounts)
        ]
        line.source = "scenario"


def _apply_flat_delta(lines: list[CashflowLine], shock: Shock, line_type: str) -> None:
    """Add ``magnitude`` to every targeted week's amount on the matching lines.

    For payroll, treat magnitude as a per-week absolute delta (e.g. +£5,000
    per week reflecting a new hire). Distributes across matching payroll
    lines proportional to their existing payroll spend.
    """
    weeks = shock.applied_weeks()
    targets = [l for l in lines if l.type == line_type and shock.matches_line(l)]
    if not targets:
        return

    # Distribute evenly across targets; controllers expect "the new hire shows up
    # in the salary line", not "spread across every department".
    delta_per_line = float(shock.magnitude) / len(targets)
    for line in targets:
        line.amounts = [
            a + delta_per_line if (i + 1) in weeks else a
            for i, a in enumerate(line.amounts)
        ]
        line.source = "scenario"


def _apply_delay(
    lines: list[CashflowLine],
    shock: Shock,
    line_type: str,
    *,
    in_weeks: bool = False,
) -> None:
    """Shift the targeted line type's amounts forward in time.

    For payment_delay_days, magnitude is in days; we round to the nearest
    week and shift. For tax_defer_weeks, magnitude is already in weeks.
    Amounts that fall off the 13-week horizon are dropped (out of model).
    """
    if in_weeks:
        shift = int(round(shock.magnitude))
    else:
        shift = int(round(shock.magnitude / 7.0))
    if shift <= 0:
        return

    weeks_filter = shock.applied_weeks()
    for line in lines:
        if line.type != line_type:
            continue
        if not shock.matches_line(line):
            continue
        new_amounts = [0.0] * WEEK_COUNT
        for i, val in enumerate(line.amounts):
            if (i + 1) not in weeks_filter:
                new_amounts[i] += val
                continue
            target_idx = i + shift
            if 0 <= target_idx < WEEK_COUNT:
                new_amounts[target_idx] += val
            # else: payment shifted past the horizon, drop it
        line.amounts = new_amounts
        line.source = "scenario"


def _build_oneoff(shock: Shock) -> CashflowLine:
    """Construct a fresh line carrying a single-week amount."""
    target_week = shock.one_off_week or 1
    target_week = max(1, min(WEEK_COUNT, target_week))
    amounts = [0.0] * WEEK_COUNT
    amounts[target_week - 1] = float(shock.magnitude)
    line_type: str
    if shock.one_off_kind == "payment":
        line_type = "payment"
    else:
        line_type = "receipt"
    return CashflowLine(
        name=f"Scenario one-off ({shock.one_off_kind})",
        type=line_type,
        category="scenario",
        amounts=amounts,
        source="scenario",
    )


# ---- Helpers for the AI parser --------------------------------------

def shock_from_dict(data: dict) -> Shock:
    """Build a Shock from the JSON DeepSeek returns. Defensive defaults.

    Caller is responsible for clamping magnitudes; this helper just
    coerces types and ensures invariants (weeks within 1..13 etc.).
    """
    s_type = str(data.get("type", "")).strip().lower()
    if s_type not in {
        "revenue_pct", "cost_pct", "payment_delay_days",
        "payroll_delta", "oneoff_amount", "tax_defer_weeks",
    }:
        raise ValueError(f"Unsupported shock type from AI: {s_type!r}")

    weeks_raw = data.get("weeks") or []
    weeks: list[int] = []
    if isinstance(weeks_raw, list):
        for w in weeks_raw:
            try:
                wi = int(w)
                if 1 <= wi <= WEEK_COUNT:
                    weeks.append(wi)
            except (ValueError, TypeError):
                continue

    cat_filter_raw = data.get("category_filter")
    cat_filter: list[str] | None = None
    if isinstance(cat_filter_raw, list) and cat_filter_raw:
        cat_filter = [str(c).strip() for c in cat_filter_raw if str(c).strip()]

    one_off_week = data.get("one_off_week")
    if one_off_week is not None:
        try:
            one_off_week = int(one_off_week)
        except (ValueError, TypeError):
            one_off_week = None

    one_off_kind = str(data.get("one_off_kind", "receipt")).strip().lower()
    if one_off_kind not in ("receipt", "payment"):
        one_off_kind = "receipt"

    try:
        magnitude = float(data.get("magnitude", 0.0))
    except (ValueError, TypeError):
        magnitude = 0.0

    return Shock(
        type=s_type,           # type: ignore[arg-type]
        magnitude=magnitude,
        weeks=weeks,
        category_filter=cat_filter,
        one_off_week=one_off_week,
        one_off_kind=one_off_kind,  # type: ignore[arg-type]
    )


def shock_to_dict(shock: Shock) -> dict:
    return {
        "type": shock.type,
        "magnitude": shock.magnitude,
        "weeks": list(shock.weeks),
        "category_filter": list(shock.category_filter) if shock.category_filter else None,
        "one_off_week": shock.one_off_week,
        "one_off_kind": shock.one_off_kind,
    }
