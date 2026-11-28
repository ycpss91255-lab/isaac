"""Headless GPU smoke test for the standalone custom RGB-D camera setup."""

import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

pytestmark = pytest.mark.core

REPO_ROOT = Path(__file__).resolve().parents[3]
RUNNER_SCRIPT = Path(__file__).parent / "_camera_headless_runner.py"
SRC_DIR = REPO_ROOT / "src"
SCRIPT_DIR = SRC_DIR / "script"
CAMERA_YAML = SRC_DIR / "config" / "camera" / "custom.yaml"
PYTHON_SH = "/isaac-sim/python.sh"

SUBPROC_TIMEOUT_SEC = 900


def _write_stub_usd(tmp_path: Path) -> Path:
    """Create a stage containing the mount parent from custom.yaml."""
    p = tmp_path / "camera_smoke_stub.usda"
    p.write_text(
        textwrap.dedent("""\
            #usda 1.0
            (
                upAxis = "Z"
                metersPerUnit = 1.0
            )

            def Xform "World"
            {
                def Xform "Forklift"
                {
                    def Xform "carriage"
                    {
                    }
                }
            }
            """),
        encoding="utf-8",
    )
    return p


def _dump_output(result):
    sys.stderr.write(
        "\n--- camera_headless stdout ---\n" + result.stdout
        + "\n--- camera_headless stderr ---\n" + result.stderr
    )


def test_camera_custom_yaml_creates_prims_headless(tmp_path):
    stub_usd = _write_stub_usd(tmp_path)

    result = subprocess.run(
        [
            PYTHON_SH, str(RUNNER_SCRIPT),
            "--script-dir", str(SCRIPT_DIR),
            "--camera-yaml", str(CAMERA_YAML),
            "--usd-path", str(stub_usd),
        ],
        capture_output=True,
        text=True,
        timeout=SUBPROC_TIMEOUT_SEC,
    )

    ok = all(
        marker in result.stdout
        for marker in ("[BOOT OK]", "[CAMERA PRIM]", "[EXIT CLEAN]")
    )
    if not ok or "[RAISED]" in result.stdout:
        _dump_output(result)

    # 1. Headless Isaac actually boots.
    assert "[BOOT OK]" in result.stdout, "Kit never reached the boot marker."

    # CUDA functional check (libcuda cuInit + device count, printed by
    # the runner from inside the booted Kit process).
    cuda = re.search(r"\[CUDA OK\] devices=(\d+)", result.stdout)
    assert cuda, "CUDA init marker missing."
    assert int(cuda.group(1)) >= 1, "CUDA reported zero devices."

    # CUDA/Vulkan init markers in the Kit log (Info-level boot lines).
    # The path contains spaces ("Kit/Isaac-Sim Python/..."), so match to
    # end of line rather than \S+.
    kit_log = re.search(r"\[KIT LOG\] path=(.+)", result.stdout)
    assert kit_log, "Runner did not announce the Kit log path."
    log_text = Path(kit_log.group(1).strip()).read_text(
        encoding="utf-8", errors="replace"
    )
    assert "vulkan" in log_text.lower(), "No Vulkan init marker in Kit log."
    assert "cuda" in log_text.lower(), "No CUDA init marker in Kit log."

    cameras = re.findall(r"^\[CAMERA PRIM\] (\S+)$", result.stdout, re.MULTILINE)
    assert len(cameras) == 2
    assert all(path.startswith("/World/Forklift/carriage/") for path in cameras)
    assert {Path(path).name for path in cameras} == {"color", "depth"}

    assert "[EXIT CLEAN]" in result.stdout, "Runner did not exit cleanly."
    assert "[RAISED]" not in result.stdout, (
        "Runner raised inside the lifecycle. " + result.stdout[-1000:]
    )
