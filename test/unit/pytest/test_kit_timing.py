"""Hosted tests for the GPU suite's timing report (isaac#527)."""

import json
import os
import re
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.core

_TEST_DIR = Path(__file__).resolve().parents[2]
_FIELDS = ("kit_boot_sec", "test_body_sec", "total_sec")


@pytest.fixture(scope="module")
def timing_run(tmp_path_factory):
    suite = tmp_path_factory.mktemp("kit_timing")
    (suite / "_sample_runner.py").write_text(textwrap.dedent("""\
        import sys
        import time

        print("progress boot_sec=17.0")
        print("[KIT-TIMING] boot_sec=invalid")
        print("[KIT-TIMING] boot_sec=42.0", file=sys.stderr)
        if sys.argv[1] != "unmarked":
            time.sleep(float(sys.argv[1]))
            print("[KIT-TIMING] boot_sec=" + sys.argv[1])
        print("runner finished")
    """))
    (suite / "test_boots.py").write_text(textwrap.dedent("""\
        import subprocess
        import sys
        import time

        import pytest

        @pytest.fixture(scope="module")
        def shared_runner():
            return subprocess.run([sys.executable, "_sample_runner.py", "0.10"],
                                  capture_output=True, text=True, check=True)

        def test_first(shared_runner):
            assert "runner finished" in shared_runner.stdout
            time.sleep(0.10)

        def test_second(shared_runner):
            assert "runner finished" in shared_runner.stdout
            subprocess.run([sys.executable, "_sample_runner.py", "0.20"],
                           capture_output=True, text=True, check=True)
            time.sleep(0.10)
    """))
    (suite / "test_unmarked.py").write_text(textwrap.dedent("""\
        import subprocess
        import sys
        import time

        def test_runner_without_boot_marker():
            subprocess.run([sys.executable, "_sample_runner.py", "unmarked"],
                           capture_output=True, text=True, check=True)
            time.sleep(0.10)
    """))
    report = suite / "timing.json"
    env = dict(os.environ, PYTHONPATH=str(_TEST_DIR), KIT_TIMING_JSON=str(report),
               PYTEST_DISABLE_PLUGIN_AUTOLOAD="1", PYTEST_ADDOPTS="")
    start = time.monotonic()
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--color=no", "-p", "kit_timing"],
        cwd=suite, env=env, capture_output=True, text=True, timeout=30,
    )
    return result, report, time.monotonic() - start


def _summary_rows(result):
    assert result.returncode == 0, result.stderr + result.stdout
    rows = {}
    for line in result.stdout.splitlines():
        if line.startswith("[FILE-TIMING]"):
            match = re.fullmatch(
                r"\[FILE-TIMING\] file=(\S+) kit_boot_sec=(\S+) "
                r"test_body_sec=(\S+) total_sec=(\S+)", line,
            )
            assert match, line
            name, *seconds = match.groups()
            assert name not in rows, line
            rows[name] = dict(zip(_FIELDS, map(float, seconds)))
    assert set(rows) == {"test_boots.py", "test_unmarked.py", "TOTAL"}
    return rows


def test_boot_seconds_count_each_subprocess_once(timing_run):
    result, _, _ = timing_run
    rows = _summary_rows(result)
    assert rows["test_boots.py"]["kit_boot_sec"] == pytest.approx(0.30)
    assert rows["test_unmarked.py"]["kit_boot_sec"] == 0


def test_file_wall_time_splits_and_sums_to_total(timing_run):
    result, _, elapsed = timing_run
    rows = _summary_rows(result)
    total = rows.pop("TOTAL")
    # Sleep durations give lower bounds even on a busy CI host.
    assert rows["test_boots.py"]["total_sec"] >= 0.50
    assert rows["test_unmarked.py"]["total_sec"] >= 0.10
    for row in rows.values():
        assert row["test_body_sec"] == pytest.approx(
            row["total_sec"] - row["kit_boot_sec"], abs=0.01,
        )
    for field in _FIELDS:
        assert total[field] == pytest.approx(sum(row[field] for row in rows.values()), abs=0.01)
    assert total["total_sec"] <= elapsed + 0.01


def test_json_matches_terminal_rows(timing_run):
    result, report, _ = timing_run
    rows = _summary_rows(result)
    data = json.loads(report.read_text())
    total = rows.pop("TOTAL")
    assert set(data["files"]) == set(rows)
    for field in _FIELDS:
        assert data["total"][field] == pytest.approx(total[field], abs=0.01)
        for name, row in rows.items():
            assert data["files"][name][field] == pytest.approx(row[field], abs=0.01)
