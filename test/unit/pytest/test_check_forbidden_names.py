"""CLI and hosted workflow contracts for the tracked-file account-name scan."""

import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.core

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = "script/ci/check_forbidden_names.py"


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


def test_clean_tracked_files_pass_despite_base_and_untracked_hits(checkout):
    assert scan(checkout, "fixture-account").returncode == 0


def test_hit_redacts_names_in_filename_and_matched_line(checkout):
    path = checkout / "Fixture-Owner-notes.txt"
    matched_line = "Account recorded as FIXTURE-ACCOUNT"
    path.write_text(matched_line + "\n")
    subprocess.run(["git", "add", "--", path.name], cwd=checkout, check=True)

    result = scan(checkout, "fixture-owner,fixture-account")
    assert result.returncode == 1
    output = (result.stdout + result.stderr).casefold()
    assert "fixture-owner" not in output
    assert "fixture-account" not in output
    assert matched_line.casefold() not in output
    assert path.name.casefold() not in output
    assert re.search(r":1 \(pattern 2\)", result.stdout)


@pytest.mark.parametrize("names", [None, "", " , , "], ids=["unset", "empty", "empty-items"])
def test_missing_names_require_explicit_skip(checkout, names):
    strict = scan(checkout, names)
    assert strict.returncode == 2
    assert "FORBIDDEN_NAMES" in strict.stderr

    optional = scan(checkout, names, "--allow-unset")
    assert optional.returncode == 0
    assert "SKIPPED: FORBIDDEN_NAMES secret not provided" in optional.stdout


def test_skip_explains_why_fork_pull_requests_can_miss_the_secret(checkout):
    result = scan(checkout, None, "--allow-unset")
    assert result.returncode == 0
    assert "SKIPPED" in result.stdout
    assert "secret" in result.stdout
    assert "fork pull request" in result.stdout
    assert "name scan not run" in result.stdout


def test_git_error_is_reported(tmp_path, monkeypatch):
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    result = scan(tmp_path, "fixture-account")
    assert result.returncode == 2
    assert "git" in result.stderr.lower()


def test_checkout_has_no_forbidden_names():
    names = os.environ.get("FORBIDDEN_NAMES", "")
    if not names.strip():
        result = scan(None, None, "--allow-unset")
        assert result.returncode == 0
        assert "SKIPPED: FORBIDDEN_NAMES secret not provided" in result.stdout
        return

    result = scan(None, names)
    assert result.returncode == 0, result.stdout


def test_baseline_script_gives_core_group_git_and_forbidden_names():
    script = (ROOT / "test/assert_pytest_baseline.sh").read_text()
    image = re.search(r'^PY_IMAGE="\$\{PY_IMAGE:-([^}]+)\}"$', script, re.MULTILINE)
    assert image, "Missing PY_IMAGE default"
    assert not image.group(1).endswith(("-slim", "-alpine"))

    # The GPU gate already checks its own JUnit report for skipped tests.
    hosted = script.partition("# default mode: hosted-unit")[2]
    assert "-e FORBIDDEN_NAMES" in hosted
    assert "--junitxml" in hosted
    assert re.search(r"\bskipped\b", hosted)


def test_hosted_core_pytest_reports_each_test_result():
    script = (ROOT / "test/assert_pytest_baseline.sh").read_text()
    hosted = script.partition("# default mode: hosted-unit")[2]
    core = hosted.partition('if [ "${GROUP}" = core ]; then')[2].partition("\n  fi")[0]
    args = re.search(r"^\s*set -- (.+)$", core, re.MULTILINE)
    assert args, "Missing hosted core pytest arguments"
    assert "-rA" in shlex.split(args.group(1), comments=True)


def test_core_unit_hosted_pytest_receives_forbidden_names():
    workflow = yaml.safe_load((ROOT / ".github/workflows/main.yaml").read_text())
    steps = workflow["jobs"]["core-unit"]["steps"]
    hosted = next(
        step for step in steps
        if step.get("name") == "Hosted core-group pytest + group floor + coverage gate"
    )
    assert hosted.get("env", {}).get("FORBIDDEN_NAMES") == "${{ secrets.FORBIDDEN_NAMES }}"


def test_core_unit_runs_forbidden_names_scan_immediately_after_stale_naming():
    workflow = yaml.safe_load((ROOT / ".github/workflows/main.yaml").read_text())
    steps = workflow["jobs"]["core-unit"]["steps"]
    stale = next(i for i, step in enumerate(steps) if step.get("name") == "Stale naming scan")
    assert any(step.get("uses", "").startswith("actions/checkout@") for step in steps[:stale])
    guard = steps[stale + 1]
    assert guard.get("run", "").strip() == f"python3 {SCRIPT} --allow-unset"
    assert guard.get("env", {}).get("FORBIDDEN_NAMES") == "${{ secrets.FORBIDDEN_NAMES }}"
