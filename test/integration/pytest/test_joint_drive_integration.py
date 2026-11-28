"""GPU integration for runtime drive gains on a USD revolute joint."""

import math
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.core

REPO_ROOT = Path(__file__).resolve().parents[3]
FRAMEWORK_DIR = REPO_ROOT / "framework"
RUNNER = Path(__file__).parent / "_joint_drive_runner.py"
PYTHON_SH = "/isaac-sim/python.sh"
RUN_TIMEOUT_SEC = 240

# Core Experimental scales angular gains by pi/180 when writing the DriveAPI.
STIFFNESS = 800.0
DAMPING = 40.0
_DEG2RAD = math.pi / 180.0
# Expected per-radian gains the angular DriveAPI actually stores.
EXPECTED_STIFFNESS = STIFFNESS * _DEG2RAD
EXPECTED_DAMPING = DAMPING * _DEG2RAD
# Float tolerance: the marker prints with %g (6 sig figs), so compare with a
# relative tolerance rather than exact equality.
_REL_TOL = 1e-4

_SUMMARY_RE = re.compile(
    r"\[DRIVE SUMMARY\] joint=(\S+) has_drive=(\S+) "
    r"stiffness=(\S+) damping=(\S+)"
)


def test_runtime_apply_joint_drive_sets_driveapi():
    """Read the authored angular drive back from the stage."""
    env = dict(os.environ)
    env["PYTHONPATH"] = (
        str(FRAMEWORK_DIR) + os.pathsep + env.get("PYTHONPATH", "")
    )
    result = subprocess.run(
        [
            PYTHON_SH, str(RUNNER),
            "--repo-root", str(REPO_ROOT),
            "--stiffness", str(STIFFNESS),
            "--damping", str(DAMPING),
        ],
        capture_output=True,
        text=True,
        timeout=RUN_TIMEOUT_SEC,
        env=env,
    )
    if result.returncode != 0 or "[DRIVE SUMMARY]" not in result.stdout:
        sys.stderr.write(
            f"\n--- joint-drive runner stdout ---\n{result.stdout}\n"
            f"--- stderr ---\n{result.stderr}\n"
        )
    m = _SUMMARY_RE.search(result.stdout)
    assert m, "no [DRIVE SUMMARY] marker"
    assert m.group(2) == "True", result.stdout
    assert math.isclose(float(m.group(3)), EXPECTED_STIFFNESS, rel_tol=_REL_TOL)
    assert math.isclose(float(m.group(4)), EXPECTED_DAMPING, rel_tol=_REL_TOL)
