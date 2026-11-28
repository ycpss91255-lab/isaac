"""Regression tests for the Dockerfile recursive chown check and its CI step."""

import importlib.util
from pathlib import Path
import subprocess
import sys

import pytest
import yaml

pytestmark = pytest.mark.core

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = "script/ci/check_no_recursive_chown.py"


@pytest.fixture(scope="module")
def checker():
    spec = importlib.util.spec_from_file_location("check_no_recursive_chown", ROOT / SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("command", [
    "chown u /isaac-sim -R",
    'chown -R u:g "${ISAAC_ROOT}"',
    "chown -R u /opt",
    "chown -R u:g /",
    "find /isaac-sim -exec chown u {} +",
    "chown -R u:g /isaac-sim",
    "chown --recursive u:g /isaac-sim",
    "chown -hR u:g /isaac-sim",
    "chown -Rh u:g /isaac-sim",
    "chown -R u:g \\\n    /isaac-sim",
    "chown -R u:g ${HOME}/.cache /opt",
    "chown -R u:g ${HOME}/../isaac-sim",
    "chown -R u:g ${HOME}",
    "chown -R --reference=/etc/passwd /opt $HOME/.cache",
    "find /isaac-sim -execdir chown u {} +",
    "find /isaac-sim -type f | xargs chown u",
])
def test_reports_unsafe_chown(checker, command):
    assert checker.violations(f"RUN {command}\n")


@pytest.mark.parametrize("line", [
    "RUN chown -R u:g ${HOME}/.cache",
    'RUN chown -R --reference=/etc/passwd "$HOME/.cache"',
    "RUN chown u:g /etc/isaac",
    "  # RUN chown -R u:g /isaac-sim",
    "RUN find ${HOME}/.cache -exec chown u {} +",
    "RUN find $HOME/.cache -execdir chown u {} +",
    "RUN find ${HOME}/.cache -type f | xargs chown u",
])
def test_accepts_safe_lines(checker, line):
    assert checker.violations(line + "\n") == []


def test_accepts_repo_dockerfile(checker):
    assert checker.violations((ROOT / "Dockerfile").read_text(encoding="utf-8")) == []


@pytest.mark.parametrize(("command", "expected_code"), [
    ("chown u /isaac-sim -R", 1),
    ("chown -R u:g ${HOME}/.cache", 0),
])
def test_cli_checks_supplied_dockerfile(tmp_path, command, expected_code):
    dockerfile = tmp_path / "Dockerfile.test"
    dockerfile.write_text(f"RUN {command}\n", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, ROOT / SCRIPT, dockerfile],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == expected_code, result.stderr
    if expected_code == 1:
        assert command in result.stdout + result.stderr


def test_core_unit_runs_recursive_chown_check():
    workflow = yaml.safe_load((ROOT / ".github/workflows/main.yaml").read_text())
    steps = workflow["jobs"]["core-unit"]["steps"]
    assert any(
        line.split() in (["python3", SCRIPT], ["python3", SCRIPT, "Dockerfile"])
        for step in steps
        for line in step.get("run", "").splitlines()
    )
