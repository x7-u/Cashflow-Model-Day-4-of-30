"""Day 4. Chart rendering.

Two PNGs per run, generated with matplotlib's Agg backend (Flask thread
has no display):

1. Waterfall: opening balance to closing balance, week by week, green
   inflow bars and rose outflow bars, balance line in teal.
2. Closing-balance line: weekly closing with markers for min, max, the
   buffer line, and the runway crossing.

The web UI does not load matplotlib; it builds inline SVG directly from
the closing-balance series. The PNGs are for the Excel embed and for
the user to download.
"""
from __future__ import annotations

# Set the backend BEFORE any pyplot import. Required because Flask has
# no display and the default backend tries to load tkinter on Windows.
import matplotlib

matplotlib.use("Agg")

from io import BytesIO
from pathlib import Path

import matplotlib.pyplot as plt

# Variance Terminal palette, same hex as the live UI.
TEAL  = "#2D9CA5"
ROSE  = "#C03E55"
EMER  = "#2E7D55"
AMBER = "#C2821A"
INK   = "#0A1019"
MUTED = "#4A5568"
PANEL = "#EFF4F7"


def render_waterfall_png(
    weeks: list,           # list[WeekRow]
    *,
    title: str,
    out_path: Path | None = None,
) -> bytes:
    """Render a 13-week waterfall chart. Returns PNG bytes.

    If ``out_path`` is given the bytes are also written to disk.
    """
    fig, ax = plt.subplots(figsize=(10, 4.5), dpi=120)
    fig.patch.set_facecolor("white")

    weeks_x = [w.week for w in weeks]
    inflow = [w.inflow for w in weeks]
    outflow = [-w.outflow for w in weeks]  # negative for visual clarity
    closing = [w.closing for w in weeks]

    bar_width = 0.7
    ax.bar(weeks_x, inflow, width=bar_width, color=EMER, label="Inflow",
           edgecolor=INK, linewidth=0.4)
    ax.bar(weeks_x, outflow, width=bar_width, color=ROSE, label="Outflow",
           edgecolor=INK, linewidth=0.4)
    ax.plot(weeks_x, closing, color=TEAL, marker="o", linewidth=2.0,
            markersize=4, label="Closing balance")

    ax.axhline(0, color=MUTED, linewidth=0.6)
    ax.set_xticks(weeks_x)
    ax.set_xticklabels([f"W{w}" for w in weeks_x], fontsize=9)
    ax.set_ylabel("GBP", fontsize=10, color=INK)
    ax.set_title(title, fontsize=12, color=INK, pad=10)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.grid(axis="y", linestyle=":", color=MUTED, alpha=0.4)
    ax.legend(loc="upper right", fontsize=8, frameon=False)

    fig.tight_layout()
    return _flush(fig, out_path)


def render_balance_line_png(
    weeks: list,           # list[WeekRow]
    *,
    title: str,
    buffer: float,
    runway_week: int | None,
    out_path: Path | None = None,
) -> bytes:
    """Render the weekly closing balance as a line with annotations."""
    fig, ax = plt.subplots(figsize=(10, 3.6), dpi=120)
    fig.patch.set_facecolor("white")

    weeks_x = [w.week for w in weeks]
    closing = [w.closing for w in weeks]

    ax.plot(weeks_x, closing, color=TEAL, marker="o", linewidth=2.2,
            markersize=4.5, label="Closing balance")
    ax.fill_between(weeks_x, closing, 0, where=[c < 0 for c in closing],
                    color=ROSE, alpha=0.15, interpolate=True, label="Below zero")
    ax.axhline(0, color=MUTED, linewidth=0.8, label="Zero line")
    if buffer > 0:
        ax.axhline(buffer, color=AMBER, linewidth=0.8, linestyle="--",
                   label=f"Buffer (£{buffer:,.0f})")

    if closing:
        min_c = min(closing)
        max_c = max(closing)
        min_w = closing.index(min_c) + 1
        max_w = closing.index(max_c) + 1
        ax.annotate(
            f"min £{min_c:,.0f}",
            xy=(min_w, min_c), xytext=(min_w, min_c - max(abs(min_c) * 0.1, 1000)),
            fontsize=8, color=ROSE, ha="center",
            arrowprops=dict(arrowstyle="-", color=ROSE, alpha=0.5),
        )
        ax.annotate(
            f"max £{max_c:,.0f}",
            xy=(max_w, max_c), xytext=(max_w, max_c + max(abs(max_c) * 0.1, 1000)),
            fontsize=8, color=EMER, ha="center",
            arrowprops=dict(arrowstyle="-", color=EMER, alpha=0.5),
        )

    if runway_week is not None and 1 <= runway_week <= len(closing):
        ax.axvline(runway_week, color=ROSE, linewidth=1.0, linestyle=":",
                   label=f"Runway W{runway_week}")

    ax.set_xticks(weeks_x)
    ax.set_xticklabels([f"W{w}" for w in weeks_x], fontsize=9)
    ax.set_ylabel("Closing balance (GBP)", fontsize=10, color=INK)
    ax.set_title(title, fontsize=12, color=INK, pad=10)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.grid(axis="y", linestyle=":", color=MUTED, alpha=0.4)
    ax.legend(loc="upper left", fontsize=8, frameon=False)

    fig.tight_layout()
    return _flush(fig, out_path)


def render_inline_svg(
    closing: list[float],
    *,
    width: int = 720,
    height: int = 180,
    pad: int = 16,
) -> str:
    """Build an inline SVG path for the closing-balance line.

    Used by the web UI to avoid a server round-trip when toggling between
    base and scenario. Returns a complete <svg>...</svg> string.
    """
    if not closing:
        return f'<svg width="{width}" height="{height}"></svg>'

    n = len(closing)
    min_c = min(closing)
    max_c = max(closing)
    span = max(abs(max_c - min_c), 1.0)
    inner_w = width - 2 * pad
    inner_h = height - 2 * pad

    def x_at(i: int) -> float:
        return pad + (i / max(n - 1, 1)) * inner_w

    def y_at(v: float) -> float:
        return pad + (1 - (v - min_c) / span) * inner_h

    pts = [(x_at(i), y_at(v)) for i, v in enumerate(closing)]
    d = "M " + " L ".join(f"{x:.1f} {y:.1f}" for x, y in pts)
    zero_y = y_at(0.0) if min_c <= 0 <= max_c else None

    parts = [f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg">']
    parts.append(f'<rect width="{width}" height="{height}" fill="white"/>')
    if zero_y is not None:
        parts.append(f'<line x1="{pad}" y1="{zero_y:.1f}" x2="{width - pad}" y2="{zero_y:.1f}" stroke="{MUTED}" stroke-width="0.8"/>')
    parts.append(f'<path d="{d}" fill="none" stroke="{TEAL}" stroke-width="2"/>')
    for i, (x, y) in enumerate(pts):
        colour = ROSE if closing[i] < 0 else TEAL
        parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3" fill="{colour}"/>')
    parts.append("</svg>")
    return "".join(parts)


# ---- Internal --------------------------------------------------------

def _flush(fig, out_path: Path | None) -> bytes:
    """Convert the figure to PNG bytes and optionally write to disk."""
    buf = BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    data = buf.getvalue()
    if out_path is not None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(data)
    return data
