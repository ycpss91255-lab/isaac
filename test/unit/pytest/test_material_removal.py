"""Hosted guards for asset-owned materials (#567)."""

import os
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.core

ROOT = Path(__file__).resolve().parents[3]
SHIM = "material" + "_setup"


@pytest.mark.parametrize("path", [
    Path("framework/isaac_devkit") / "materials.py",
    Path("src/script") / f"{SHIM}.py",
    Path("test/unit/pytest") / f"test_{SHIM}.py",
])
def test_material_module_removed(path):
    assert not os.path.lexists(ROOT / path), path


def test_no_references_to_removed_material_modules():
    terms = [
        r"isaac_devkit[.]materials", r"from +isaac_devkit +import +materials",
        "material_cfg" + "_from_yaml", "load_material" + "_config", SHIM,
    ]
    result = subprocess.run(
        ["git", "grep", "-nIE", "|".join(terms), "--", ".",
         ":!doc/changelog/CHANGELOG.md", ":!src/doc/adr"],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert result.returncode == 1, result.stderr or result.stdout


def test_scene_does_not_construct_or_bind_visual_materials():
    source = (ROOT / "framework/isaac_devkit/scene.py").read_text()
    for term in ("_material_diffuse_for", "PreviewSurfaceMaterial", "apply_visual_materials"):
        assert term not in source, term
