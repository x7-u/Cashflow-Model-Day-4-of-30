import math
from datetime import date, datetime


def gbp(x: float | int | None, dp: int = 2) -> str:
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "n/a"
    return f"£{x:,.{dp}f}"


def pct(x: float | None, dp: int = 1) -> str:
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "n/a"
    return f"{x * 100:.{dp}f}%"


def ratio(x: float | None, dp: int = 2) -> str:
    if x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))):
        return "n/a"
    return f"{x:.{dp}f}x"


def days(x: float | None, dp: int = 0) -> str:
    if x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))):
        return "n/a"
    return f"{x:.{dp}f} days"


def iso_date(d: date | datetime | str) -> str:
    if isinstance(d, str):
        return d[:10]
    return d.strftime("%Y-%m-%d")
