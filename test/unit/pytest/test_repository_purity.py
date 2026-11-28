"""Regression checks for removing forklift content from the repository (#136)."""

import os
import re
import subprocess
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.core

ROOT = Path(__file__).resolve().parents[3]
TERMS = re.compile(r"forklift|modela", re.IGNORECASE)
ALLOWED_FILES = {
    Path("doc/changelog/CHANGELOG.md"),
    Path("doc/PRD-template-convergence.draft.md"),
    Path("script/ci/check_framework_purity.sh"),
    Path("test/unit/pytest/test_framework_purity.py"),
    Path(__file__).resolve().relative_to(ROOT),
}


def repository_files():
    if (ROOT / ".git").exists():
        names = subprocess.check_output(
            ["git", "ls-files", "-z", "--", ".", ":!.base"], cwd=ROOT
        )
        for name in names.split(b"\0"):
            if name:
                yield Path(os.fsdecode(name))
        return

    for directory, subdirs, names in os.walk(ROOT):
        relative = Path(directory).relative_to(ROOT)
        if relative == Path("."):
            subdirs[:] = [name for name in subdirs if name not in {".base"}]
        for name in names:
            yield relative / name


def test_repository_has_no_forklift_content():
    matches = []
    for relative in repository_files():
        path = ROOT / relative
        if relative in ALLOWED_FILES or path.is_symlink() or not path.is_file():
            continue
        data = path.read_bytes()
        if b"\0" in data:
            continue
        for number, line in enumerate(data.decode("utf-8", errors="replace").split("\n"), 1):
            if not TERMS.search(line):
                continue
            if relative == Path("doc/test/TEST.md") and (
                line == "case-insensitive matches of `forklift|coresam|pallet|pushback|openbase`."
                or line.startswith("| `test_repository_purity.py` |")
            ):
                continue
            matches.append(f"{relative}:{number}")
    assert not matches, "\n" + "\n".join(matches)


def test_default_camera_mounts_and_topics_are_generic():
    configs = sorted((ROOT / "src/config/camera").glob("*.yaml"))
    assert configs, "No default camera configs found"
    matches = []
    for path in configs:
        config = yaml.safe_load(path.read_text())
        for section, key in (("mount", "parent_prim"), ("ros", "topic_prefix")):
            value = config.get(section, {}).get(key, "")
            if "forklift" in value.casefold():
                matches.append(f"{path.relative_to(ROOT)}: {section}.{key} = {value}")
    assert not matches, "\n" + "\n".join(matches)
