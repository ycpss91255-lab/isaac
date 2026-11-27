"""Hosted tests for the per-step output cost runner (isaac#385)."""

import importlib.util
import re
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.core

_RUNNER = (Path(__file__).resolve().parents[2] / "integration" / "pytest"
           / "_output_cost_runner.py")
_CASES = {
    "cam_640_30hz": ("rgb", (640, 480), 30, 33.3),
    "cam_640_60hz": ("rgb", (640, 480), 60, 16.7),
    "cam_1280": ("rgb", (1280, 720), 30, 33.3),
    "depth_640": ("depth", (640, 480), 30, 33.3),
    "jsimu": ("jsimu", None, 200, 5.0),
}


def _load_runner(monkeypatch):
    """Import the standalone runner without invoking its Kit entry point."""
    spec = importlib.util.spec_from_file_location(_RUNNER.stem, _RUNNER)
    runner = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, runner)
    spec.loader.exec_module(runner)
    return runner


def test_import_does_not_attempt_to_load_isaac_or_ros(monkeypatch):
    """Catch lazy or optional imports executed during module initialization."""
    forbidden = {"isaacsim", "omni", "pxr", "rclpy", "isaaclab"}

    class HostedImportGuard:
        def find_spec(self, fullname, path=None, target=None):
            if fullname.partition(".")[0] in forbidden:
                pytest.fail(f"Runner attempted to import {fullname}")
            return None

    for name in list(sys.modules):
        if name.partition(".")[0] in forbidden:
            monkeypatch.delitem(sys.modules, name)
    monkeypatch.setattr(sys, "meta_path", [HostedImportGuard(), *sys.meta_path])
    _load_runner(monkeypatch)


def test_cases_define_sensor_kind_resolution_rate_and_budget(monkeypatch):
    cases = _load_runner(monkeypatch).CASES
    assert set(cases) == set(_CASES)
    for name, expected in _CASES.items():
        case = cases[name]
        assert (case["kind"], case["resolution"], case["hz"],
                case["budget_ms"]) == expected, name


@pytest.mark.parametrize("hz, expected", [(30, 33.3), (60, 16.7), (200, 5.0)])
def test_budget_ms_rounds_the_step_period_to_tenths(monkeypatch, hz, expected):
    assert _load_runner(monkeypatch).budget_ms(hz) == pytest.approx(expected)


def test_summarize_reports_mean_extrema_and_range(monkeypatch):
    summary = _load_runner(monkeypatch).summarize([0.5, -0.1, 0.1, 0.1])
    assert summary == pytest.approx({
        "mean": 0.15, "min": -0.1, "max": 0.5, "spread": 0.6,
    })


def test_share_of_budget_is_a_percentage(monkeypatch):
    runner = _load_runner(monkeypatch)
    assert runner.share_of_budget(0.040, 5.0) == pytest.approx(0.8)


@pytest.mark.parametrize("load, spread, mean, expected", [
    (2.0, 0.25, 1.0, False),
    (2.1, 0.10, 1.0, True),
    (1.0, 0.20, 0.5, True),
    (1.0, 0.20, 2.0, False),
])
def test_contamination_uses_host_load_or_relative_spread(
    monkeypatch, load, spread, mean, expected,
):
    runner = _load_runner(monkeypatch)
    assert runner.is_contaminated(
        load, spread, mean, load_threshold=2.0, spread_ratio=0.25,
    ) is expected


def test_render_table_reports_each_measurement(monkeypatch):
    runner = _load_runner(monkeypatch)
    results = {}
    for n, (name, case) in enumerate(runner.CASES.items(), start=3):
        mean = n / 10
        results[name] = {
            "mean": mean, "min": mean - 0.1, "max": mean + 0.1,
            "budget_ms": case["budget_ms"], "n": n, "warmup_sec": n + 0.5,
            "contaminated": False,
        }

    lines = runner.render_table(results).strip().splitlines()
    assert lines[0] == (
        "| case | budget ms | extra ms | share of budget | n | "
        "warm-up seconds |"
    )
    assert re.fullmatch(r"\|(?:\s*:?-+:?\s*\|){6}", lines[1])
    assert len(lines[2:]) == len(results)
    seen = set()
    for line in lines[2:]:
        name, budget, extra, share, n, warmup = (
            cell.strip() for cell in line.strip("|").split("|")
        )
        result = results[name]
        seen.add(name)
        assert float(budget) == pytest.approx(result["budget_ms"])
        # The extra-ms cell carries the mean and both ends of the range.
        values = [float(v) for v in re.findall(r"\d+(?:\.\d+)?", extra)]
        assert sorted(values) == pytest.approx(
            [result["min"], result["mean"], result["max"]]
        )
        assert share.endswith("%")
        assert float(share[:-1]) == pytest.approx(
            100 * result["mean"] / result["budget_ms"], abs=0.05
        )
        assert int(n) == result["n"]
        assert float(warmup) == result["warmup_sec"]
    assert seen == set(results)

    # A flag must be visible on the affected row even with the same timings.
    results["jsimu"]["contaminated"] = True
    flagged = runner.render_table(results).splitlines()
    clean_row, = (line for line in lines if "jsimu" in line)
    flagged_row, = (line for line in flagged if "jsimu" in line)
    assert flagged_row != clean_row


def test_parser_accepts_measurement_options(monkeypatch, tmp_path):
    parser = _load_runner(monkeypatch).build_parser()
    out = tmp_path / "cost.md"
    for case in _CASES:
        args = parser.parse_args([
            "--case", case, "--repeats", "4", "--warmup-sec", "2.5",
            "--steps", "120", "--out", str(out),
        ])
        assert args.case == case
        assert (args.repeats, args.warmup_sec, args.steps) == (4, 2.5, 120)
        assert Path(args.out) == out
