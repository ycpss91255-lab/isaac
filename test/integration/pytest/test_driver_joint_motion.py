"""Regression for #447. A velocity command must turn both Jetbot wheels."""

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


@pytest.mark.parametrize("engine", ["physx", "newton"])
@pytest.mark.skipif(not Path(PYTHON_SH).is_file(), reason="requires Isaac Sim")
def test_driver_applies_wheel_velocity(engine):
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
    match = re.search(r"^\[WHEEL MOTION\] (\w+) (\S+) (\S+)$", result.stdout, re.MULTILINE)
    assert match, result.stdout[-4000:]
    active, left, right = match.groups()
    assert active.lower() == engine
    # One radian in the commanded direction on each wheel excludes startup jitter.
    assert float(left) > 1.0, match.group()
    assert float(right) > 1.0, match.group()
