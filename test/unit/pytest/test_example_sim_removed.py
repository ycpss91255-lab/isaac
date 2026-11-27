"""Guard against reintroducing the bundled Isaac simulation example (#327)."""

import os
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.core

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_example_sim_removed():
    example = Path("example") / "sim"
    problems = []
    if (REPO_ROOT / example).exists():
        problems.append(f"{example} still exists")

    driver_import = re.compile(r"(?:^|[;\s])(?:from|import)\s+(?:[.\w]+\.)?example_driver\b")
    example_path = example.as_posix()
    this_test = Path(__file__).resolve()
    skip_dirs = {".git", ".base", "node_modules", "__pycache__"}
    for root, dirs, files in os.walk(REPO_ROOT):
        dirs[:] = sorted(name for name in dirs if name not in skip_dirs)
        for name in sorted(files):
            path = Path(root) / name
            if name in {".git", "CHANGELOG.md"} or path == this_test:
                continue
            relative = path.relative_to(REPO_ROOT)
            if relative.parent == Path("doc") and relative.match("PRD*.draft.md"):
                continue
            if path.is_symlink() or not path.is_file():
                continue
            data = path.read_bytes()
            if b"\x00" in data:
                continue
            try:
                lines = data.decode("utf-8").splitlines()
            except UnicodeDecodeError:
                continue
            for number, line in enumerate(lines, start=1):
                if example_path in line or driver_import.search(line):
                    problems.append(f"{relative}:{number}:{line}")

    assert not problems, "\n" + "\n".join(problems)
