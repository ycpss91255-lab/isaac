"""IsaacDriver applies velocity commands under Newton and paces the loop (isaac#447).

Boots ``IsaacDriver`` (Isaac Lab ``AppLauncher``) with the official Jetbot
(``test/test_assets.py``), drives both wheels at a constant velocity and
checks, per engine (PhysX is the control):

* the wheel joint positions advance past a threshold (Newton used to
  ignore every command: the AppLauncher experience leaves
  ``SimulationManager`` default callbacks off, so no physics sim view);
* updates run at 60 Hz (+-15 %) in simulation time, wall-clock throughput
  exceeds 20 updates/s, and sim time never wraps (timeline looping off).

The runner enables Newton itself in ``_open_stage`` to verify the sim loop
settings applied by ``driver._play_timeline``.

Run inside the GPU test container::

    ./script/run.sh -t test -- /isaac-sim/python.sh -m pytest \
        <repo>/test/integration/pytest/test_newton_drive_integration.py -s
"""

import re
import subprocess
import sys
from pathlib import Path

import pytest

_TEST_DIR = Path(__file__).resolve().parents[2]
if str(_TEST_DIR) not in sys.path:
    sys.path.insert(0, str(_TEST_DIR))

from test_assets import fetch_test_asset  # noqa: E402

pytestmark = pytest.mark.core

REPO_ROOT = Path(__file__).resolve().parents[3]
RUNNER = Path(__file__).parent / "_newton_drive_runner.py"
PYTHON_SH = "/isaac-sim/python.sh"
SUBPROC_TIMEOUT_SEC = 900
# 10 rad/s commanded for ~6 s; even at a fraction of realtime the wheels
# must turn well past one radian.
MIN_WHEEL_DELTA_RAD = 1.0
RATE_HZ = 60.0
RATE_TOLERANCE = 0.15

requires_isaac = pytest.mark.skipif(
    not Path(PYTHON_SH).exists(), reason="needs the Isaac container"
)


def _run(engine):
    result = subprocess.run(
        [PYTHON_SH, str(RUNNER), "--script-dir", str(REPO_ROOT / "framework"),
         "--robot-usd", str(fetch_test_asset("jetbot")), "--engine", engine],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=SUBPROC_TIMEOUT_SEC,
    )
    return result.stdout


@pytest.fixture(scope="module", params=["physx", "newton"])
def run_output(request):
    return request.param, _run(request.param)


@requires_isaac
def test_engine_is_the_requested_one(run_output):
    engine, out = run_output
    m = re.search(r"\[DRIVE ENGINE\] active=(\w+)", out)
    assert m, out[-2000:]
    assert m.group(1).lower() == engine


@requires_isaac
def test_wheels_turn_under_velocity_command(run_output):
    _, out = run_output
    m = re.search(r"\[DRIVE WHEELS\] left=(-?[\d.]+) right=(-?[\d.]+) delta_rad=[\d.]+", out)
    assert m, out[-2000:]
    left, right = map(float, m.groups())
    assert abs(left) > MIN_WHEEL_DELTA_RAD, m.group(0)
    assert abs(right) > MIN_WHEEL_DELTA_RAD, m.group(0)


@requires_isaac
def test_loop_runs_at_configured_rate_and_time_never_wraps(run_output):
    _, out = run_output
    m = re.search(
        r"\[DRIVE CLOCK\] sim_hz=([\d.]+) wall_hz=([\d.]+) "
        r"monotonic=(\w+) span_s=(-?[\d.]+) updates=\d+", out)
    assert m, out[-2000:]
    sim_hz, wall_hz, monotonic, span_s = m.groups()
    assert float(sim_hz) == pytest.approx(RATE_HZ, rel=RATE_TOLERANCE), m.group(0)
    assert float(wall_hz) > 20.0, m.group(0)
    assert monotonic == "True", m.group(0)
    assert float(span_s) > 1.7, m.group(0)  # Timeline loop period is 1.667 s.
