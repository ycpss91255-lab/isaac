"""GPU integration checks for the headless Jetbot example (#132, #325).

The runner builds a scene from the official Jetbot USD and mounts a custom
camera on its chassis. The tests check the live robot structure, camera
mount, CUDA and Vulkan initialization, loaded modules, and SIGINT shutdown.
Kit can exit directly in app.close(), so the tests read the runner's stdout
markers. The fixture allows one logged retry within the GPU CI policy.

Run inside the GPU-enabled test container (requires the
``[stage:devel-test] deploy.gpu_mode = force`` setup.conf override)::

    ./script/run.sh -t test -- /isaac-sim/python.sh -m pytest \
        <repo>/test/integration/pytest/test_example_gpu_integration.py -s
"""

import re
import subprocess
import sys
from pathlib import Path

import pytest

# ``test/`` hosts the shared asset helper (#341); make it importable.
_TEST_DIR = Path(__file__).resolve().parents[2]
if str(_TEST_DIR) not in sys.path:
    sys.path.insert(0, str(_TEST_DIR))

from test_assets import fetch_test_asset  # noqa: E402

pytestmark = pytest.mark.core

REPO_ROOT = Path(__file__).resolve().parents[3]
RUNNER_SCRIPT = Path(__file__).parent / "_example_headless_runner.py"
PYTHON_SH = "/isaac-sim/python.sh"

# Allow for Kit startup and shader compilation on a cold cache.
BOOT_BUDGET_SEC = 400
SUBPROC_TIMEOUT_SEC = int(BOOT_BUDGET_SEC * 1.5)

# GPU CI policy: retry at most once, logged.
MAX_RETRIES = 1

# The Jetbot chassis is its articulation body.
EXPECTED_BASE_LINK = "/World/Robot/chassis"

# Jetbot USD structure (pxr inspection of the pinned asset, defaultPrim
# /jetbot): three rigid-body Xform links directly under the root (chassis,
# left_wheel, right_wheel) and two PhysicsRevoluteJoints (the wheel
# joints). Counted by the same ``_summarize_prim_records`` rule the L1
# runner uses (Xform children of the root / types containing "Joint").
EXPECTED_LINK_COUNT = 3
EXPECTED_JOINT_COUNT = 2
EXPECTED_ROBOT_ROOT_PRIM_NAME = "/jetbot"


def _run_once(robot_usd):
    """Run the headless example runner once; return CompletedProcess."""
    return subprocess.run(
        [
            PYTHON_SH,
            str(RUNNER_SCRIPT),
            "--repo-root",
            str(REPO_ROOT),
            "--robot-usd",
            str(robot_usd),
        ],
        capture_output=True,
        text=True,
        timeout=SUBPROC_TIMEOUT_SEC,
    )


def _boot_succeeded(result) -> bool:
    """Did the runner reach a clean lifecycle exit without raising?"""
    return (
        result is not None
        and "[BOOT OK]" in result.stdout
        and "[EXIT CLEAN]" in result.stdout
        and "[RAISED]" not in result.stdout
    )


def _run_with_retry(robot_usd):
    """Run headless with retry <= 1, logging each attempt (GPU CI policy)."""
    result = None
    for attempt in range(MAX_RETRIES + 1):
        sys.stderr.write(
            f"\n[example-gpu-integration] attempt "
            f"{attempt + 1}/{MAX_RETRIES + 1} "
            f"(timeout={SUBPROC_TIMEOUT_SEC}s)\n"
        )
        try:
            result = _run_once(robot_usd)
        except subprocess.TimeoutExpired:
            sys.stderr.write(
                f"[example-gpu-integration] attempt {attempt + 1} timed out "
                f"after {SUBPROC_TIMEOUT_SEC}s\n"
            )
            result = None
            continue
        if _boot_succeeded(result):
            sys.stderr.write(
                f"[example-gpu-integration] attempt {attempt + 1} booted "
                f"clean\n"
            )
            return result
        sys.stderr.write(
            f"[example-gpu-integration] attempt {attempt + 1} did not boot "
            f"clean; retrying if budget remains\n"
        )
    return result


def _dump(result) -> None:
    if result is None:
        sys.stderr.write(
            "\n--- example_gpu stdout --- (no result: timed out)\n"
        )
        return
    sys.stderr.write(
        "\n--- example_gpu stdout ---\n" + result.stdout
        + "\n--- example_gpu stderr ---\n" + result.stderr
    )


@pytest.fixture(scope="module")
def example_run():
    """Boot the Jetbot scene headless once (module-scoped, retry<=1)."""
    robot_usd = fetch_test_asset("jetbot")
    result = _run_with_retry(robot_usd)
    if not _boot_succeeded(result):
        _dump(result)
        pytest.fail(
            "example headless runner did not boot clean within the GPU CI "
            "budget (timeout / retry exhausted)."
        )
    return result


def test_l4_boot_and_clean_exit_markers(example_run):
    """L4: [BOOT OK] + [EXIT CLEAN] present, nothing raised."""
    out = example_run.stdout
    assert "[BOOT OK]" in out, "Kit never reached the boot marker."
    assert "[EXIT CLEAN]" in out, "Runner did not exit cleanly."
    assert "[RAISED]" not in out, (
        "Runner raised inside the lifecycle. " + out[-1000:]
    )


def test_cuda_and_vulkan_init(example_run):
    """GPU actually initialized: libcuda device count + Kit log markers."""
    out = example_run.stdout
    cuda = re.search(r"\[CUDA OK\] devices=(\d+)", out)
    assert cuda, "CUDA init marker missing."
    assert int(cuda.group(1)) >= 1, "CUDA reported zero devices."

    kit_log = re.search(r"\[KIT LOG\] path=(.+)", out)
    assert kit_log, "Runner did not announce the Kit log path."
    log_text = Path(kit_log.group(1).strip()).read_text(
        encoding="utf-8", errors="replace"
    )
    assert "vulkan" in log_text.lower(), "No Vulkan init marker in Kit log."
    assert "cuda" in log_text.lower(), "No CUDA init marker in Kit log."


def test_l1_base_link_valid_and_rigidbody(example_run):
    """L1: base_link IsValid + RigidBodyAPI present at the expected path."""
    out = example_run.stdout
    m = re.search(
        r"\[L1 BASE_LINK OK\] path=(\S+) valid=(\S+) rigidbody=(\S+)", out
    )
    assert m, "L1 base_link marker missing."
    assert m.group(1) == EXPECTED_BASE_LINK, (
        f"base_link path mismatch: got {m.group(1)!r}, "
        f"expected {EXPECTED_BASE_LINK!r}"
    )
    assert m.group(2) == "True", "base_link is not IsValid on the live stage."
    assert m.group(3) == "True", "base_link is missing RigidBodyAPI."


def test_l1_link_and_joint_counts(example_run):
    """L1: live Jetbot link/joint counts match the asset's structure."""
    out = example_run.stdout
    m = re.search(
        r"\[L1 COUNTS OK\] links=(\d+) joints=(\d+) root=(\S+)", out
    )
    assert m, "L1 counts marker missing."
    assert int(m.group(1)) == EXPECTED_LINK_COUNT, (
        f"link count mismatch: got {m.group(1)}, expected "
        f"{EXPECTED_LINK_COUNT}"
    )
    assert int(m.group(2)) == EXPECTED_JOINT_COUNT, (
        f"joint count mismatch: got {m.group(2)}, expected "
        f"{EXPECTED_JOINT_COUNT}"
    )
    assert m.group(3) == EXPECTED_ROBOT_ROOT_PRIM_NAME, (
        f"robot root mismatch: got {m.group(3)!r}, "
        f"expected {EXPECTED_ROBOT_ROOT_PRIM_NAME!r}"
    )


# test_l1_urdf_to_usd_diff_zero RETIRED (#154, ADR-0018 decision 6).
#
# It re-imported camera_bot.urdf and asserted a byte/structure diff == 0
# against the COMMITTED camera_bot.usd (since replaced by the official
# Jetbot asset, #325). The committed USD is a curated
# legacy-importer asset (a defaultPrim was added in fb6f580 so the
# UsdFileCfg reference resolves, but the asset was NOT regenerated by the
# new Isaac Lab instanceable importer), so a fresh-import vs committed
# diff is non-zero BY CONSTRUCTION and regenerating the committed asset is
# an out-of-band GPU step the example rework deliberately does not take.
#
# The "a fresh import is structurally correct" contract is already covered
# by test_model_import.py (the openbase single-USD import, #150). The L1
# structure of the live committed USD is still asserted here by
# test_l1_link_and_joint_counts (3 links / 2 joints / root /jetbot) and
# test_l1_base_link_valid_and_rigidbody. The collected GPU baseline drops
# by 1 (the retired test) -- a documented ratchet exception, recorded in
# test/pytest-baseline.txt and the PR body.


def test_l3_camera_prim_exists(example_run):
    mount_path = f"{EXPECTED_BASE_LINK}/custom_mount"
    assert f"[CAMERA PRIM OK] path={mount_path} valid=True" in example_run.stdout


def test_no_ros_modules_loaded(example_run):
    assert "[ROS_MODULES] []" in example_run.stdout


def test_l4_injected_sigint_runs_shutdown(example_run):
    """L4: an injected SIGINT still runs shutdown() in the live driver."""
    out = example_run.stdout
    assert "[SIGINT SHUTDOWN OK]" in out, (
        "Injected SIGINT did not reach shutdown() (the live-driver leg of "
        "the lifecycle-order assertion; the pure-side ORDER spy is in "
        "hosted unit suite)."
    )
