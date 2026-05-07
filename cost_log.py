"""Day 4. Persistent cost log.

Every analysis or scenario run appends one JSONL line to
``outputs/runs.jsonl``. The sidebar shows running totals so the user has
an honest picture of what the AI is costing them. Mirrors the Day 3
cost log exactly so the data shape stays consistent across days.
"""
from __future__ import annotations

import datetime as dt
import json
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path

DEFAULT_LOG_PATH = Path(__file__).resolve().parent / "outputs" / "runs.jsonl"


@dataclass
class CostSummary:
    runs: int
    cost_usd_total: float
    rows_total: int
    last_run_at: str | None
    cost_usd_30d: float
    runs_30d: int


class CostLog:
    """Thread-safe JSONL append store with a small read-side helper."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path is not None else DEFAULT_LOG_PATH
        self._lock = threading.Lock()

    def append(
        self,
        *,
        company: str,
        period_label: str,
        rows: int,
        cost_usd: float,
        model: str,
        skipped: bool,
        elapsed_ms: int,
        source_filename: str = "",
        total_variance: float | None = None,
        total_variance_pct: float | None = None,
        rag_red: int | None = None,
    ) -> dict:
        entry = {
            "id": uuid.uuid4().hex[:12],
            "ts": dt.datetime.now(dt.UTC).replace(microsecond=0, tzinfo=None).isoformat() + "Z",
            "company": company,
            "period_label": period_label,
            "source_filename": source_filename,
            "rows": int(rows),
            "cost_usd": round(float(cost_usd), 6),
            "model": model or "",
            "skipped": bool(skipped),
            "elapsed_ms": int(elapsed_ms),
            "total_variance": (None if total_variance is None else round(float(total_variance), 2)),
            "total_variance_pct": (None if total_variance_pct is None else round(float(total_variance_pct), 6)),
            "rag_red": rag_red,
        }
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return entry

    def entries(self, limit: int = 500) -> list[dict]:
        if not self.path.exists():
            return []
        out: list[dict] = []
        try:
            for line in self.path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        except OSError:
            return []
        return list(reversed(out[-limit:]))

    def summary(self) -> CostSummary:
        items = self.entries(limit=10000)
        if not items:
            return CostSummary(
                runs=0, cost_usd_total=0.0, rows_total=0,
                last_run_at=None, cost_usd_30d=0.0, runs_30d=0,
            )
        cost_total = sum(i.get("cost_usd", 0) or 0 for i in items)
        rows_total = sum(i.get("rows", 0) or 0 for i in items)
        last_at = items[0].get("ts")
        cutoff = (
            dt.datetime.now(dt.UTC)
            .replace(microsecond=0, tzinfo=None) - dt.timedelta(days=30)
        ).isoformat() + "Z"
        recent = [i for i in items if (i.get("ts") or "") >= cutoff]
        cost_30d = sum(i.get("cost_usd", 0) or 0 for i in recent)
        return CostSummary(
            runs=len(items),
            cost_usd_total=round(cost_total, 6),
            rows_total=rows_total,
            last_run_at=last_at,
            cost_usd_30d=round(cost_30d, 6),
            runs_30d=len(recent),
        )

    def clear(self) -> int:
        with self._lock:
            count = len(self.entries(limit=10000))
            if self.path.exists():
                self.path.write_text("", encoding="utf-8")
            return count
