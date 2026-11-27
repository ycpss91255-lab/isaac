"""Hosted checks for the framework's lint and coverage configuration."""

import tomllib
from pathlib import Path

import pytest

pytestmark = pytest.mark.core

_CONFIG = Path(__file__).resolve().parents[3] / "framework" / "pyproject.toml"


@pytest.fixture
def framework_tools():
    with _CONFIG.open("rb") as config:
        return tomllib.load(config)["tool"]


def test_banned_module_level_imports(framework_tools):
    tidy_imports = framework_tools["ruff"]["lint"]["flake8-tidy-imports"]
    assert tidy_imports["banned-module-level-imports"] == ["omni", "pxr", "isaacsim"]


def test_hosted_scene_functions_count_toward_coverage(framework_tools):
    excluded = framework_tools["coverage"]["report"]["exclude_also"]
    hosted = {r"def _set_physics_properties\(", r"def apply_joint_drive\("}
    assert not hosted.intersection(excluded)
