"""CLI and hosted workflow contracts for the tracked-file account-name scan."""

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.core

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = "script/ci/check_forbidden_names.py"
needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="requires git")


def scan(root, names, *flags):
    assert (ROOT / SCRIPT).is_file(), f"Missing scanner: {SCRIPT}"
    env = os.environ.copy()
    if names is None:
        env.pop("FORBIDDEN_NAMES", None)
    else:
        env["FORBIDDEN_NAMES"] = names
    command = [sys.executable, SCRIPT, *flags]
    if root is not None:
        command.append(str(root))
    return subprocess.run(
        command,
        cwd=ROOT, env=env, capture_output=True, text=True,
    )


@pytest.fixture
def checkout(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "tracked notes.txt").write_text("clean text\n")
    (tmp_path / ".base").mkdir()
    (tmp_path / ".base/ignored.txt").write_text("fixture-account\n")
    subprocess.run(
        ["git", "add", "-f", "--", "tracked notes.txt", ".base/ignored.txt"],
        cwd=tmp_path, check=True,
    )
    (tmp_path / "untracked.txt").write_text("fixture-account\n")
    return tmp_path


@needs_git
@pytest.mark.parametrize("flags", [(), ("--allow-unset",)], ids=["strict", "allow-unset"])
def test_hits_report_only_locations_and_pattern_indices(checkout, flags):
    (checkout / "tracked notes.txt").write_text(
        "clean text\nprivate context FIXTURE-ACCOUNT-isaac\nprivate context /home/Fixture-Owner/work\n"
    )
    result = scan(checkout, " fixture-owner , , Fixture-Account , ", *flags)
    assert result.returncode == 1
    log = (result.stdout + result.stderr).lower()
    for sensitive in ("fixture-owner", "fixture-account", "private context"):
        assert sensitive not in log

    indices = {}
    for hit in result.stdout.splitlines():
        match = re.fullmatch(r"tracked notes\.txt:([23])\b\D+(\d+)\D*", hit)
        assert match, hit
        line, index = map(int, match.groups())
        assert line not in indices
        indices[line] = index
    # Both zero- and one-based indices identify the configured pattern.
    assert indices in ({2: 1, 3: 0}, {2: 2, 3: 1})


@needs_git
def test_clean_tracked_files_pass_despite_base_and_untracked_hits(checkout):
    assert scan(checkout, "fixture-account").returncode == 0


@needs_git
@pytest.mark.parametrize("names", [None, "", " , , "], ids=["unset", "empty", "empty-items"])
def test_missing_names_require_explicit_skip(checkout, names):
    strict = scan(checkout, names)
    assert strict.returncode == 2
    assert "FORBIDDEN_NAMES" in strict.stderr

    optional = scan(checkout, names, "--allow-unset")
    assert optional.returncode == 0
    assert "SKIPPED: FORBIDDEN_NAMES not set" in optional.stdout.splitlines()


@needs_git
def test_git_error_is_reported(tmp_path, monkeypatch):
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    result = scan(tmp_path, "fixture-account")
    assert result.returncode == 2
    assert "git" in result.stderr.lower()


@needs_git
def test_checkout_has_no_forbidden_names():
    names = ",".join(("yun" + "chien", "yu" + "lin"))
    result = scan(None, names)
    assert result.returncode == 0, result.stdout


def test_core_unit_runs_forbidden_names_scan_immediately_after_stale_naming():
    workflow = yaml.safe_load((ROOT / ".github/workflows/main.yaml").read_text())
    steps = workflow["jobs"]["core-unit"]["steps"]
    stale = next(i for i, step in enumerate(steps) if step.get("name") == "Stale naming scan")
    assert any(step.get("uses", "").startswith("actions/checkout@") for step in steps[:stale])
    guard = steps[stale + 1]
    assert guard.get("run", "").strip() == f"python3 {SCRIPT} --allow-unset"
    assert guard.get("env", {}).get("FORBIDDEN_NAMES") == "${{ vars.FORBIDDEN_NAMES }}"
