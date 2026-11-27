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


def test_no_ros_integration_layout():
    pytest_dir = REPO_ROOT / INTEGRATION_DIR
    no_ros = pytest_dir.with_name("no_ros")
    assert no_ros.is_dir()
    readme = no_ros / "README.md"
    assert readme.is_file()
    description = " ".join(readme.read_text(encoding="utf-8").lower().split())
    assert "isaac" in description
    assert re.search(
        r"\b(?:loads no|(?:does not load|never loads)(?: any)?) ros modules?\b", description
    )
    assert (no_ros / "conftest.py").is_file()
    for name in ("test_io_plugin_integration.py", "_io_plugin_runner.py", "_io_plugin_marker.py"):
        assert (no_ros / name).is_file()
        assert not os.path.lexists(pytest_dir / name)


def test_integration_files_outside_no_ros_have_no_ros_references():
    integration = REPO_ROOT / INTEGRATION_DIR.parent
    no_ros = integration / "no_ros"
    pattern = re.compile(rb"rclpy|ros2")
    matches = sorted(
        path.relative_to(REPO_ROOT)
        for path in integration.rglob("*")
        if no_ros not in path.parents and path.is_file() and pattern.search(path.read_bytes())
    )
    assert matches == []


def test_cross_subnet_adr_points_to_ros_io():
    adr = REPO_ROOT / "src/doc/adr/0015-cross-subnet-ros2-viewing-tcp-dds.md"
    assert adr.is_file()
    assert "isaac_ros_io" in adr.read_text(encoding="utf-8")


def test_baseline_has_no_cross_container_leg():
    baseline = REPO_ROOT / "test/assert_pytest_baseline.sh"
    assert "XC_PYTEST" not in baseline.read_text(encoding="utf-8")


def _doc_files_containing(needle):
    doc_dir = REPO_ROOT / "src/doc"
    return sorted(
        path.relative_to(doc_dir)
        for path in doc_dir.rglob("*")
        if path.is_file() and needle in path.read_bytes()
    )


def test_action_graph_clients_do_not_mount_the_fastdds_profile():
    guide = Path("action_graph_setup.md")
    text = (REPO_ROOT / "src/doc" / guide).read_text(encoding="utf-8")
    commands = [
        block for block in re.findall(r"```bash\n(.*?)```", text, re.S)
        if "ros:humble" in block
    ]
    assert len(commands) == 2
    for cmd in commands:
        assert "config/ros2/fastdds.xml" not in cmd
        assert "FASTRTPS_DEFAULT_PROFILES_FILE" not in cmd
    assert "此 checkout 的 fast dds 設定檔" not in text.casefold()
    assert _doc_files_containing(b"FASTRTPS_DEFAULT_PROFILES_FILE") == []


def test_adr_0025_fastdds_note():
    adr = Path("adr/0025-output-mode-ros-or-python.md")
    lines = (REPO_ROOT / "src/doc" / adr).read_text(encoding="utf-8").splitlines()
    original = "the UDPv4-only Fast DDS profile (`config/ros2/fastdds.xml`, #367)."
    original_line = next((i for i, line in enumerate(lines) if original in line), None)
    assert original_line is not None, original
    required = ("test/fixtures/ros2/fastdds.xml", "isaac_ros_io", "ADR-0015")
    assert any(all(term in line for term in required) for line in lines[original_line + 1:])
    assert _doc_files_containing(b"config/ros2/fastdds.xml") == [adr]


def test_acceptance_doc_has_no_cmd_vel_coverage():
    acceptance = (REPO_ROOT / "doc/v1.0.0-rc1-acceptance.md").read_text(encoding="utf-8")
    assert "cmd_vel" not in acceptance
    assert "camera topic + `frame_id`" not in acceptance
    assert "test_l3_camera_prim_exists" in acceptance


def test_adr_0005_0024_original_text_kept():
    adr_dir = REPO_ROOT / "src/doc/adr"
    adr_0005, = adr_dir.glob("0005-*.md")
    adr_0024, = adr_dir.glob("0024-*.md")
    original = (
        "the legacy `doc/cmd_vel_inkit_teleop.md` and `doc/action_graph_setup.md` SOPs "
        "are kept as historical reference but flagged as superseded at the top of each file."
    )
    assert original in adr_0005.read_text(encoding="utf-8")
    text = adr_0024.read_text(encoding="utf-8")
    assert "**Integration tests unchanged.**" in text
    assert "test_camera_ros2_headless.py" in text
