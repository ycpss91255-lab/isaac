"""Hosted checks for the USD-only model boundary (isaac#477)."""

import os
import re
import shutil
import subprocess
import sys
from importlib import import_module
from pathlib import Path

import pytest

pytestmark = pytest.mark.core

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "framework"))

OLD_IMPORT = "import_" + "urdf"
FORBIDDEN = re.compile("|".join((
    "Urdf" + "Converter", "xa" + "cro", OLD_IMPORT,
    "import-" + "model", "_preprocess_" + "urdf",
)).encode(), re.IGNORECASE)


def _source_paths():
    if shutil.which("git"):
        names = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT)
        yield from (Path(os.fsdecode(name)) for name in names.split(b"\0") if name)
    else:
        # Hosted pytest mounts a clean checkout in python:slim without Git.
        for directory, dirs, files in os.walk(ROOT):
            dirs[:] = [d for d in dirs if d not in {
                ".git", ".base", "adr", "__pycache__", ".pytest_cache",
            }]
            yield from (Path(directory, f).relative_to(ROOT) for f in files)


def test_no_conversion_references():
    matches = []
    for relative in _source_paths():
        if {".git", ".base", "adr"}.intersection(relative.parts) or relative.name == "CHANGELOG.md":
            continue
        path = ROOT / relative
        if path == Path(__file__).resolve() or path.is_symlink() or not path.is_file():
            continue
        if FORBIDDEN.search(path.read_bytes()):
            matches.append(str(relative))
    assert not matches, "\n".join(matches)


@pytest.mark.parametrize("relative", [
    "test/fixtures/urdf", f"src/script/{OLD_IMPORT}.py", "src/script/import_model.py",
])
def test_conversion_paths_removed(relative):
    assert not os.path.lexists(ROOT / relative)


def test_package_drops_conversion_entry_point():
    import isaac_devkit

    assert not hasattr(isaac_devkit, OLD_IMPORT)


def test_usd_helpers_remain_importable():
    import isaac_devkit
    from isaac_devkit import PrimSummary, scene

    modules = (isaac_devkit, scene, import_module(PrimSummary.__module__))
    assert any(callable(getattr(module, "apply_joint_drive", None)) for module in modules)
