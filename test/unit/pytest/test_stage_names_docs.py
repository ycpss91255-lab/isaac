"""Check Docker stage names in the driver and Action Graph docs (isaac#86)."""

from pathlib import Path

import pytest

pytestmark = pytest.mark.docs

_REPO_ROOT = Path(__file__).resolve().parents[3]


def test_driver_has_no_retired_stream_stage():
    driver = _REPO_ROOT / "framework/isaac_devkit/driver.py"
    assert "headless-stream" not in driver.read_text(encoding="utf-8")


def test_action_graph_setup_uses_current_stage_names():
    guide = _REPO_ROOT / "src/doc/action_graph_setup.md"
    for number, line in enumerate(guide.read_text(encoding="utf-8").splitlines(), 1):
        location = f"{guide.name}:{number}: {line}"
        assert "-t standalone" not in line, location
        assert "headless-stream" not in line, location
        if "runheadless" in line:
            assert "-t headless" not in line, location
