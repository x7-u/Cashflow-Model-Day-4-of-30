"""Day 4. Flat CSV outputs for the cash flow forecast.

Two files per analyse run:
- weekly_balances.csv   one row per week with receipts, payments, payroll,
                        tax, net, opening, closing, RAG.
- line_items.csv        one row per (line, week) so the data lands cleanly
                        in Power Query / Pandas.

Encoding is utf-8-sig so Excel auto-detects UTF-8.
"""
from __future__ import annotations

import csv
from pathlib import Path

from pipeline import AnalysisResult

WEEKLY_COLUMNS: list[str] = [
    "week", "iso_week_label", "receipts", "payments", "payroll", "tax",
    "inflow", "outflow", "net", "opening", "closing", "rag",
    "concentration_pct",
]

LINES_COLUMNS: list[str] = [
    "name", "type", "category", "week", "amount", "source",
]


def write_weekly_csv(result: AnalysisResult, out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(WEEKLY_COLUMNS)
        for w in result.weeks:
            writer.writerow([
                w.week, w.iso_week_label,
                _num(w.receipts), _num(w.payments), _num(w.payroll), _num(w.tax),
                _num(w.inflow), _num(w.outflow), _num(w.net),
                _num(w.opening), _num(w.closing),
                w.rag,
                ("" if w.concentration_pct is None else f"{w.concentration_pct:.4f}"),
            ])
    return out_path


def write_lines_csv(result: AnalysisResult, out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(LINES_COLUMNS)
        for line in result.lines:
            for week_idx, amount in enumerate(line.amounts, start=1):
                if amount == 0.0:
                    continue
                writer.writerow([
                    line.name, line.type, line.category,
                    week_idx, _num(amount), line.source,
                ])
    return out_path


def write_csv_pair(
    result: AnalysisResult,
    out_dir: Path,
    *,
    stem: str = "cashflow",
) -> tuple[Path, Path]:
    """Convenience: write both CSVs to ``out_dir`` and return (weekly, lines)."""
    weekly = write_weekly_csv(result, out_dir / f"{stem}_weekly.csv")
    lines  = write_lines_csv(result, out_dir / f"{stem}_lines.csv")
    return (weekly, lines)


def _num(v: float) -> str:
    """Numeric format: blank for zero amount? No, treasurers want to see the zero.
    Just round to 2dp."""
    return f"{float(v):.2f}"
