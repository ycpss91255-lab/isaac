"""Check the published output cost measurements against isaac#385."""

import importlib.util
import re
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.docs

_ROOT = Path(__file__).resolve().parents[3]
_DOC = _ROOT / "doc" / "test" / "output-api-cost.md"
_RUNNER = _ROOT / "test" / "integration" / "pytest" / "_output_cost_runner.py"
_COLUMNS = ["case", "budget ms", "extra ms", "share of budget", "n",
            "warm-up seconds"]
_CASES = {"cam_640_30hz", "cam_640_60hz", "cam_1280", "depth_640", "jsimu"}


def _cells(line):
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _measurement_rows():
    """Read the measurement table, allowing unrelated tables in the report."""
    lines = iter(_DOC.read_text(encoding="utf-8").splitlines())
    assert any(_cells(line) == _COLUMNS for line in lines), "Missing header"
    separator = _cells(next(lines, ""))
    assert len(separator) == len(_COLUMNS)
    assert all(re.fullmatch(r":?-+:?", cell) for cell in separator)
    rows = []
    for line in lines:
        if not line.startswith("|"):
            break
        cells = _cells(line)
        assert len(cells) == len(_COLUMNS), line
        rows.append(dict(zip(_COLUMNS, cells)))
    return rows


def test_report_has_five_cases_with_at_least_three_runs_each():
    rows = _measurement_rows()
    assert len(rows) == len(_CASES)
    assert {row["case"].strip("`") for row in rows} == _CASES
    for row in rows:
        assert re.fullmatch(r"[0-9]+", row["n"]), row
        assert int(row["n"]) >= 3, row


def test_report_has_six_space_prefixed_table_lines():
    lines = _DOC.read_text(encoding="utf-8").splitlines()
    assert sum(line.startswith("| ") for line in lines) >= 6


def test_report_budgets_match_the_runner(monkeypatch):
    rows = _measurement_rows()
    spec = importlib.util.spec_from_file_location(_RUNNER.stem, _RUNNER)
    runner = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, runner)
    spec.loader.exec_module(runner)
    budgets = {row["case"].strip("`"): float(row["budget ms"]) for row in rows}
    assert budgets == {
        name: case["budget_ms"] for name, case in runner.CASES.items()
    }


def test_report_records_noise_floor_contamination_load_and_prototype():
    report = _DOC.read_text(encoding="utf-8")
    assert "noise floor" in report.lower()
    assert "contaminated" in report.lower()
    assert re.search(r"\bload\b", report, re.IGNORECASE)
    assert re.search(
        r"https?://github\.com/ycpss91255-lab/isaac/issues/365\b", report
    )
