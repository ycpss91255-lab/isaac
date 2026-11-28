"""Per-PR wiring for the official Isaac Sim startup suite (isaac#436)."""

from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.core

_ROOT = Path(__file__).resolve().parents[3]
_HELPER = _ROOT / "script/ci/official_startuptests.sh"


@pytest.fixture(scope="module")
def gpu_inputs():
    workflow = yaml.safe_load((_ROOT / ".github/workflows/main.yaml").read_text())
    return workflow["jobs"]["core-gpu"]["with"]


def test_gpu_job_calls_official_startuptests(gpu_inputs):
    script = gpu_inputs["run-script"]
    assert script == "./script/ci/gpu_integration_job.sh"
    assert _HELPER.name in (_ROOT / script).read_text()


def test_startuptests_only_need_isaac_sim():
    assert _HELPER.is_file(), f"Missing Isaac Sim startup suite helper: {_HELPER.name}"
    assert "isaaclab" not in _HELPER.read_text().lower()


def test_gpu_job_uploads_the_startuptests_directory_even_on_failure(gpu_inputs):
    assert gpu_inputs.get("artifact-name")
    assert Path(gpu_inputs["artifact-path"]) == Path("artifacts/startuptests")
    assert gpu_inputs.get("artifact-when") == "always"
