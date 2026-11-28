"""Report GPU test wall time and the portion spent constructing SimulationApp."""

import json
import os
import re
import subprocess
import time
from pathlib import Path
from unittest.mock import patch

import pytest

_FILES = pytest.StashKey[dict]()
_FIELDS = ("kit_boot_sec", "test_body_sec", "total_sec")
_BOOT = re.compile(r"^\[KIT-TIMING\] boot_sec=(\d+(?:\.\d+)?)\r?$", re.MULTILINE)


def _boot_seconds(stdout):
    if isinstance(stdout, bytes):
        stdout = stdout.decode(errors="replace")
    match = _BOOT.search(stdout or "")
    return float(match[1]) if match else 0.0


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_protocol(item):
    files = item.config.stash.setdefault(_FILES, {})
    filename = item.nodeid.split("::", 1)[0]
    row = files.setdefault(filename, dict.fromkeys(_FIELDS, 0.0))
    run = subprocess.run

    def timed_run(*args, **kwargs):
        try:
            result = run(*args, **kwargs)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            row["kit_boot_sec"] += _boot_seconds(exc.stdout)
            raise
        row["kit_boot_sec"] += _boot_seconds(result.stdout)
        return result

    # Include fixture setup and teardown. A shared fixture launches its runner once.
    with patch.object(subprocess, "run", timed_run):
        start = time.monotonic()
        try:
            yield
        finally:
            row["total_sec"] += time.monotonic() - start
            row["test_body_sec"] = row["total_sec"] - row["kit_boot_sec"]


def pytest_terminal_summary(terminalreporter, config):
    files = config.stash.get(_FILES, {})
    if not files:
        return
    total = {key: sum(row[key] for row in files.values()) for key in _FIELDS}
    for name, row in {**files, "TOTAL": total}.items():
        terminalreporter.write_line(
            f"[FILE-TIMING] file={name} kit_boot_sec={row['kit_boot_sec']:.6f} "
            f"test_body_sec={row['test_body_sec']:.6f} total_sec={row['total_sec']:.6f}"
        )
    path = os.environ.get("KIT_TIMING_JSON")
    if path:
        Path(path).write_text(json.dumps({"files": files, "total": total}, indent=2) + "\n")
