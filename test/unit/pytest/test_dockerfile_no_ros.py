"""Host-side checks for removing ROS configuration from the image (isaac#430)."""

import os
import re
import runpy
import shutil
import tomllib
from pathlib import Path

import pytest

pytestmark = pytest.mark.core

REPO_ROOT = Path(__file__).resolve().parents[3]
DOCKERFILE = REPO_ROOT / "Dockerfile"
ROS_TERMS = re.compile(r"ROS_DISTRO|fastdds|isaacsim\.ros2|isaac-ros-env")


def test_image_inputs_have_no_ros_configuration_references():
    paths = [DOCKERFILE]
    for directory in ("script", "config"):
        paths.extend(sorted((REPO_ROOT / directory).rglob("*")))

    hits = []
    for path in paths:
        if path.is_symlink() or not path.is_file():
            continue
        data = path.read_bytes()
        if b"\0" in data:
            continue
        lines = data.decode("utf-8", errors="surrogateescape").splitlines()
        for number, line in enumerate(lines, 1):
            if ROS_TERMS.search(line):
                hits.append(f"{path.relative_to(REPO_ROOT)}:{number}: {line}")
    assert not hits, "\n".join(hits)


def test_setup_toml_has_no_ros_environment():
    with (REPO_ROOT / "setup.toml").open("rb") as source:
        setup = tomllib.load(source)

    pattern = re.compile(r"ROS|RMW|FASTRTPS")
    hits = []
    for arg in setup.get("build", {}).get("args", []):
        if pattern.search(arg["key"]):
            hits.append(f"build.args key: {arg['key']}")
    for key, value in setup.get("environment", {}).items():
        if pattern.search(key) or pattern.search(str(value)):
            hits.append(f"environment.{key} = {value!r}")
    assert not hits, "\n".join(hits)


def test_obsolete_ros_files_are_removed():
    obsolete = (
        "script/isaac-ros-env-wrapper.sh",
        "config/ros2/fastdds.xml",
        "test/bats/smoke/isaac_ros_env_wrapper.bats",
    )
    remaining = [name for name in obsolete if os.path.lexists(REPO_ROOT / name)]
    assert not remaining, remaining


def test_dockerfile_instructions_have_no_ros_setup_or_entrypoint_wrapper():
    lines = DOCKERFILE.read_text().splitlines()
    active = "\n".join(line for line in lines if not line.lstrip().startswith("#"))
    instructions = active.replace("\\\n", "").splitlines()
    hits = []
    for line in instructions:
        words = line.split(maxsplit=1)
        if len(words) != 2:
            continue
        directive, args = words
        if directive.upper() in {"COPY", "ENV", "ARG", "ENTRYPOINT"} and (
            ROS_TERMS.search(args) or "FASTRTPS_DEFAULT_PROFILES_FILE" in args
        ):
            hits.append(line)
        elif "/etc/isaac/ros-distro" in args:
            hits.append(line)
    assert not hits, "\n".join(hits)


def test_cross_container_roundtrip_uses_test_fastdds_profile(monkeypatch):
    test_dir = REPO_ROOT / "test"
    fixture = test_dir / "fixtures" / "ros2" / "fastdds.xml"
    assert fixture.is_file()

    # The integration module checks for Docker while defining its skip marker.
    monkeypatch.setattr(shutil, "which", lambda name: None)
    monkeypatch.syspath_prepend(str(test_dir))
    roundtrip = test_dir / "integration/pytest/test_cross_container_roundtrip.py"
    module = runpy.run_path(str(roundtrip))
    assert module["FASTDDS_PROFILE"] == fixture
