"""檢查 GPU 共用工作流程的呼叫端、版本下限與 core-gpu 的容器清理範圍。"""

import pathlib
import re
import shutil
import subprocess

import yaml

import pytest

from gpu_pin import GPU_REUSABLE_MIN_TAG, GPU_REUSABLE_PATH, GPU_REUSABLE_TAG, tag_at_least_min

pytestmark = pytest.mark.core

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
_WORKFLOWS = _REPO_ROOT / ".github" / "workflows"
_EXPECTED_CALLERS = {
    "main.yaml",
    "ci-stream-smoke.yaml",
    "ci-stream-visual-e2e.yaml",
    "ci-headless-smoke.yaml",
    "publish-stream-source.yaml",
}


@pytest.mark.parametrize("tag", ["v0.4.0", "v0.4.1", "v0.10.0", "v1.0.0"])
def test_tag_at_least_min_accepts_release(tag):
    assert tag_at_least_min(tag) is True


@pytest.mark.parametrize(
    "tag", ["main", "v0.3.0", "v0.3.9", "v0.4", "0.4.0", "v0.4.0-rc1", ""]
)
def test_tag_at_least_min_rejects_ineligible_tag(tag):
    assert tag_at_least_min(tag) is False


def _callers():
    """Map workflow file name -> list of `uses` refs to the GPU reusable."""
    found = {}
    for path in sorted(_WORKFLOWS.glob("*.y*ml")):
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for job in (doc.get("jobs") or {}).values():
            uses = (job or {}).get("uses") or ""
            if uses.startswith(GPU_REUSABLE_PATH + "@"):
                found.setdefault(path.name, []).append(uses)
    return found


def _gpu_integration_job():
    """Parsed `core-gpu` job of main.yaml."""
    doc = yaml.safe_load(
        (_WORKFLOWS / "main.yaml").read_text(encoding="utf-8")
    )
    return doc["jobs"]["core-gpu"]


def test_gpu_reusable_callers_share_one_tag():
    callers = _callers()
    tags = {ref.partition("@")[2] for refs in callers.values() for ref in refs}
    assert len(tags) == 1, f"所有呼叫端應使用相同標籤：{callers}"


def test_every_gpu_reusable_caller_meets_minimum_tag():
    for name, refs in _callers().items():
        for ref in refs:
            assert tag_at_least_min(ref.partition("@")[2]), (
                f"{name} 的 {ref} 必須使用 {GPU_REUSABLE_MIN_TAG} 以上的正式版本"
            )


def test_gpu_reusable_callers_are_the_known_five():
    callers = set(_callers())
    assert callers == _EXPECTED_CALLERS, (
        f"missing={_EXPECTED_CALLERS - callers}, extra={callers - _EXPECTED_CALLERS}. "
        "When adding or removing a caller, update _EXPECTED_CALLERS and the "
        "doc/test/TEST.md row."
    )


def test_dependabot_comment_matches_gpu_reusable_tag():
    text = (_REPO_ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8")
    tags = {
        tag
        for line in text.splitlines() if line.lstrip().startswith("#")
        for tag in re.findall(r"gpu-self-hosted\.yml@([\w./+-]+)", line)
    }
    assert tags == {GPU_REUSABLE_TAG}, (
        f".github/dependabot.yml comments must mention gpu-self-hosted.yml@{GPU_REUSABLE_TAG}; "
        f"found tags {tags}"
    )


def has_reap_filter(job):
    return "reap-container-filter" in job.get("with", {})


def test_core_gpu_requires_reap_filter_input():
    assert not has_reap_filter({"with": {}})
    assert has_reap_filter(_gpu_integration_job())


def test_gpu_integration_passes_run_scoped_reap_filter():
    """isaac#344: the cancel-safe reap step only runs when the input is set."""
    job = _gpu_integration_job()
    path, _, tag = job["uses"].partition("@")
    assert path == GPU_REUSABLE_PATH
    assert tag_at_least_min(tag)
    assert job["with"]["reap-container-filter"] == (
        "label=com.docker.compose.project="
        "isaac-baseline-${{ github.run_id }}-${{ github.run_attempt }}"
    )


_STUB_SETUP = "#!/usr/bin/env bash\nprintf 'WS_PATH=/x\\n' > .env.generated\n"
_STUB_SUCCESS = "#!/usr/bin/env bash\nexit 0\n"
_STUB_BASELINE = (
    "#!/usr/bin/env bash\n"
    'echo "BASELINE_PROJECT=${BASELINE_PROJECT}" > "${OBSERVED}"\n'
)


def test_reap_filter_matches_script_baseline_project(tmp_path):
    """isaac#344: the reap filter must name the project the script runs.

    The script is run for real (stubbed setup/build/baseline) with a known
    run id and attempt; the project it exports is the expected value.
    """
    (tmp_path / "script" / "ci").mkdir(parents=True)
    (tmp_path / "test").mkdir()
    for name in ("gpu_job_lib.sh", "gpu_integration_job.sh"):
        shutil.copy(_REPO_ROOT / "script" / "ci" / name,
                    tmp_path / "script" / "ci" / name)
    for rel, body in (
        ("script/setup.sh", _STUB_SETUP),
        ("script/build.sh", _STUB_SUCCESS),
        ("script/ci/uid_matrix.sh", _STUB_SUCCESS),
        ("script/ci/official_startuptests.sh", _STUB_SUCCESS),
        ("script/ci/official_pythontests.sh", _STUB_SUCCESS),
        ("test/assert_pytest_baseline.sh", _STUB_BASELINE),
    ):
        (tmp_path / rel).write_text(body, encoding="utf-8")
    for path in tmp_path.rglob("*.sh"):
        path.chmod(0o755)
    observed = tmp_path / "observed.txt"
    env = {
        "PATH": "/usr/bin:/bin",
        "GITHUB_WORKSPACE": str(tmp_path),
        "GITHUB_RUN_ID": "111",
        "GITHUB_RUN_ATTEMPT": "2",
        "OBSERVED": str(observed),
        "ISAAC_CI_CACHE_ROOT": str(tmp_path / "ci-cache"),
    }
    subprocess.run(
        ["bash", str(tmp_path / "script" / "ci" / "gpu_integration_job.sh")],
        check=True, env=env, cwd=tmp_path, capture_output=True,
    )
    project = observed.read_text(encoding="utf-8").strip().split("=", 1)[1]

    template = _gpu_integration_job()["with"]["reap-container-filter"]
    rendered = template.replace("${{ github.run_id }}", "111").replace(
        "${{ github.run_attempt }}", "2"
    )
    assert rendered == f"label=com.docker.compose.project={project}"
