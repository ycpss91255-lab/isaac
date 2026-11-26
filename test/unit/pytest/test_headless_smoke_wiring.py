"""The headless boot check is wired into CI (isaac#461).

The headless stage was only ever built. These guard the wiring that makes the
boot check run: the workflow, the main.yaml job, the gate, the image bake and
the scope rule. The verdict logic itself is in
test/bats/smoke/headless_smoke_spec.bats.
"""

import importlib.util
import sys
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.headless

_ROOT = Path(__file__).resolve().parents[3]
_WORKFLOWS = _ROOT / ".github" / "workflows"


def _load(name):
    return yaml.safe_load((_WORKFLOWS / name).read_text())


def _triggers(doc):
    return doc.get("on", doc.get(True))


def test_the_smoke_workflow_runs_the_job_script_on_the_gpu_runner():
    job = _load("ci-headless-smoke.yaml")["jobs"]["headless-smoke"]
    assert job["uses"].startswith(
        "ycpss91255-lab/.github/.github/workflows/gpu-self-hosted.yml@"
    )
    assert job["with"]["run-script"] == "./script/ci/headless_smoke_job.sh"


def test_the_smoke_workflow_is_callable_and_manually_dispatchable():
    triggers = _triggers(_load("ci-headless-smoke.yaml"))
    assert "workflow_call" in triggers
    assert "workflow_dispatch" in triggers
    assert "schedule" not in triggers


def test_main_runs_the_smoke_for_the_headless_group_with_the_fork_guard():
    cfg = _load("main.yaml")["jobs"]["headless-smoke"]
    assert cfg["uses"] == "./.github/workflows/ci-headless-smoke.yaml"
    assert "needs.changes.outputs.headless == 'true'" in str(cfg["if"])
    assert "github.event.pull_request.head.repo.full_name == github.repository" in str(
        cfg["if"]
    )


def test_the_gate_waits_for_the_smoke():
    assert "headless-smoke" in _load("main.yaml")["jobs"]["gate"]["needs"]


def test_the_scripts_are_baked_into_the_image_for_the_bats_spec():
    dockerfile = (_ROOT / "Dockerfile").read_text()
    assert "script/ci/headless_smoke.sh" in dockerfile
    assert "script/ci/headless_smoke_job.sh" in dockerfile


def test_a_change_to_the_smoke_selects_the_headless_group():
    spec = importlib.util.spec_from_file_location(
        "changed_groups", _ROOT / "script" / "ci" / "changed_groups.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("changed_groups", module)
    spec.loader.exec_module(module)
    for path in (
        "script/ci/headless_smoke.sh",
        "script/ci/headless_smoke_job.sh",
        ".github/workflows/ci-headless-smoke.yaml",
    ):
        assert "headless" in module.classify(path), path
