"""GPU smoke tests for Python output mode with the official Jetbot."""

import math
import os
from pathlib import Path
import re
import subprocess
import sys

import pytest

_TEST_DIR = Path(__file__).resolve().parents[2]
if str(_TEST_DIR) not in sys.path:
    sys.path.insert(0, str(_TEST_DIR))

from test_assets import fetch_test_asset  # noqa: E402

pytestmark = pytest.mark.core

REPO_ROOT = _TEST_DIR.parent
RUNNER = Path(__file__).with_name("_output_mode_runner.py")
PYTHON_SH = "/isaac-sim/python.sh"
SUBPROC_TIMEOUT_SEC = 900

requires_isaac = pytest.mark.skipif(
    not Path(PYTHON_SH).exists(), reason="needs the Isaac container"
)


@pytest.fixture(scope="module")
def runner_output():
    """Run one Python-mode scene and check Kit's completion markers."""
    result = subprocess.run(
        [
            PYTHON_SH,
            str(RUNNER),
            "--repo-root",
            str(REPO_ROOT),
            "--robot-usd",
            str(fetch_test_asset("jetbot")),
        ],
        env={**os.environ, "ISAAC_OUTPUT_MODE": "python"},
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=SUBPROC_TIMEOUT_SEC,
    )
    output = result.stdout
    assert "[MODE RAISED]" not in output, output[-2000:]
    assert "[MODE EXIT CLEAN]" in output.splitlines(), output[-2000:]
    return output


@requires_isaac
def test_rgb_callback_receives_frame(runner_output):
    match = re.search(r"^\[MODE RGB\] count=(\d+)$", runner_output, re.MULTILINE)
    assert match, runner_output[-1500:]
    assert int(match[1]) >= 1, match[0]


@requires_isaac
def test_no_ros2_bridge_nodes(runner_output):
    assert "[MODE ROS2_NODES] count=0" in runner_output.splitlines(), (
        runner_output[-1500:]
    )


@requires_isaac
def test_step_time_after_warmup(runner_output):
    match = re.search(
        r"^\[MODE STEP\] warmup=(\d+) steps=300 mean_ms=(\S+) p95_ms=(\S+)$",
        runner_output,
        re.MULTILINE,
    )
    assert match, runner_output[-1500:]
    print(match[0])
    assert int(match[1]) > 0, match[0]
    mean_ms = float(match[2])
    assert math.isfinite(mean_ms) and mean_ms >= 0, match[0]
    assert 0 <= float(match[3]) < 33.3, match[0]
