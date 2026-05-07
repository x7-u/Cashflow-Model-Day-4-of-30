"""Day 4. Hard rule: no em-dash (U+2014) or en-dash (U+2013) anywhere
in the day-04 source tree.

This test scans every .py / .html / .css / .js / .md file under the day
folder and fails the build if either byte sequence is present. The test
file itself contains the byte literals ``EM`` and ``EN`` so it has to
exempt its own path from the scan.
"""
from __future__ import annotations

import pathlib

DAY_ROOT = pathlib.Path(__file__).resolve().parent.parent
EXTS = {".py", ".html", ".css", ".js", ".md"}
EM = b"\xe2\x80\x94"
EN = b"\xe2\x80\x93"
SELF = pathlib.Path(__file__).resolve()


def test_no_em_or_en_dashes() -> None:
    offenders: list[str] = []
    for path in DAY_ROOT.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix not in EXTS:
            continue
        if path.resolve() == SELF:
            continue
        if "__pycache__" in path.parts:
            continue
        data = path.read_bytes()
        for line_no, line in enumerate(data.splitlines(), start=1):
            if EM in line or EN in line:
                snippet = line.decode("utf-8", errors="replace")[:80]
                offenders.append(f"{path.relative_to(DAY_ROOT)}:{line_no}: {snippet}")

    assert not offenders, "em or en dashes found:\n" + "\n".join(offenders)
