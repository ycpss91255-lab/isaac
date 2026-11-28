"""The official Python buckets use the existing scoped GPU workflow."""

import subprocess
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.core

ROOT = Path(__file__).resolve().parents[3]
HELPER = ROOT / "script/ci/official_pythontests.sh"


def test_official_buckets_share_the_core_gpu_job_and_always_upload_reports():
    workflow = yaml.safe_load((ROOT / ".github/workflows/main.yaml").read_text())
    job = workflow["jobs"]["core-gpu"]
    assert "needs.changes.outputs.core == 'true'" in job["if"]
    inputs = job["with"]
    assert HELPER.name in (ROOT / inputs["run-script"]).read_text()
    assert inputs["artifact-path"].splitlines() == [
        "artifacts/startuptests", "artifacts/pythontests",
    ]
    assert inputs["artifact-when"] == "always"
    assert inputs["timeout-minutes"] >= 60


@pytest.mark.parametrize(
    ("mode", "success", "diagnostic"),
    [
        ("pass", True, "deprecated: 2/2 passed"),
        ("failure", False, "failures=1"),
        ("error", False, "errors=1"),
        ("skip", False, "skipped=1"),
        ("missing", False, "Invalid pythontests report"),
        ("truncated", False, "Invalid pythontests report"),
        ("short", False, "expected at least 17"),
        ("docker", False, "Docker exited with status 23"),
    ],
)
def test_runs_both_buckets_serially_and_checks_junit(
    tmp_path, monkeypatch, mode, success, diagnostic,
):
    (tmp_path / ".env.generated").write_text("DOCKER_HUB_USER=fixture\nIMAGE_NAME=isaac\n")
    docker = tmp_path / "docker"
    docker.write_text(
        """#!/usr/bin/env python3
import os
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

args = sys.argv[1:]
bucket = args[args.index("--bucket") + 1]
with Path("calls").open("a") as calls:
    print(bucket, file=calls)
assert args[:4] == ["run", "--rm", "--gpus", "all"]
assert args[args.index("--workdir") + 1] == "/tmp"
assert Path(args[-1]).parent == Path("/artifacts")
assert args[args.index("--label") + 1] == "com.docker.compose.project=test-project"
assert args[args.index("--entrypoint") + 1] == "python3"
assert args[-8:-1] == [
    "fixture/isaac:test", "/isaac-sim/run_tests.py", "--suite",
    "pythontests", "--bucket", bucket, "--output",
]
mount = next(arg for arg in args if arg.endswith(":" + args[-1]))
report = Path(mount.split(":", 1)[0])
mode = os.environ["MODE"] if bucket == "asset" else "pass"
if mode == "missing":
    sys.exit(0)
if mode == "truncated":
    report.write_text("<testsuite")
    sys.exit(0)
count = 2 if bucket == "deprecated" else 16 if mode == "short" else 17
suite = ET.Element("testsuite", name=f"pythontests.{bucket}", tests=str(count),
                   failures=str(int(mode == "failure")), errors=str(int(mode == "error")),
                   skipped=str(int(mode == "skip")), time="3.0")
for index in range(count):
    case = ET.SubElement(suite, "testcase", name=f"test-{index}")
    if index == 0 and mode in ("failure", "error", "skip"):
        ET.SubElement(case, "skipped" if mode == "skip" else mode)
ET.ElementTree(suite).write(report)
sys.exit(23 if mode == "docker" else 0)
"""
    )
    docker.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}:/usr/bin:/bin")
    monkeypatch.setenv("BASELINE_PROJECT", "test-project")
    monkeypatch.setenv("MODE", mode)
    reports = tmp_path / "artifacts" / "pythontests"
    reports.mkdir(parents=True)
    (reports / "asset.xml").write_text("stale report")
    result = subprocess.run(
        ["bash", HELPER], cwd=tmp_path, capture_output=True, text=True,
    )

    assert (result.returncode == 0) == success, result.stdout + result.stderr
    assert (tmp_path / "calls").read_text().splitlines() == ["asset", "deprecated"]
    assert diagnostic in result.stdout + result.stderr
    assert (reports / "deprecated.xml").is_file()
    assert (reports / "asset.xml").read_text() != "stale report"
