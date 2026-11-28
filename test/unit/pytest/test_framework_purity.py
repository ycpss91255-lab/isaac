"""Regression checks for the framework-only CI lint."""

import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.core

ROOT = Path(__file__).resolve().parents[3]
LINT = Path("script/ci/check_framework_purity.sh")


def test_checkout_passes_framework_purity_lint():
    result = subprocess.run(["bash", str(ROOT / LINT)], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.fixture
def checkout(tmp_path):
    lint = tmp_path / LINT
    lint.parent.mkdir(parents=True)
    shutil.copyfile(ROOT / LINT, lint)
    package = tmp_path / "framework/isaac_devkit"
    package.mkdir(parents=True)
    (package / "driver.py").write_text("# Generic driver\n")
    (package.parent / "pyproject.toml").write_text('[project]\nname = "isaac-devkit"\n')
    return tmp_path


@pytest.mark.parametrize(
    ("path", "term"),
    [
        ("framework/isaac_devkit/driver.py", "ForkLift"),
        ("framework/isaac_devkit/driver.py", "CoreSAM"),
        ("framework/isaac_devkit/driver.py", "PALLET"),
        ("framework/isaac_devkit/driver.py", "PushBack"),
        ("framework/pyproject.toml", "OpenBase"),
    ],
)
def test_lint_reports_application_terms_in_contract(checkout, path, term):
    with (checkout / path).open("a") as source:
        source.write(f"# {term}\n")
    result = subprocess.run(["bash", str(checkout / LINT)], capture_output=True, text=True)
    assert result.returncode == 1
    assert path in result.stdout
    assert term in result.stdout


def test_lint_ignores_files_outside_contract(checkout):
    for path in ("src/example.py", "framework/README.md", "framework/isaac_devkit/cache.txt"):
        file = checkout / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text("# forklift\n")
    result = subprocess.run(["bash", str(checkout / LINT)], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_lint_fails_if_contract_configuration_is_missing(checkout):
    (checkout / "framework/pyproject.toml").unlink()
    result = subprocess.run(["bash", str(checkout / LINT)], capture_output=True, text=True)
    assert result.returncode != 0
    assert "pyproject.toml" in result.stderr


def test_core_ci_runs_framework_purity_lint():
    import yaml

    workflow = yaml.safe_load((ROOT / ".github/workflows/main.yaml").read_text())
    steps = workflow["jobs"]["core-unit"]["steps"]
    assert any(step.get("run") == f"bash {LINT}" and "if" not in step for step in steps)
