"""Check Jetbot wheel motion and IsaacDriver timeline settings and pacing (#447)."""

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from test_assets import fetch_test_asset  # noqa: E402

pytestmark = pytest.mark.core

PYTHON_SH = "/isaac-sim/python.sh"
RUNNER = Path(__file__).with_name("_driver_joint_motion_runner.py")


@pytest.fixture(scope="module", params=["physx", "newton"])
def driver_run(request):
    if not Path(PYTHON_SH).is_file():
        pytest.skip("requires Isaac Sim")
    engine = request.param
    result = subprocess.run(
        [PYTHON_SH, str(RUNNER), "--engine", engine,
         "--robot-usd", str(fetch_test_asset("jetbot"))],
        env={
            **os.environ,
            "ISAAC_LIVESTREAM": "0",
            "ISAAC_IO_PLUGIN": "",
            "ISAAC_KIT_EXTRA_ARGS": "",
        },
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=900,
    )
    # Kit can exit with status zero even when driver setup or stepping raises.
    assert result.returncode == 0, result.stdout[-4000:]
    return engine, result.stdout


def test_driver_applies_wheel_velocity(driver_run):
    engine, output = driver_run
    match = re.search(r"^\[WHEEL MOTION\] (\w+) (\S+) (\S+)$", output, re.MULTILINE)
    assert match, output[-4000:]
    active, left, right = match.groups()
    assert active.lower() == engine
    # One radian in the commanded direction on each wheel excludes startup jitter.
    assert float(left) > 1.0, match.group()
    assert float(right) > 1.0, match.group()


def test_driver_timeline_settings(driver_run):
    _, output = driver_run
    match = re.search(
        r"^\[DRIVE SETTINGS\] rate_limit_enabled=(\w+) rate_limit_hz=(\S+) "
        r"fixed_step=(\w+) looping=(\w+)$",
        output, re.MULTILINE,
    )
    assert match, output[-4000:]
    rate_limit_enabled, rate_limit_hz, fixed_step, looping = match.groups()
    assert rate_limit_enabled == "True", match.group()
    assert float(rate_limit_hz) == 60, match.group()
    assert fixed_step == "True", match.group()
    assert looping == "False", match.group()


def test_driver_timeline_clock(driver_run):
    """sim_hz measures updates per second of omni.timeline simulation time."""
    _, output = driver_run
    match = re.search(
        r"^\[DRIVE CLOCK\] sim_hz=(\S+) wall_hz=(\S+) monotonic=(\w+) "
        r"span_s=(\S+) updates=(\d+)$",
        output, re.MULTILINE,
    )
    assert match, output[-4000:]
    sim_hz, wall_hz, monotonic, span_s, updates = match.groups()
    assert int(updates) >= 2, match.group()
    assert float(span_s) > 0, match.group()
    assert monotonic == "True", match.group()
    assert float(sim_hz) == pytest.approx(60, rel=0.15), match.group()
    # Only an upper bound: wall rate drops under shared-host load, but removing
    # the driver 60 Hz rate limit pushes it to ~120 Hz. Allow 15% above 60 Hz.
    assert float(wall_hz) < 69, match.group()
