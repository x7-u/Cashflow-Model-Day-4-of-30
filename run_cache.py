"""Day 4. Run cache.

Persists the full JSON result of each successful run as
``outputs/runs/<run_id>.json`` so the UI can re-open a past run and
the scenario engine can apply a shock to a base run without making
the user re-upload the workbook.

Capped at MAX_RUNS so the cache does not grow unbounded; oldest files
are evicted when the cap is exceeded. Mirrors Day 3.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path

MAX_RUNS = 100
DEFAULT_DIR = Path(__file__).resolve().parent / "outputs" / "runs"


class RunCache:
    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root) if root is not None else DEFAULT_DIR
        self._lock = threading.Lock()

    def save(self, run_id: str, payload: dict) -> Path:
        with self._lock:
            self.root.mkdir(parents=True, exist_ok=True)
            path = self.root / f"{run_id}.json"
            tmp = path.with_suffix(".json.tmp")
            with tmp.open("w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False)
            tmp.replace(path)
            self._evict_old()
            return path

    def get(self, run_id: str) -> dict | None:
        path = self.root / f"{run_id}.json"
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def remove(self, run_id: str) -> bool:
        path = self.root / f"{run_id}.json"
        if not path.is_file():
            return False
        try:
            path.unlink()
            return True
        except OSError:
            return False

    def clear(self) -> int:
        with self._lock:
            if not self.root.exists():
                return 0
            n = 0
            for p in self.root.glob("*.json"):
                try:
                    p.unlink()
                    n += 1
                except OSError:
                    continue
            return n

    def _evict_old(self) -> None:
        files = sorted(self.root.glob("*.json"), key=lambda p: p.stat().st_mtime)
        excess = len(files) - MAX_RUNS
        for p in files[:max(0, excess)]:
            try:
                p.unlink()
            except OSError:
                continue
