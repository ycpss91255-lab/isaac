"""Hosted checks for the removal of the ROS scripts and cross-container tests (#429)."""

import os
import re
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.core

REPO_ROOT = Path(__file__).resolve().parents[3]
INTEGRATION_DIR = Path("test/integration/pytest")
REMOVED_MODULES = (
    "test_camera_ros2_headless",
    "test_cross_container_roundtrip",
    "_cross_container_runner",
    "_camera_headless_runner",
)


@pytest.mark.parametrize(
    "path",
    [
        "src/script/ros2_" + "test_pub.py",
        "src/script/ros2_" + "test_pub_standalone.py",
        "src/script/ros2_" + "test_sub.py",
        "src/script/ros2_" + "test_sub_standalone.py",
        "src/script/view_isaac_" + "bag.sh",
        "src/script/view_isaac_" + "camera.sh",
        "src/doc/ros2_pubsub_smoke.md",
        "src/doc/cmd_vel_inkit_teleop.md",
        "src/config/ros2/fastdds_tcp_client.xml",
        "src/config/ros2/fastdds_tcp_server.xml",
        *(str(INTEGRATION_DIR / f"{name}.py") for name in REMOVED_MODULES),
        "test/unit/pytest/test_xc_roundtrip_asset_migration.py",
        "test/unit/pytest/test_xc_compose_project_isolation.py",
    ],
)
def test_ros_file_removed(path):
    assert not os.path.lexists(REPO_ROOT / path)


def _repo_files():
    try:
        names = subprocess.check_output(
            ["git", "ls-files", "-z"], cwd=REPO_ROOT, stderr=subprocess.PIPE
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        # Hosted source copies may lack Git or worktree metadata.
        for directory, dirs, files in os.walk(REPO_ROOT):
            parent = Path(directory)
            dirs[:] = [
                d for d in dirs
                if d not in {".git", "__pycache__"}
                and parent / d != REPO_ROOT / "doc/changelog"
            ]
            yield from (parent / name for name in files if name != ".git")
    else:
        yield from (REPO_ROOT / os.fsdecode(name) for name in names.split(b"\0") if name)


def test_no_removed_script_references():
    pattern = re.compile(rb"ros2_" + rb"test_|view_isaac_" + rb"(bag|camera)")
    changelog = REPO_ROOT / "doc/changelog"
    matches = [
        path.relative_to(REPO_ROOT)
        for path in _repo_files()
        if changelog not in path.parents
        and path.is_file() and pattern.search(path.read_bytes())
    ]
    assert matches == []


def test_integration_files_have_no_removed_module_references():
    for path in (REPO_ROOT / INTEGRATION_DIR).rglob("*"):
        if path.is_file():
            content = path.read_bytes()
            for name in REMOVED_MODULES:
                assert name.encode() not in content, f"{path.relative_to(REPO_ROOT)}: {name}"


def test_cross_subnet_adr_points_to_ros_io():
    adr = REPO_ROOT / "src/doc/adr/0015-cross-subnet-ros2-viewing-tcp-dds.md"
    assert adr.is_file()
    assert "isaac_ros_io" in adr.read_text(encoding="utf-8")


def test_baseline_has_no_cross_container_leg():
    baseline = REPO_ROOT / "test/assert_pytest_baseline.sh"
    assert "XC_PYTEST" not in baseline.read_text(encoding="utf-8")
