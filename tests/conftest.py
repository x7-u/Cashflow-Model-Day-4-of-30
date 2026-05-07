"""Day 4 test isolation.

Each day folder defines modules with the same basenames (server, main,
pipeline, csv_writer, excel_writer, etc.). pytest collects them all in
one process, so without a conftest the second day to run inherits cached
imports from the first. This evicts the conflicting names from
sys.modules and prepends Day 4's folder to sys.path so 'from cashflow_maths
import ...' resolves to Day 4's version.
"""
from __future__ import annotations

import sys
from pathlib import Path

DAY_ROOT = Path(__file__).resolve().parent.parent
PROJECT_ROOT = DAY_ROOT.parent

_CONFLICTING = {
    # Day 1 to 3 module names that may already be cached.
    "excel_writer", "pipeline", "csv_writer", "ratios", "sectors",
    "pdf_loader", "invoice_schema", "main", "server", "ledger",
    "variance", "budget_schema", "cost_log", "pptx_writer",
    "history_store", "comparison", "run_cache", "power_bi",
    # Day 4 names.
    "cashflow_schema", "cashflow_maths", "scenario", "chart",
}


def _evict_and_set_path() -> None:
    for name in list(_CONFLICTING):
        sys.modules.pop(name, None)
    for p in (str(DAY_ROOT), str(PROJECT_ROOT)):
        if p in sys.path:
            sys.path.remove(p)
    sys.path.insert(0, str(DAY_ROOT))
    sys.path.insert(0, str(PROJECT_ROOT))


_evict_and_set_path()


def pytest_collectstart(collector):
    p = getattr(collector, "path", None) or getattr(collector, "fspath", None)
    if p is None:
        return
    if str(DAY_ROOT) in str(p):
        _evict_and_set_path()


for p in (str(DAY_ROOT), str(PROJECT_ROOT)):
    if p in sys.path:
        sys.path.remove(p)
sys.path.insert(0, str(DAY_ROOT))
sys.path.insert(0, str(PROJECT_ROOT))
