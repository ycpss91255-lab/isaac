"""檢查 GPU 共用工作流程的呼叫端、版本下限與各次執行的容器清理範圍。"""

import pathlib
import re
import shlex
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
    "ci-official-native-python.yaml",
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


def _gpu_reusable_jobs():
    """逐一列出呼叫 GPU 共用工作流程的檔名、作業名稱與設定。"""
    for path in sorted(_WORKFLOWS.glob("*.y*ml")):
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for name, job in (doc.get("jobs") or {}).items():
            uses = (job or {}).get("uses") or ""
            if uses.startswith(GPU_REUSABLE_PATH + "@"):
                yield path.name, name, job


def _gpu_integration_job():
    """讀取 main.yaml 的 core-gpu 作業。"""
    doc = yaml.safe_load(
        (_WORKFLOWS / "main.yaml").read_text(encoding="utf-8")
    )
    return doc["jobs"]["core-gpu"]


def test_gpu_reusable_callers_share_one_tag():
    tags = {job["uses"].partition("@")[2] for _, _, job in _gpu_reusable_jobs()}
    assert len(tags) == 1, f"所有呼叫端應使用相同標籤：{tags}"


def test_every_gpu_reusable_caller_meets_minimum_tag():
    for name, _, job in _gpu_reusable_jobs():
        ref = job["uses"]
        assert tag_at_least_min(ref.partition("@")[2]), (
            f"{name} 的 {ref} 必須使用 {GPU_REUSABLE_MIN_TAG} 以上的正式版本"
        )


def test_gpu_reusable_callers_match_the_expected_set():
    callers = {name for name, _, _ in _gpu_reusable_jobs()}
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
    assert has_reap_filter(_gpu_integration_job())


def test_gpu_integration_passes_run_scoped_reap_filter():
    """取消作業時，共用工作流程依呼叫端提供的篩選器清理容器（isaac#344）。"""
    job = _gpu_integration_job()
    path, _, tag = job["uses"].partition("@")
    assert path == GPU_REUSABLE_PATH
    assert tag_at_least_min(tag)
    assert job["with"]["reap-container-filter"] == (
        "label=com.docker.compose.project="
        "isaac-baseline-${{ github.run_id }}-${{ github.run_attempt }}"
    )


def test_run_scoped_project_callers_pass_reap_filter():
    """入口腳本依執行編號設定 Compose 專案時，清理篩選器也須限定到該次執行。"""
    # stream 與 headless 的 SMOKE_PROJECT 只傳給有清理 trap 的冒煙腳本。
    project_assignment = re.compile(
        r"^[ \t]*(?:export[ \t]+)?(?:BASELINE_PROJECT|(?:COMPOSE_)?PROJECT_NAME)="
        r"[^\s#]*\$\{?GITHUB_RUN_ID\b",
        re.MULTILINE,
    )
    checked = 0
    for workflow, name, job in _gpu_reusable_jobs():
        inputs = job["with"]
        # publish 的入口以 bash 啟動，其餘入口直接執行腳本。
        command = shlex.split(inputs["run-script"])
        script = _REPO_ROOT / (command[1] if command[0] == "bash" else command[0])
        if not project_assignment.search(script.read_text(encoding="utf-8")):
            continue

        checked += 1
        reap_filter = inputs.get("reap-container-filter", "")
        for field in ("run_id", "run_attempt"):
            assert re.search(r"\$\{\{\s*github\." + field + r"\s*\}\}", reap_filter), (
                f"{workflow} 的 {name} 清理篩選器缺少 github.{field}：{reap_filter!r}"
            )
    assert checked > 0, "至少要檢查一個依執行編號設定 Compose 專案的作業"


_RUN_ID = "111"
_RUN_ATTEMPT = "2"


def _write_stub(path, body):
    path.write_text("#!/usr/bin/env bash\n" + body, encoding="utf-8")
    path.chmod(0o755)


def _run_gpu_job(tmp_path, mutation=None):
    """在暫存目錄執行作業，回傳基準檢查收到的專案名稱與替身呼叫順序。"""
    ci = tmp_path / "script" / "ci"
    ci.mkdir(parents=True)
    (tmp_path / "test").mkdir()
    for name in ("gpu_job_lib.sh", "gpu_integration_job.sh"):
        shutil.copy(_REPO_ROOT / "script" / "ci" / name, ci)
    if mutation is not None:
        name, old, new = mutation
        script = ci / name
        source = script.read_text(encoding="utf-8")
        assert old in source, f"{name} 找不到要替換的文字：{old!r}"
        script.write_text(source.replace(old, new, 1), encoding="utf-8")

    record_call = 'echo "${0##*/}" >> "$CALL_LOG"\n'
    for rel, body in (
        ("script/setup.sh", "echo 'WS_PATH=/x' > .env.generated\n"),
        ("script/build.sh", ""),
        ("script/ci/uid_matrix.sh", ""),
        ("script/ci/official_startuptests.sh", ""),
        ("script/ci/official_pythontests.sh", ""),
        ("test/assert_pytest_baseline.sh", 'echo "$BASELINE_PROJECT" > "$OBSERVED"\n'),
    ):
        _write_stub(tmp_path / rel, record_call + body)

    stub_bin = tmp_path / "bin"
    stub_bin.mkdir()
    # PATH 僅開放共用腳本使用的系統工具，新增其他外部指令時會立即報錯。
    for name in (
        "awk", "bash", "chmod", "cp", "dirname", "find", "flock", "ln", "mkdir",
        "mv", "rm", "sed", "sort",
    ):
        (stub_bin / name).symlink_to(shutil.which(name, path="/usr/bin:/bin"))
    for name in ("docker", "git", "sudo", "ssh"):
        message = f"UNSTUBBED {name}"
        _write_stub(
            stub_bin / name,
            f'echo "{message}" >> "$CALL_LOG"\necho "{message}" >&2\nexit 99\n',
        )

    observed = tmp_path / "observed.txt"
    call_log = tmp_path / "calls.log"
    env = {
        "PATH": str(stub_bin),
        "GITHUB_WORKSPACE": str(tmp_path),
        "GITHUB_RUN_ID": _RUN_ID,
        "GITHUB_RUN_ATTEMPT": _RUN_ATTEMPT,
        "CALL_LOG": str(call_log),
        "OBSERVED": str(observed),
        "ISAAC_CI_CACHE_ROOT": str(tmp_path / "ci-cache"),
    }
    subprocess.run(
        ["bash", ci / "gpu_integration_job.sh"], check=True, env=env, cwd=tmp_path
    )
    project = observed.read_text(encoding="utf-8").strip()
    calls = call_log.read_text(encoding="utf-8").splitlines()
    return project, calls


def _reap_filter_matches_project(template, project):
    rendered = template.replace("${{ github.run_id }}", _RUN_ID).replace(
        "${{ github.run_attempt }}", _RUN_ATTEMPT
    )
    return rendered == f"label=com.docker.compose.project={project}"


def test_reap_filter_matches_script_baseline_project(tmp_path):
    """篩選器須選中基準檢查實際使用的 Compose 專案（isaac#344）。"""
    project, _ = _run_gpu_job(tmp_path)
    template = _gpu_integration_job()["with"]["reap-container-filter"]
    assert _reap_filter_matches_project(template, project)


def test_gpu_job_calls_all_stubs_in_order(tmp_path):
    """完整執行須依序呼叫六個腳本替身，記錄中不得出現額外呼叫。"""
    _, calls = _run_gpu_job(tmp_path)
    assert calls == [
        "setup.sh",
        "build.sh",
        "uid_matrix.sh",
        "assert_pytest_baseline.sh",
        "official_startuptests.sh",
        "official_pythontests.sh",
    ]


def test_gpu_job_rejects_unstubbed_docker(tmp_path):
    """共用函式新增 docker 呼叫時，替身須記錄指令並中止作業。"""
    mutation = ("gpu_job_lib.sh", "gpu_job_build() {", "gpu_job_build() {\n  docker ps")
    with pytest.raises(subprocess.CalledProcessError) as error:
        _run_gpu_job(tmp_path, mutation)
    assert error.value.returncode == 99
    calls = (tmp_path / "calls.log").read_text(encoding="utf-8").splitlines()
    assert calls[-1] == "UNSTUBBED docker"


def test_reap_filter_detects_changed_script_prefix(tmp_path):
    """僅改動腳本匯出的專案前綴時，原篩選器須比對失敗。"""
    mutation = ("gpu_integration_job.sh", "isaac-baseline-", "isaac-other-")
    project, _ = _run_gpu_job(tmp_path, mutation)
    template = _gpu_integration_job()["with"]["reap-container-filter"]
    assert not _reap_filter_matches_project(template, project)


def test_reap_filter_detects_changed_workflow_prefix(tmp_path):
    """僅改動工作流程的篩選器前綴時，與實際專案的比對須失敗。"""
    project, _ = _run_gpu_job(tmp_path)
    template = _gpu_integration_job()["with"]["reap-container-filter"]
    mutated = template.replace("isaac-baseline-", "isaac-other-", 1)
    assert not _reap_filter_matches_project(mutated, project)
