"""Shared theme -- RAG palette + matplotlib defaults.

The palette is consumed by:
- excel_writer.py (RAG_HEX → openpyxl PatternFill ARGB)
- static/style.css (RAG colour variables; intentionally kept in sync by hand)
- any matplotlib chart in later days (call apply_style() once at start)
"""
from __future__ import annotations

RAG = {
    "green": "#2E8540",
    "amber": "#F0A030",
    "red": "#C62828",
}

# Hex without the '#' prefix -- convenient for openpyxl PatternFill (ARGB strings).
RAG_HEX = {k: v.lstrip("#") for k, v in RAG.items()}

PALETTE = ["#1F4E79", "#2E8540", "#F0A030", "#C62828", "#5B5B5B", "#7B68A6"]


def apply_style() -> None:
    """Apply the shared matplotlib theme. Lazy-imported so non-matplotlib days
    don't pay the import cost."""
    import matplotlib as mpl  # noqa: PLC0415

    mpl.rcParams.update({
        "font.family": ["Arial", "Helvetica", "DejaVu Sans"],
        "font.size": 10,
        "axes.titlesize": 12,
        "axes.titleweight": "bold",
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.grid": True,
        "grid.color": "#D0D0D0",
        "grid.linewidth": 0.6,
        "axes.prop_cycle": mpl.cycler(color=PALETTE),
        "figure.dpi": 110,
        "savefig.dpi": 150,
        "savefig.bbox": "tight",
    })
