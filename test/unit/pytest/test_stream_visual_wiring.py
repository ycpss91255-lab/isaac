"""Tier B belongs to the same GPU scope and required check as Tier A (#173)."""

import re
import runpy
from pathlib import Path

import pytest
import yaml

from test_stream_visual_job import _check_cleanup, _value, run_job

pytestmark = pytest.mark.stream

_ROOT = Path(__file__).resolve().parents[3]
_WORKFLOWS = _ROOT / ".github/workflows"
_JOB = "stream-visual-e2e"
_WORKFLOW = f"ci-{_JOB}.yaml"


def _load(filename):
    path = _WORKFLOWS / filename
    assert path.is_file(), f"missing {filename}"
    return yaml.safe_load(path.read_text())


def test_visual_workflow_triggers_and_gpu_job():
    doc = _load(_WORKFLOW)
    assert doc["name"] == "CI: Stream Visual E2E"
    assert set(doc.get("on", doc.get(True))) == {"workflow_call", "workflow_dispatch"}
    gpu = doc["jobs"][_JOB]
    smoke = _load("ci-stream-smoke.yaml")["jobs"]["stream-smoke"]
    assert gpu["uses"] == smoke["uses"]
    inputs = gpu["with"]
    assert inputs["run-script"] == "./script/ci/stream_visual_e2e_job.sh"
    assert inputs["artifact-name"]
    assert inputs["artifact-path"].rstrip("/") == "artifacts/stream-visual-e2e"
    assert inputs.get("artifact-when", "failure") in {"failure", "always"}


def test_reap_filter_matches_only_containers_from_same_run_and_attempt(run_job):
    inputs = _load(_WORKFLOW)["jobs"][_JOB]["with"]
    key, template = inputs["reap-container-filter"].split("=", 1)
    assert key == "name"
    assert template.startswith("^/")

    containers = {}
    for run_id, attempt in ((12, 1), (123, 1), (12, 10)):
        result, calls, _ = run_job(run_id, attempt)
        assert result.returncode == 0, result.stdout
        project = _check_cleanup(calls)
        names = [f"/{project}-stream-1"]
        names.extend("/" + _value(call, "--name ") for call in calls if call.startswith("docker run "))
        assert len(set(names)) == 3
        containers[run_id, attempt] = names

    for run_id, attempt in containers:
        rendered = template.replace("${{ github.run_id }}", str(run_id))
        pattern = re.compile(rendered.replace("${{ github.run_attempt }}", str(attempt)))
        for owner, names in containers.items():
            for name in names:
                matched = pattern.search(name) is not None
                assert matched == (owner == (run_id, attempt)), (pattern.pattern, name)


def test_main_uses_the_stream_smoke_conditions_and_gates_visual_result():
    jobs = _load("main.yaml")["jobs"]
    assert _JOB in jobs
    visual = jobs[_JOB]
    assert visual["uses"] == f"./.github/workflows/{_WORKFLOW}"
    assert set(visual["needs"]) == set(jobs["stream-smoke"]["needs"]) == {"changes", "stream-unit"}
    assert visual["if"] == jobs["stream-smoke"]["if"]
    assert _JOB in jobs["gate"]["needs"]


def test_visual_paths_select_stream_for_prs():
    select = runpy.run_path(str(_ROOT / "script/ci/changed_groups.py"))["select"]
    paths = [
        f".github/workflows/{_WORKFLOW}",
        "script/ci/stream_visual_e2e_job.sh",
        "script/ci/stream_visual_e2e.sh",
        "script/ci/visual_e2e/ports.py",
        "script/ci/visual_e2e/probe.mjs",
        "script/ci/visual_e2e/verdict.py",
        "script/ci/visual_e2e/scene/min_scene.py",
    ]
    assert [p for p in paths if select("pull_request", [p]) != ["stream", "docs"]] == []


def test_workflow_name_guard_accepts_the_e2e_acronym(tmp_path):
    lint = runpy.run_path(str(_ROOT / "script/ci/lint_workflow_names.py"))["lint"]
    workflows = tmp_path / ".github/workflows"
    workflows.mkdir(parents=True)
    (workflows / _WORKFLOW).write_text('name: "CI: Stream Visual E2E"\n')
    assert lint(tmp_path) == []
