"""Day 4. Input parsing for the cash flow forecasting model.

Canonical shape: wide-by-week. A `metadata` sheet plus a `forecast` sheet
where each row is one cashflow line and columns W1..W13 carry the weekly
amounts. An optional `actuals` sheet with the same shape overlays the
forecast (any populated cell wins). A long-format `data` sheet is also
accepted via a server-side adapter that pivots to wide before maths run.

Reject ambiguity (both `forecast` and `data` present) and non-GBP
metadata. Period labels are opaque strings; week numbering is
Monday-aligned to `metadata.start_date` and uses W1..W13 internally.
"""
from __future__ import annotations

import datetime as dt
import io
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import pandas as pd

WEEK_COUNT = 13
WEEK_COLS: list[str] = [f"W{i}" for i in range(1, WEEK_COUNT + 1)]
LINE_TYPES: tuple[str, ...] = ("receipt", "payment", "payroll", "tax")


@dataclass
class CashflowMetadata:
    company: str
    currency: str
    opening_balance: float
    start_date: dt.date
    period_label: str
    buffer_amount: float | None = None  # resolved later when None


@dataclass
class CashflowLine:
    name: str
    type: Literal["receipt", "payment", "payroll", "tax"]
    category: str
    amounts: list[float]  # length = WEEK_COUNT
    source: str = "forecast"  # "forecast", "actual", or "scenario"

    def total(self) -> float:
        return float(sum(self.amounts))


@dataclass
class ParsedInputs:
    metadata: CashflowMetadata
    lines: list[CashflowLine]
    warnings: list[str] = field(default_factory=list)

    def line_count(self) -> int:
        return len(self.lines)


# ---- Public entry point ---------------------------------------------

def parse_inputs(
    *,
    file_bytes: bytes | None = None,
    path: Path | str | None = None,
    source_filename: str = "",
) -> ParsedInputs:
    """Read a workbook and return ParsedInputs. Raises ValueError on shape errors."""
    if file_bytes is not None:
        buf: io.BytesIO | Path = io.BytesIO(file_bytes)
    elif path is not None:
        buf = Path(path)
    else:
        raise ValueError("parse_inputs() needs either file_bytes or path.")

    try:
        xl = pd.ExcelFile(buf, engine="openpyxl")
    except Exception as e:
        raise ValueError(f"Could not open workbook: {e}") from e

    sheets = {name.strip().lower(): name for name in xl.sheet_names}

    if "metadata" not in sheets:
        raise ValueError(
            "Workbook missing required 'metadata' sheet. "
            "Expected keys: company, currency, opening_balance, start_date, period_label."
        )

    has_forecast = "forecast" in sheets
    has_data = "data" in sheets
    has_actuals = "actuals" in sheets

    if has_forecast and has_data:
        raise ValueError(
            "Workbook contains both 'forecast' and 'data' sheets. "
            "Provide either the wide forecast layout or the long data layout, not both."
        )
    if not has_forecast and not has_data:
        raise ValueError(
            "Workbook has neither a 'forecast' nor a 'data' sheet. "
            "Provide the wide forecast layout (W1..W13 columns) or the long data layout."
        )

    metadata = _parse_metadata(xl, sheets["metadata"])
    warnings: list[str] = []

    if has_forecast:
        lines = _parse_wide(xl, sheets["forecast"], default_source="forecast", warnings=warnings)
    else:
        lines = _parse_long(xl, sheets["data"], warnings=warnings)

    if has_actuals:
        actual_lines = _parse_wide(
            xl, sheets["actuals"], default_source="actual", warnings=warnings,
        )
        lines = _overlay_actuals(lines, actual_lines, warnings=warnings)

    if not lines:
        raise ValueError("No cashflow lines found in the workbook. Add at least one line.")

    if len(lines) > 500:
        warnings.append(f"Capped at 500 lines; received {len(lines)}.")
        lines = lines[:500]

    return ParsedInputs(metadata=metadata, lines=lines, warnings=warnings)


# ---- Metadata --------------------------------------------------------

_REQUIRED_META_KEYS = {"company", "currency", "opening_balance", "start_date", "period_label"}


def _parse_metadata(xl: pd.ExcelFile, sheet_name: str) -> CashflowMetadata:
    df = xl.parse(sheet_name, header=None)
    if df.shape[1] < 2:
        raise ValueError("'metadata' sheet must have two columns: key | value.")

    pairs: dict[str, str] = {}
    for _, row in df.iterrows():
        key = str(row.iloc[0] or "").strip().lower()
        if not key or key in {"key", "metadata"}:
            continue
        val = row.iloc[1]
        pairs[key] = "" if pd.isna(val) else str(val).strip()

    missing = _REQUIRED_META_KEYS - pairs.keys()
    if missing:
        raise ValueError(
            f"'metadata' sheet missing keys: {sorted(missing)}. "
            f"Required: {sorted(_REQUIRED_META_KEYS)}."
        )

    currency = pairs["currency"].upper() or "GBP"
    if currency != "GBP":
        raise ValueError(
            f"Day 4 MVP supports GBP only. Found: {currency}. "
            "Multi-currency is on the post-30 list."
        )

    try:
        opening_balance = float(pairs["opening_balance"].replace(",", ""))
    except (ValueError, AttributeError) as e:
        raise ValueError(
            f"opening_balance must be a number. Got: {pairs['opening_balance']!r}"
        ) from e

    start_date = _coerce_date(pairs["start_date"])

    buf_amount: float | None = None
    if "buffer_amount" in pairs and pairs["buffer_amount"]:
        try:
            buf_amount = float(pairs["buffer_amount"].replace(",", ""))
        except (ValueError, AttributeError):
            buf_amount = None

    return CashflowMetadata(
        company=pairs["company"] or "Unnamed Company",
        currency=currency,
        opening_balance=opening_balance,
        start_date=start_date,
        period_label=pairs["period_label"] or "Q? 26",
        buffer_amount=buf_amount,
    )


def _coerce_date(value: str) -> dt.date:
    """Accept ISO YYYY-MM-DD or YYYY/MM/DD; else raise."""
    if isinstance(value, dt.date):
        return value
    s = str(value).strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return dt.datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    # Try pandas parsing as a fallback (handles "2026-04-06" style and many others).
    try:
        return pd.Timestamp(s).date()
    except (ValueError, TypeError) as e:
        raise ValueError(f"start_date not a recognised date: {s!r}") from e


# ---- Wide layout -----------------------------------------------------

def _parse_wide(
    xl: pd.ExcelFile,
    sheet_name: str,
    *,
    default_source: str,
    warnings: list[str],
) -> list[CashflowLine]:
    df = xl.parse(sheet_name)
    df.columns = [str(c).strip() for c in df.columns]
    df = _coerce_columns_lowercase(df, keep_week_cols=True)

    required = {"name", "type"}
    missing_cols = required - set(df.columns)
    if missing_cols:
        raise ValueError(
            f"'{sheet_name}' sheet missing required columns: {sorted(missing_cols)}. "
            f"Need: name | type | category | W1..W13."
        )

    week_cols_present = [c for c in df.columns if c.upper() in WEEK_COLS]
    if not week_cols_present:
        raise ValueError(
            f"'{sheet_name}' sheet has no W1..W13 columns. "
            "The wide layout needs at least W1..W13 amount columns."
        )

    if "category" not in df.columns:
        df["category"] = ""

    lines: list[CashflowLine] = []
    for idx, row in df.iterrows():
        name = str(row.get("name") or "").strip()
        if not name:
            continue
        line_type = str(row.get("type") or "").strip().lower()
        if line_type not in LINE_TYPES:
            warnings.append(
                f"Row {idx + 2}: unknown type '{line_type}' for '{name}', skipped. "
                f"Valid: {LINE_TYPES}."
            )
            continue
        category = str(row.get("category") or "").strip()
        amounts: list[float] = [0.0] * WEEK_COUNT
        for w in range(1, WEEK_COUNT + 1):
            col = next((c for c in df.columns if c.upper() == f"W{w}"), None)
            if col is None:
                amounts[w - 1] = 0.0
                continue
            val = row.get(col)
            if pd.isna(val) or val == "":
                amounts[w - 1] = 0.0
            else:
                try:
                    amounts[w - 1] = float(str(val).replace(",", ""))
                except (ValueError, TypeError):
                    amounts[w - 1] = 0.0
                    warnings.append(
                        f"Row {idx + 2}: '{name}' W{w} not numeric ({val!r}), treated as 0."
                    )

        if all(a == 0.0 for a in amounts):
            # Drop empty rows silently (treasury teams leave placeholder rows).
            continue

        lines.append(CashflowLine(
            name=name, type=line_type, category=category,
            amounts=amounts, source=default_source,
        ))

    return lines


def _coerce_columns_lowercase(df: pd.DataFrame, *, keep_week_cols: bool) -> pd.DataFrame:
    """Rename columns to lowercase except W1..W13 stay capitalised for clarity."""
    rename: dict[str, str] = {}
    for c in df.columns:
        if keep_week_cols and c.upper() in WEEK_COLS:
            rename[c] = c.upper()
        else:
            rename[c] = c.lower()
    return df.rename(columns=rename)


# ---- Long layout adapter --------------------------------------------

def _parse_long(
    xl: pd.ExcelFile,
    sheet_name: str,
    *,
    warnings: list[str],
) -> list[CashflowLine]:
    df = xl.parse(sheet_name)
    df.columns = [str(c).strip().lower() for c in df.columns]
    required = {"week", "name", "type", "amount"}
    missing_cols = required - set(df.columns)
    if missing_cols:
        raise ValueError(
            f"'{sheet_name}' sheet missing required columns: {sorted(missing_cols)}. "
            "Long layout needs: week | name | type | amount (and optional category, source)."
        )

    if "category" not in df.columns:
        df["category"] = ""
    if "source" not in df.columns:
        df["source"] = "forecast"

    grouped: dict[tuple[str, str, str], list[float]] = {}
    sources: dict[tuple[str, str, str], str] = {}
    for idx, row in df.iterrows():
        try:
            week = int(row["week"])
        except (ValueError, TypeError):
            warnings.append(f"Row {idx + 2}: week not numeric ({row['week']!r}), skipped.")
            continue
        if not (1 <= week <= WEEK_COUNT):
            warnings.append(f"Row {idx + 2}: week {week} out of range (1 to {WEEK_COUNT}), skipped.")
            continue

        name = str(row.get("name") or "").strip()
        line_type = str(row.get("type") or "").strip().lower()
        category = str(row.get("category") or "").strip()
        if not name or line_type not in LINE_TYPES:
            continue

        try:
            amount = float(str(row["amount"]).replace(",", ""))
        except (ValueError, TypeError):
            amount = 0.0

        key = (name, line_type, category)
        if key not in grouped:
            grouped[key] = [0.0] * WEEK_COUNT
            sources[key] = str(row.get("source") or "forecast").strip().lower()
        grouped[key][week - 1] += amount

    lines: list[CashflowLine] = []
    for (name, line_type, category), amounts in grouped.items():
        if all(a == 0.0 for a in amounts):
            continue
        lines.append(CashflowLine(
            name=name, type=line_type, category=category,
            amounts=amounts, source=sources.get((name, line_type, category), "forecast"),
        ))
    return lines


# ---- Actuals overlay -------------------------------------------------

def _overlay_actuals(
    forecast: list[CashflowLine],
    actuals: list[CashflowLine],
    *,
    warnings: list[str],
) -> list[CashflowLine]:
    """Apply actuals on top of forecast: any populated actual cell wins.

    Lines are matched on (name, type, category). Actuals lines without a
    matching forecast line are added as new entries (treated as standalone).
    """
    forecast_map = {(l.name, l.type, l.category): l for l in forecast}

    for a_line in actuals:
        key = (a_line.name, a_line.type, a_line.category)
        f_line = forecast_map.get(key)
        if f_line is None:
            forecast_map[key] = CashflowLine(
                name=a_line.name, type=a_line.type, category=a_line.category,
                amounts=list(a_line.amounts), source="actual",
            )
            continue
        # Per-week overlay: any non-zero actual cell overrides the forecast cell.
        merged = list(f_line.amounts)
        for i, val in enumerate(a_line.amounts):
            if val != 0.0:
                merged[i] = val
        f_line.amounts = merged
        f_line.source = "hybrid"
    return list(forecast_map.values())


# ---- Helpers for tests + UI -----------------------------------------

def week_iso_label(start_date: dt.date, week_index_1_based: int) -> str:
    """Return an ISO week label like '2026-W18' for display only."""
    target = start_date + dt.timedelta(days=7 * (week_index_1_based - 1))
    iso_year, iso_week, _ = target.isocalendar()
    return f"{iso_year:04d}-W{iso_week:02d}"


def lines_total_by_type(lines: Iterable[CashflowLine]) -> dict[str, float]:
    """Total amount by type across all weeks. Used by the AI digest."""
    out: dict[str, float] = {t: 0.0 for t in LINE_TYPES}
    for line in lines:
        out[line.type] = out.get(line.type, 0.0) + line.total()
    return out
