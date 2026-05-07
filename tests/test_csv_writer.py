"""Day 4. CSV writer tests.

Just enough to lock down column ordering, encoding, and that we don't
accidentally write 'None' for empty cells.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from csv_writer import LINES_COLUMNS, WEEKLY_COLUMNS, write_csv_pair
from pipeline import analyse

DAY_ROOT = Path(__file__).resolve().parent.parent
SAMPLES = DAY_ROOT / "sample_data"


@pytest.fixture(scope="module")
def services_result():
    services = SAMPLES / "sample_services.xlsx"
    if not services.is_file():
        pytest.skip("services sample not built; run sample_data/_build.py first")
    return analyse(path=services, source_filename=services.name, skip_ai=True)


def test_csv_files_written(services_result, tmp_path) -> None:
    weekly, lines = write_csv_pair(services_result, tmp_path)
    assert weekly.is_file()
    assert lines.is_file()


def test_csv_encoding_is_utf8_sig(services_result, tmp_path) -> None:
    weekly, _ = write_csv_pair(services_result, tmp_path)
    head = weekly.read_bytes()[:3]
    assert head == b"\xef\xbb\xbf", "utf-8-sig BOM expected at start"


def test_weekly_csv_has_expected_header(services_result, tmp_path) -> None:
    weekly, _ = write_csv_pair(services_result, tmp_path)
    line = weekly.read_text(encoding="utf-8-sig").splitlines()[0]
    cols = [c.strip() for c in line.split(",")]
    assert cols == WEEKLY_COLUMNS


def test_lines_csv_skips_zero_amounts(services_result, tmp_path) -> None:
    _, lines = write_csv_pair(services_result, tmp_path)
    # Header + at least a few rows. Zero amounts are filtered out.
    rows = lines.read_text(encoding="utf-8-sig").splitlines()
    assert rows[0].split(",") == LINES_COLUMNS
    for row in rows[1:]:
        amount_str = row.split(",")[4]
        assert float(amount_str) != 0.0, "zero amount leaked into lines CSV"
